from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (
    Bundle,
    Certification,
    Course,
    CourseAccess,
    CourseEnrollment,
    Lesson,
    AIUsageLog,
    Tenant,
    TenantConfig,
    TenantDomain,
    TenantMembership,
    UserProgress,
)
from .utils.domains import ensure_temporary_domain, normalize_domain, get_platform_base_domain
from .utils.branding import ensure_tenant_branding


def superadmin_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_superuser, login_url='login')(view_func)


@superadmin_required
def superadmin_home(request):
    tenants = Tenant.objects.all().order_by('name')
    total_tenants = tenants.count()
    active_tenants = tenants.filter(is_active=True).count()
    total_courses = Course.objects.count()
    total_lessons = Lesson.objects.count()
    total_enrollments = CourseEnrollment.objects.count()
    total_accesses = CourseAccess.objects.filter(status='unlocked').count()
    total_certifications = Certification.objects.count()

    platform_base_domain = (get_platform_base_domain() or '').strip()
    raw_host = (request.get_host() or '').strip()
    host_only, host_port = (raw_host.rsplit(':', 1) + [''])[:2] if ':' in raw_host else (raw_host, '')
    is_local_host = host_only in {'localhost', '127.0.0.1'} or host_only.startswith('127.') or host_only.endswith('.local')
    recent_tenants = list(
        tenants.prefetch_related('domains').order_by('-created_at')[:8]
    )
    for tenant in recent_tenants:
        fallback_domain_obj = (
            tenant.domains.filter(is_primary=True).order_by('domain').first()
            or tenant.domains.filter(is_temporary=True).order_by('domain').first()
            or tenant.domains.order_by('domain').first()
        )
        if not fallback_domain_obj:
            # Backfill missing temporary domain records for older tenants.
            fallback_domain_obj = ensure_temporary_domain(tenant)

        fallback_domain = fallback_domain_obj.domain if fallback_domain_obj else ''
        inferred_platform_domain = f"{tenant.slug}.{platform_base_domain}" if platform_base_domain else ''
        inferred_local_domain = f"{tenant.slug}.lvh.me{':' + host_port if host_port else ''}" if is_local_host else ''
        tenant.display_domain = (
            tenant.custom_domain
            or fallback_domain
            or inferred_platform_domain
            or inferred_local_domain
            or '-'
        )
        if tenant.display_domain != '-':
            is_local_domain = (
                tenant.display_domain.startswith('localhost')
                or tenant.display_domain.startswith('127.')
                or tenant.display_domain.endswith('.local')
                or '.lvh.me' in tenant.display_domain
            )
            scheme = 'http' if is_local_domain else 'https'
            tenant.display_domain_url = f"{scheme}://{tenant.display_domain}/"
        else:
            tenant.display_domain_url = ''

    return render(request, 'superadmin/home.html', {
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'total_courses': total_courses,
        'total_lessons': total_lessons,
        'total_enrollments': total_enrollments,
        'total_accesses': total_accesses,
        'total_certifications': total_certifications,
        'recent_tenants': recent_tenants,
    })


