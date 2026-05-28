from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch
from django.utils.text import slugify
from django.urls import reverse
from django.contrib import messages

from .models import (
    TenantMembership, ForumCategory, ForumPost, ForumComment, ForumReaction,
)


def _get_forum_context(request):
    """Return (tenant, membership) or (None, None) if user has no access."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return None, None
    membership = TenantMembership.objects.filter(
        tenant=tenant, user=request.user, is_active=True,
    ).select_related('tenant').first()
    return tenant, membership


def _build_role_map(tenant, user_ids):
    """Return {user_id: role_display} for a set of user IDs within a tenant."""
    memberships = TenantMembership.objects.filter(
        tenant=tenant, user_id__in=user_ids, is_active=True,
    ).values_list('user_id', 'role')
    role_labels = {'tenant_admin': 'Instructor', 'student': 'Student'}
    return {uid: role_labels.get(role, 'Member') for uid, role in memberships}


def _get_user_reactions(user, post_ids, tenant):
    """Return {post_id: set(reaction_types)} for the current user."""
    reactions = ForumReaction.objects.filter(
        tenant=tenant, user=user, post_id__in=post_ids,
    ).values_list('post_id', 'reaction_type')
    result = {}
    for post_id, rtype in reactions:
        result.setdefault(post_id, set()).add(rtype)
    return result


def _redirect_with_fallback(request, fallback_url_name, **kwargs):
    """Redirect to a safe `next` URL or fallback route."""
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(fallback_url_name, **kwargs)


REACTION_META = [
    ('like', 'fa-thumbs-up', 'Like'),
    ('celebrate', 'fa-hands-clapping', 'Celebrate'),
    ('support', 'fa-heart', 'Support'),
    ('insightful', 'fa-lightbulb', 'Insightful'),
]


@login_required
def forum_feed(request):
    tenant, membership = _get_forum_context(request)
    if not tenant or not membership:
        return redirect('home')

    categories = ForumCategory.objects.filter(tenant=tenant, is_active=True)
    composer_content = ''
    composer_category_id = ''

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        category_id = request.POST.get('category', '')
        image = request.FILES.get('image')
        composer_content = content
        composer_category_id = category_id

        if not content:
            messages.error(request, 'Post content cannot be empty.')
        elif len(content) > 5000:
            messages.error(request, 'Post content cannot exceed 5000 characters.')
        else:
            category = None
            if category_id:
                category = ForumCategory.objects.filter(id=category_id, tenant=tenant).first()

            post = ForumPost.objects.create(
                tenant=tenant,
                author=request.user,
                content=content,
                category=category,
                image=image,
            )
            messages.success(request, 'Post created!')
            return redirect(f'{reverse("forum_feed")}#post-{post.id}')

    active_category = request.GET.get('category', '')
    sort = request.GET.get('sort', 'recent')

    posts = ForumPost.objects.filter(tenant=tenant).select_related('author', 'category')

    if active_category:
        posts = posts.filter(category__slug=active_category)

    posts = posts.annotate(
        comment_count=Count('comments', distinct=True),
        reaction_count=Count('reactions', distinct=True),
    )

    if sort == 'popular':
        posts = posts.order_by('-is_pinned', '-reaction_count', '-created_at')
    else:
        posts = posts.order_by('-is_pinned', '-created_at')

    paginator = Paginator(posts, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    post_ids = [p.id for p in page_obj]
    user_reactions = _get_user_reactions(request.user, post_ids, tenant)
    author_ids = {p.author_id for p in page_obj}
    role_map = _build_role_map(tenant, author_ids)

    reaction_counts = {}
    if post_ids:
        counts = (
            ForumReaction.objects.filter(post_id__in=post_ids)
            .values('post_id', 'reaction_type')
            .annotate(cnt=Count('id'))
        )
        for row in counts:
            reaction_counts.setdefault(row['post_id'], {})[row['reaction_type']] = row['cnt']

    comments_by_post = {}
    comment_reaction_map = {}
    comment_rcounts = {}
    if post_ids:
        replies_qs = ForumComment.objects.filter(
            tenant=tenant, post_id__in=post_ids, parent__isnull=False,
        ).select_related('author').order_by('created_at')
        top_level_comments = (
            ForumComment.objects.filter(
                tenant=tenant, post_id__in=post_ids, parent__isnull=True,
            )
            .select_related('author')
            .prefetch_related(Prefetch('replies', queryset=replies_qs))
            .order_by('created_at')
        )

        comment_ids = []
        for comment in top_level_comments:
            comments_by_post.setdefault(comment.post_id, []).append(comment)
            author_ids.add(comment.author_id)
            comment_ids.append(comment.id)
            for reply in comment.replies.all():
                author_ids.add(reply.author_id)
                comment_ids.append(reply.id)

        if comment_ids:
            user_comment_reactions = ForumReaction.objects.filter(
                tenant=tenant, user=request.user, comment_id__in=comment_ids,
            ).values_list('comment_id', 'reaction_type')
            for cid, rtype in user_comment_reactions:
                comment_reaction_map.setdefault(cid, set()).add(rtype)

            counts = (
                ForumReaction.objects.filter(comment_id__in=comment_ids)
                .values('comment_id', 'reaction_type')
                .annotate(cnt=Count('id'))
            )
            for row in counts:
                comment_rcounts.setdefault(row['comment_id'], {})[row['reaction_type']] = row['cnt']

        role_map = _build_role_map(tenant, author_ids)

    user_post_count = ForumPost.objects.filter(tenant=tenant, author=request.user).count()

    top_posters = (
        ForumPost.objects.filter(tenant=tenant)
        .values('author__id', 'author__first_name', 'author__last_name', 'author__username')
        .annotate(post_count=Count('id'))
        .order_by('-post_count')[:5]
    )

    return render(request, 'forum/feed.html', {
        'page_obj': page_obj,
        'categories': categories,
        'active_category': active_category,
        'sort': sort,
        'user_reactions': user_reactions,
        'reaction_counts': reaction_counts,
        'comments_by_post': comments_by_post,
        'comment_reaction_map': comment_reaction_map,
        'comment_rcounts': comment_rcounts,
        'role_map': role_map,
        'reaction_meta': REACTION_META,
        'membership': membership,
        'user_post_count': user_post_count,
        'top_posters': top_posters,
        'composer_content': composer_content,
        'composer_category_id': composer_category_id,
    })


@login_required
def forum_post_detail(request, post_id):
    tenant, membership = _get_forum_context(request)
    if not tenant or not membership:
        return redirect('home')

    post = get_object_or_404(ForumPost, id=post_id, tenant=tenant)

    comments = (
        ForumComment.objects.filter(post=post, parent__isnull=True)
        .select_related('author')
        .prefetch_related('replies__author')
    )

    author_ids = {post.author_id}
    for c in comments:
        author_ids.add(c.author_id)
        for r in c.replies.all():
            author_ids.add(r.author_id)
    role_map = _build_role_map(tenant, author_ids)

    user_reactions = _get_user_reactions(request.user, [post.id], tenant)

    comment_reaction_map = {}
    comment_ids = []
    for c in comments:
        comment_ids.append(c.id)
        for r in c.replies.all():
            comment_ids.append(r.id)
    if comment_ids:
        user_comment_reactions = ForumReaction.objects.filter(
            tenant=tenant, user=request.user, comment_id__in=comment_ids,
        ).values_list('comment_id', 'reaction_type')
        for cid, rtype in user_comment_reactions:
            comment_reaction_map.setdefault(cid, set()).add(rtype)

    reaction_counts = {}
    post_rcounts = (
        ForumReaction.objects.filter(post=post)
        .values('reaction_type')
        .annotate(cnt=Count('id'))
    )
    reaction_counts[post.id] = {row['reaction_type']: row['cnt'] for row in post_rcounts}

    comment_rcounts = {}
    if comment_ids:
        cr = (
            ForumReaction.objects.filter(comment_id__in=comment_ids)
            .values('comment_id', 'reaction_type')
            .annotate(cnt=Count('id'))
        )
        for row in cr:
            comment_rcounts.setdefault(row['comment_id'], {})[row['reaction_type']] = row['cnt']

    return render(request, 'forum/post_detail.html', {
        'post': post,
        'comments': comments,
        'role_map': role_map,
        'user_reactions': user_reactions,
        'comment_reaction_map': comment_reaction_map,
        'reaction_counts': reaction_counts,
        'comment_rcounts': comment_rcounts,
        'reaction_meta': REACTION_META,
        'membership': membership,
    })


@login_required
def forum_create_post(request):
    tenant, membership = _get_forum_context(request)
    if not tenant or not membership:
        return redirect('home')

    categories = ForumCategory.objects.filter(tenant=tenant, is_active=True)
    editing_post = None
    post_id = request.GET.get('edit')
    if post_id:
        editing_post = ForumPost.objects.filter(
            id=post_id, tenant=tenant, author=request.user,
        ).first()

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        category_id = request.POST.get('category', '')
        image = request.FILES.get('image')

        if not content:
            messages.error(request, 'Post content cannot be empty.')
            return render(request, 'forum/create_post.html', {
                'categories': categories,
                'editing_post': editing_post,
            })

        if len(content) > 5000:
            messages.error(request, 'Post content cannot exceed 5000 characters.')
            return render(request, 'forum/create_post.html', {
                'categories': categories,
                'editing_post': editing_post,
            })

        category = None
        if category_id:
            category = ForumCategory.objects.filter(id=category_id, tenant=tenant).first()

        if editing_post:
            editing_post.content = content
            editing_post.category = category
            editing_post.is_edited = True
            if image:
                editing_post.image = image
            editing_post.save()
            messages.success(request, 'Post updated.')
            return redirect('forum_post_detail', post_id=editing_post.id)
        else:
            post = ForumPost.objects.create(
                tenant=tenant,
                author=request.user,
                content=content,
                category=category,
                image=image,
            )
            messages.success(request, 'Post created!')
            return redirect('forum_feed')

    return render(request, 'forum/create_post.html', {
        'categories': categories,
        'editing_post': editing_post,
    })


@login_required
@require_http_methods(["POST"])
def forum_delete_post(request, post_id):
    tenant, membership = _get_forum_context(request)
    if not tenant or not membership:
        return redirect('home')

    post = get_object_or_404(ForumPost, id=post_id, tenant=tenant)
    if post.author != request.user and membership.role != 'tenant_admin':
        messages.error(request, 'You cannot delete this post.')
        return redirect('forum_feed')

    post.delete()
    messages.success(request, 'Post deleted.')
    return redirect('forum_feed')


@login_required
@require_http_methods(["POST"])
def forum_add_comment(request, post_id):
    tenant, membership = _get_forum_context(request)
    if not tenant or not membership:
        return redirect('home')

    post = get_object_or_404(ForumPost, id=post_id, tenant=tenant)
    content = request.POST.get('content', '').strip()
    parent_id = request.POST.get('parent_id', '')

    if not content:
        messages.error(request, 'Comment cannot be empty.')
        return _redirect_with_fallback(request, 'forum_post_detail', post_id=post.id)

    parent = None
    if parent_id:
        parent = ForumComment.objects.filter(
            id=parent_id, post=post, tenant=tenant, parent__isnull=True,
        ).first()

    ForumComment.objects.create(
        tenant=tenant,
        post=post,
        author=request.user,
        parent=parent,
        content=content,
    )

    return _redirect_with_fallback(request, 'forum_post_detail', post_id=post.id)


@login_required
@require_http_methods(["POST"])
def forum_delete_comment(request, comment_id):
    tenant, membership = _get_forum_context(request)
    if not tenant or not membership:
        return redirect('home')

    comment = get_object_or_404(ForumComment, id=comment_id, tenant=tenant)
    if comment.author != request.user and membership.role != 'tenant_admin':
        messages.error(request, 'You cannot delete this comment.')
        return _redirect_with_fallback(request, 'forum_post_detail', post_id=comment.post_id)

    post_id = comment.post_id
    comment.delete()
    messages.success(request, 'Comment deleted.')
    return _redirect_with_fallback(request, 'forum_post_detail', post_id=post_id)


@login_required
@require_http_methods(["POST"])
def forum_toggle_reaction(request):
    import json
    tenant, membership = _get_forum_context(request)
    if not tenant or not membership:
        return JsonResponse({'success': False}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    target_type = data.get('target_type', '')
    target_id = data.get('target_id')
    reaction_type = data.get('reaction_type', 'like')

    valid_types = [r[0] for r in ForumReaction.REACTION_CHOICES]
    if reaction_type not in valid_types:
        return JsonResponse({'success': False, 'error': 'Invalid reaction type'}, status=400)

    if target_type == 'post':
        post = ForumPost.objects.filter(id=target_id, tenant=tenant).first()
        if not post:
            return JsonResponse({'success': False, 'error': 'Post not found'}, status=404)
        existing = ForumReaction.objects.filter(
            tenant=tenant, user=request.user, post=post, reaction_type=reaction_type,
        ).first()
        if existing:
            existing.delete()
            action = 'removed'
        else:
            ForumReaction.objects.create(
                tenant=tenant, user=request.user, post=post, reaction_type=reaction_type,
            )
            action = 'added'
        count = ForumReaction.objects.filter(post=post, reaction_type=reaction_type).count()

    elif target_type == 'comment':
        comment = ForumComment.objects.filter(id=target_id, tenant=tenant).first()
        if not comment:
            return JsonResponse({'success': False, 'error': 'Comment not found'}, status=404)
        existing = ForumReaction.objects.filter(
            tenant=tenant, user=request.user, comment=comment, reaction_type=reaction_type,
        ).first()
        if existing:
            existing.delete()
            action = 'removed'
        else:
            ForumReaction.objects.create(
                tenant=tenant, user=request.user, comment=comment, reaction_type=reaction_type,
            )
            action = 'added'
        count = ForumReaction.objects.filter(comment=comment, reaction_type=reaction_type).count()
    else:
        return JsonResponse({'success': False, 'error': 'Invalid target_type'}, status=400)

    return JsonResponse({'success': True, 'action': action, 'count': count})


# ─── Admin / Moderation Views ───────────────────────────────────────

@login_required
def dashboard_forum_moderation(request):
    tenant = getattr(request, 'tenant', None)
    if not tenant or not request.user.is_staff:
        return redirect('dashboard_home')

    categories = ForumCategory.objects.filter(tenant=tenant, is_active=True)

    posts = (
        ForumPost.objects.filter(tenant=tenant)
        .select_related('author', 'category')
        .annotate(
            comment_count=Count('comments', distinct=True),
            reaction_count=Count('reactions', distinct=True),
        )
        .order_by('-is_pinned', '-created_at')
    )

    paginator = Paginator(posts, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'dashboard/forum_moderation.html', {
        'page_obj': page_obj,
        'categories': categories,
    })


@login_required
@require_http_methods(["POST"])
def dashboard_forum_pin_post(request, post_id):
    tenant = getattr(request, 'tenant', None)
    if not tenant or not request.user.is_staff:
        return redirect('dashboard_home')

    post = get_object_or_404(ForumPost, id=post_id, tenant=tenant)
    post.is_pinned = not post.is_pinned
    post.save(update_fields=['is_pinned'])
    messages.success(request, f'Post {"pinned" if post.is_pinned else "unpinned"}.')
    return redirect('dashboard_forum_moderation')


@login_required
def dashboard_forum_categories(request):
    tenant = getattr(request, 'tenant', None)
    if not tenant or not request.user.is_staff:
        return redirect('dashboard_home')

    categories = ForumCategory.objects.filter(tenant=tenant)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'add':
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            if name:
                slug = slugify(name)
                if ForumCategory.objects.filter(tenant=tenant, slug=slug).exists():
                    messages.error(request, f'Category "{name}" already exists.')
                else:
                    max_order = ForumCategory.objects.filter(tenant=tenant).count()
                    ForumCategory.objects.create(
                        tenant=tenant, name=name, slug=slug,
                        description=description, order=max_order,
                    )
                    messages.success(request, f'Category "{name}" created.')

        elif action == 'toggle':
            cat_id = request.POST.get('category_id')
            cat = ForumCategory.objects.filter(id=cat_id, tenant=tenant).first()
            if cat:
                cat.is_active = not cat.is_active
                cat.save(update_fields=['is_active'])
                messages.success(request, f'Category {"enabled" if cat.is_active else "disabled"}.')

        elif action == 'delete':
            cat_id = request.POST.get('category_id')
            cat = ForumCategory.objects.filter(id=cat_id, tenant=tenant).first()
            if cat:
                cat.delete()
                messages.success(request, 'Category deleted.')

        return redirect('dashboard_forum_categories')

    return render(request, 'dashboard/forum_categories.html', {
        'categories': categories,
    })