@superadmin_required
def superadmin_tenants(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        slug = request.POST.get('slug', '').strip().lower()
        custom_domain = request.POST.get('custom_domain', '').strip().lower() or None
        primary_color = request.POST.get('primary_color', '#3B82F6').strip() or '#3B82F6'
        is_active = request.POST.get('is_active') == 'on'

        if not name or not slug:
            messages.error(request, 'Tenant name and slug are required.')
            return redirect('superadmin_tenants')

        if Tenant.objects.filter(slug=slug).exists():
            messages.error(request, f'Tenant slug "{slug}" already exists.')
            return redirect('superadmin_tenants')

        if custom_domain and Tenant.objects.filter(custom_domain=custom_domain).exists():
            messages.error(request, f'Custom domain "{custom_domain}" is already assigned.')
            return redirect('superadmin_tenants')

        tenant = Tenant.objects.create(
            name=name,
            slug=slug,
            custom_domain=custom_domain,
            primary_color=primary_color,
            is_active=is_active,
        )
        TenantConfig.objects.get_or_create(tenant=tenant)
        ensure_tenant_branding(tenant)
        ensure_temporary_domain(tenant)
        messages.success(request, f'Tenant "{tenant.name}" created successfully.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

    tenants = Tenant.objects.annotate(
        course_count=Count('courses', distinct=True),
        # Count via courses to include legacy lessons with null tenant FK.
        lesson_count=Count('courses__lessons', distinct=True),
        # Show only real student enrollments (exclude staff/superusers).
        enrollment_count=Count(
            'courses__enrollments',
            filter=Q(
                courses__enrollments__user__is_staff=False,
                courses__enrollments__user__is_superuser=False,
            ),
            distinct=True,
        ),
    ).order_by('name')

    return render(request, 'superadmin/tenants.html', {
        'tenants': tenants,
    })


@superadmin_required
def superadmin_tenant_detail(request, tenant_id):
    tenant = get_object_or_404(Tenant.objects.select_related('config'), id=tenant_id)
    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        slug = request.POST.get('slug', '').strip().lower()
        custom_domain = request.POST.get('custom_domain', '').strip().lower() or None
        primary_color = request.POST.get('primary_color', '#3B82F6').strip() or '#3B82F6'
        is_active = request.POST.get('is_active') == 'on'

        if not name or not slug:
            messages.error(request, 'Tenant name and slug are required.')
            return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

        slug_conflict = Tenant.objects.exclude(id=tenant.id).filter(slug=slug).exists()
        if slug_conflict:
            messages.error(request, f'Tenant slug "{slug}" already exists.')
            return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

        domain_conflict = custom_domain and Tenant.objects.exclude(id=tenant.id).filter(custom_domain=custom_domain).exists()
        if domain_conflict:
            messages.error(request, f'Custom domain "{custom_domain}" is already assigned.')
            return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

        tenant.name = name
        tenant.slug = slug
        tenant.custom_domain = custom_domain
        tenant.primary_color = primary_color
        tenant.is_active = is_active
        tenant.save()
        ensure_tenant_branding(tenant)
        ensure_temporary_domain(tenant)

        config.chatbot_webhook = request.POST.get('chatbot_webhook', config.chatbot_webhook).strip()
        config.vimeo_team_id = request.POST.get('vimeo_team_id', config.vimeo_team_id).strip()
        config.accredible_issuer_id = request.POST.get('accredible_issuer_id', config.accredible_issuer_id).strip()
        config.save()

        messages.success(request, 'Tenant settings updated.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

    stats = {
        'courses': Course.objects.filter(tenant=tenant).count(),
        'lessons': Lesson.objects.filter(
            Q(tenant=tenant) | Q(course__tenant=tenant)
        ).distinct().count(),
        'enrollments': CourseEnrollment.objects.filter(
            Q(tenant=tenant) | Q(course__tenant=tenant)
        ).filter(
            user__is_staff=False,
            user__is_superuser=False,
        ).distinct().count(),
        'active_accesses': CourseAccess.objects.filter(tenant=tenant, status='unlocked').count(),
        'certifications': Certification.objects.filter(tenant=tenant).count(),
        'bundles': Bundle.objects.filter(tenant=tenant).count(),
    }
    tenant_admins = TenantMembership.objects.filter(
        tenant=tenant,
        role='tenant_admin',
        is_active=True
    ).select_related('user').order_by('user__username')
    tenant_domains = TenantDomain.objects.filter(tenant=tenant).order_by('-is_primary', 'domain')

    return render(request, 'superadmin/tenant_detail.html', {
        'tenant': tenant,
        'config': config,
        'stats': stats,
        'tenant_admins': tenant_admins,
        'tenant_domains': tenant_domains,
    })


@superadmin_required
def superadmin_tenant_analytics(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)

    course_count = Course.objects.filter(tenant=tenant).count()
    lesson_count = Lesson.objects.filter(tenant=tenant).count()
    enrollment_count = CourseEnrollment.objects.filter(tenant=tenant).count()
    access_count = CourseAccess.objects.filter(tenant=tenant, status='unlocked').count()
    certification_count = Certification.objects.filter(tenant=tenant).count()
    completion_count = UserProgress.objects.filter(tenant=tenant, completed=True).count()

    top_courses = Course.objects.filter(tenant=tenant).annotate(
        enrollments=Count('enrollments', distinct=True),
        accesses=Count('accesses', filter=Q(accesses__status='unlocked'), distinct=True),
        lessons=Count('lessons', distinct=True),
    ).order_by('-enrollments', '-accesses', 'name')[:20]

    return render(request, 'superadmin/tenant_analytics.html', {
        'tenant': tenant,
        'course_count': course_count,
        'lesson_count': lesson_count,
        'enrollment_count': enrollment_count,
        'access_count': access_count,
        'certification_count': certification_count,
        'completion_count': completion_count,
        'top_courses': top_courses,
    })


@superadmin_required
def superadmin_analytics(request):
    cutoff_30d = timezone.now() - timedelta(days=30)

    tenants = Tenant.objects.annotate(
        courses=Count('courses', distinct=True),
        lessons=Count('lessons', distinct=True),
        enrollments=Count('course_enrollments', distinct=True),
        active_accesses=Count('course_accesses', filter=Q(course_accesses__status='unlocked'), distinct=True),
        certifications=Count('certifications', distinct=True),
    ).order_by('name')

    usage_rows = AIUsageLog.objects.filter(created_at__gte=cutoff_30d).values('tenant_id').annotate(
        ai_calls_30d=Count('id'),
        ai_tokens_30d=Sum('total_tokens'),
        ai_spend_30d=Sum('cost_usd'),
        ai_courses_30d=Count('course_id', distinct=True),
        ai_lessons_30d=Count('lesson_id', distinct=True),
    )
    usage_map = {row['tenant_id']: row for row in usage_rows}

    for tenant in tenants:
        row = usage_map.get(tenant.id, {})
        tenant.ai_calls_30d = row.get('ai_calls_30d') or 0
        tenant.ai_tokens_30d = row.get('ai_tokens_30d') or 0
        tenant.ai_spend_30d = row.get('ai_spend_30d') or 0
        tenant.ai_courses_30d = row.get('ai_courses_30d') or 0
        tenant.ai_lessons_30d = row.get('ai_lessons_30d') or 0
        tenant.ai_cost_per_course_30d = (
            tenant.ai_spend_30d / tenant.ai_courses_30d if tenant.ai_courses_30d else 0.0
        )

    ai_totals = AIUsageLog.objects.filter(created_at__gte=cutoff_30d).aggregate(
        ai_calls_30d=Count('id'),
        ai_tokens_30d=Sum('total_tokens'),
        ai_spend_30d=Sum('cost_usd'),
        ai_courses_30d=Count('course_id', distinct=True),
        ai_lessons_30d=Count('lesson_id', distinct=True),
    )
    total_ai_spend_30d = ai_totals.get('ai_spend_30d') or 0
    total_ai_courses_30d = ai_totals.get('ai_courses_30d') or 0
    total_ai_cost_per_course_30d = total_ai_spend_30d / total_ai_courses_30d if total_ai_courses_30d else 0

    return render(request, 'superadmin/analytics.html', {
        'tenants': tenants,
        'usage_window_days': 30,
        'totals': {
            'tenants': Tenant.objects.count(),
            'active_tenants': Tenant.objects.filter(is_active=True).count(),
            'courses': Course.objects.count(),
            'lessons': Lesson.objects.count(),
            'enrollments': CourseEnrollment.objects.count(),
            'active_accesses': CourseAccess.objects.filter(status='unlocked').count(),
            'certifications': Certification.objects.count(),
            'ai_calls_30d': ai_totals.get('ai_calls_30d') or 0,
            'ai_tokens_30d': ai_totals.get('ai_tokens_30d') or 0,
            'ai_courses_30d': total_ai_courses_30d,
            'ai_lessons_30d': ai_totals.get('ai_lessons_30d') or 0,
            'ai_spend_30d': total_ai_spend_30d,
            'ai_cost_per_course_30d': total_ai_cost_per_course_30d,
        }
    })


@superadmin_required
@require_http_methods(["POST"])
def superadmin_tenant_suspend(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    action = request.POST.get('action', '').strip().lower()
    if action == 'activate':
        tenant.is_active = True
        tenant.save(update_fields=['is_active'])
        messages.success(request, f'Tenant "{tenant.name}" is now active.')
    else:
        tenant.is_active = False
        tenant.save(update_fields=['is_active'])
        messages.success(request, f'Tenant "{tenant.name}" has been suspended.')
    next_url = (request.POST.get('next') or '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('superadmin_tenant_detail', tenant_id=tenant.id)


@superadmin_required
@require_http_methods(["POST"])
def superadmin_create_tenant_admin(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)

    username = (request.POST.get('username') or '').strip()
    email = (request.POST.get('email') or '').strip().lower()
    password = request.POST.get('password') or ''

    if not username or not password:
        messages.error(request, 'Username and password are required to create tenant admin.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

    user = User.objects.filter(username=username).first()
    if user is None:
        if email and User.objects.filter(email=email).exists():
            messages.error(request, f'Email "{email}" is already used by another account.')
            return redirect('superadmin_tenant_detail', tenant_id=tenant.id)
        user = User.objects.create_user(username=username, email=email, password=password)
    else:
        if password:
            user.set_password(password)

    user.is_staff = True
    user.save()

    membership, created = TenantMembership.objects.get_or_create(
        tenant=tenant,
        user=user,
        defaults={'role': 'tenant_admin', 'is_active': True}
    )
    if not created:
        membership.role = 'tenant_admin'
        membership.is_active = True
        membership.save(update_fields=['role', 'is_active', 'updated_at'])

    messages.success(request, f'User "{user.username}" now has tenant admin access for "{tenant.name}".')
    return redirect('superadmin_tenant_detail', tenant_id=tenant.id)


@superadmin_required
@require_http_methods(["POST"])
def superadmin_add_tenant_domain(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    domain = normalize_domain(request.POST.get('domain'))
    if not domain:
        messages.error(request, 'Please provide a valid domain.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)
    if TenantDomain.objects.filter(domain=domain).exists():
        messages.error(request, f'Domain "{domain}" is already connected.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

    TenantDomain.objects.create(
        tenant=tenant,
        domain=domain,
        is_temporary=False,
        is_primary=False,
        is_verified=False,
        verification_notes='Awaiting DNS verification',
    )
    messages.success(request, f'Domain "{domain}" added. Verify DNS and then click Verify.')
    return redirect('superadmin_tenant_detail', tenant_id=tenant.id)


@superadmin_required
@require_http_methods(["POST"])
def superadmin_verify_tenant_domain(request, tenant_id, domain_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    tenant_domain = get_object_or_404(TenantDomain, id=domain_id, tenant=tenant)
    tenant_domain.is_verified = True
    tenant_domain.verification_notes = 'Manually verified by super admin'
    tenant_domain.save(update_fields=['is_verified', 'verification_notes', 'updated_at'])
    messages.success(request, f'Domain "{tenant_domain.domain}" marked as verified.')
    return redirect('superadmin_tenant_detail', tenant_id=tenant.id)


@superadmin_required
@require_http_methods(["POST"])
def superadmin_set_primary_tenant_domain(request, tenant_id, domain_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    tenant_domain = get_object_or_404(TenantDomain, id=domain_id, tenant=tenant)
    if not tenant_domain.is_verified:
        messages.error(request, 'Domain must be verified before setting as primary.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)
    TenantDomain.objects.filter(tenant=tenant).update(is_primary=False)
    tenant_domain.is_primary = True
    tenant_domain.save(update_fields=['is_primary', 'updated_at'])
    if not tenant_domain.is_temporary:
        tenant.custom_domain = tenant_domain.domain
        tenant.save(update_fields=['custom_domain'])
    messages.success(request, f'"{tenant_domain.domain}" is now the primary domain.')
    return redirect('superadmin_tenant_detail', tenant_id=tenant.id)


@superadmin_required
@require_http_methods(["POST"])
def superadmin_set_tenant_stripe_keys(request, tenant_id):
    """Super admin: set or clear a tenant's own Stripe keys on their behalf."""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)

    if request.POST.get('clear_own_keys') == '1':
        config.stripe_own_secret_key = ''
        config.stripe_own_publishable_key = ''
        config.stripe_own_webhook_secret = ''
        config.save(update_fields=['stripe_own_secret_key', 'stripe_own_publishable_key', 'stripe_own_webhook_secret', 'updated_at'])
        messages.success(request, f'Stripe keys cleared for "{tenant.name}".')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

    secret_key = request.POST.get('stripe_own_secret_key', '').strip()
    pub_key = request.POST.get('stripe_own_publishable_key', '').strip()
    webhook_secret = request.POST.get('stripe_own_webhook_secret', '').strip()

    if not secret_key or not pub_key:
        messages.error(request, 'Secret Key and Publishable Key are required.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)
    if not secret_key.startswith('sk_'):
        messages.error(request, 'Secret Key must start with sk_live_ or sk_test_.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)
    if not pub_key.startswith('pk_'):
        messages.error(request, 'Publishable Key must start with pk_live_ or pk_test_.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)
    if webhook_secret and not webhook_secret.startswith('whsec_'):
        messages.error(request, 'Webhook Secret must start with whsec_.')
        return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

    config.stripe_own_secret_key = secret_key
    config.stripe_own_publishable_key = pub_key
    config.stripe_own_webhook_secret = webhook_secret
    config.save(update_fields=['stripe_own_secret_key', 'stripe_own_publishable_key', 'stripe_own_webhook_secret', 'updated_at'])
    messages.success(request, f'Stripe keys saved for "{tenant.name}". They can now accept payments.')
    return redirect('superadmin_tenant_detail', tenant_id=tenant.id)

