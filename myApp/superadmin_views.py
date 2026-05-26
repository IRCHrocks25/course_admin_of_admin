import json
import os
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_http_methods

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from .models import (
    Bundle,
    Certification,
    Course,
    CourseAccess,
    CourseEnrollment,
    Lesson,
    AIUsageLog,
    PricingTier,
    Tenant,
    TenantConfig,
    TenantDomain,
    TenantMembership,
    TenantNotification,
    TenantNotificationDelivery,
    UserProgress,
)
from .utils.domains import ensure_temporary_domain, normalize_domain, get_platform_base_domain
from .utils.branding import ensure_tenant_branding


def superadmin_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_superuser, login_url='login')(view_func)


@superadmin_required
def superadmin_home(request):
    tenants = Tenant.objects.filter(is_archived=False).order_by('name')
    total_tenants = tenants.count()
    active_tenants = tenants.filter(is_active=True).count()

    # Keep metrics tenant-scoped and student-centric so cards reflect
    # real learner activity, not platform/admin seed records.
    total_courses = Course.objects.filter(tenant__in=tenants).count()
    total_lessons = Lesson.objects.filter(
        Q(tenant__in=tenants) | Q(course__tenant__in=tenants)
    ).distinct().count()
    total_enrollments = CourseEnrollment.objects.filter(
        Q(tenant__in=tenants) | Q(course__tenant__in=tenants),
        user__is_staff=False,
        user__is_superuser=False,
    ).distinct().count()
    total_accesses = CourseAccess.objects.filter(
        tenant__in=tenants,
        status='unlocked',
        user__is_staff=False,
        user__is_superuser=False,
    ).count()
    total_certifications = Certification.objects.filter(
        tenant__in=tenants,
        user__is_staff=False,
        user__is_superuser=False,
    ).count()

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

    unpaid_setup_fees = tenants.filter(setup_fee_paid=False).count()

    return render(request, 'superadmin/home.html', {
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'unpaid_setup_fees': unpaid_setup_fees,
        'total_courses': total_courses,
        'total_lessons': total_lessons,
        'total_enrollments': total_enrollments,
        'total_accesses': total_accesses,
        'total_certifications': total_certifications,
        'recent_tenants': recent_tenants,
    })


@superadmin_required
def superadmin_tenants(request):
    include_archived = request.GET.get('include_archived', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if request.method == 'POST':
        # Bulk archive/unarchive from tenants list.
        bulk_action = (request.POST.get('bulk_action') or '').strip().lower()
        if bulk_action:
            selected_ids = []
            for raw_id in request.POST.getlist('tenant_ids'):
                try:
                    selected_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    continue

            if not selected_ids:
                messages.error(request, 'Select at least one tenant.')
                return redirect('superadmin_tenants')

            tenants_qs = Tenant.objects.filter(id__in=selected_ids)
            if not tenants_qs.exists():
                messages.error(request, 'No matching tenants found.')
                return redirect('superadmin_tenants')

            if bulk_action == 'unarchive':
                updated = tenants_qs.update(is_archived=False)
                messages.success(request, f'Restored {updated} tenant(s).')
            else:
                updated = tenants_qs.update(is_archived=True, is_active=False)
                messages.success(request, f'Archived {updated} tenant(s).')

            next_url = (request.POST.get('next') or '').strip()
            if next_url and url_has_allowed_host_and_scheme(
                url=next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('superadmin_tenants')

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

    tenants_qs = Tenant.objects.all()
    if not include_archived:
        tenants_qs = tenants_qs.filter(is_archived=False)

    tenants = tenants_qs.annotate(
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
        'include_archived': include_archived,
        'archived_count': Tenant.objects.filter(is_archived=True).count(),
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
def superadmin_tenant_archive(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    action = request.POST.get('action', '').strip().lower()

    if action == 'unarchive':
        tenant.is_archived = False
        tenant.save(update_fields=['is_archived', 'updated_at'])
        messages.success(request, f'Tenant "{tenant.name}" has been restored.')
    else:
        # Archive acts like soft-delete: hide from default superadmin lists and
        # disable portal activity without removing any data.
        tenant.is_archived = True
        tenant.is_active = False
        tenant.save(update_fields=['is_archived', 'is_active', 'updated_at'])
        messages.success(request, f'Tenant "{tenant.name}" has been archived.')

    next_url = (request.POST.get('next') or '').strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('superadmin_tenants')


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
        defaults={'role': 'tenant_admin', 'is_active': True, 'must_change_password': True}
    )
    if not created:
        membership.role = 'tenant_admin'
        membership.is_active = True
        membership.must_change_password = True
        membership.save(update_fields=['role', 'is_active', 'must_change_password', 'updated_at'])

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


# ========== PRICING MANAGEMENT ==========

@superadmin_required
def superadmin_pricing(request):
    tiers = PricingTier.objects.all()
    return render(request, 'superadmin/pricing.html', {'tiers': tiers})


@superadmin_required
def superadmin_pricing_add(request):
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip().lower()
        name = (request.POST.get('name') or '').strip()
        if not code or not name:
            messages.error(request, 'Code and name are required.')
            return redirect('superadmin_pricing')
        if PricingTier.objects.filter(code=code).exists():
            messages.error(request, f'Tier code "{code}" already exists.')
            return redirect('superadmin_pricing')
        try:
            PricingTier.objects.create(
                code=code,
                name=name,
                description=(request.POST.get('description') or '').strip(),
                setup_fee_cents=int(request.POST.get('setup_fee_cents') or 0),
                monthly_cents=int(request.POST.get('monthly_cents') or 0),
                yearly_cents=int(request.POST.get('yearly_cents') or 0),
                sort_order=int(request.POST.get('sort_order') or 0),
                charge_setup_fee=request.POST.get('charge_setup_fee') == 'on',
                is_active=request.POST.get('is_active') == 'on',
            )
            messages.success(request, f'Tier "{name}" created.')
        except (ValueError, TypeError):
            messages.error(request, 'Invalid numeric value.')
        return redirect('superadmin_pricing')
    return render(request, 'superadmin/pricing_form.html', {'tier': None})


@superadmin_required
def superadmin_pricing_edit(request, tier_id):
    tier = get_object_or_404(PricingTier, id=tier_id)
    if request.method == 'POST':
        tier.name = (request.POST.get('name') or tier.name).strip()
        tier.description = (request.POST.get('description') or '').strip()
        try:
            tier.setup_fee_cents = int(request.POST.get('setup_fee_cents') or tier.setup_fee_cents)
            tier.monthly_cents = int(request.POST.get('monthly_cents') or tier.monthly_cents)
            tier.yearly_cents = int(request.POST.get('yearly_cents') or tier.yearly_cents)
            tier.sort_order = int(request.POST.get('sort_order') or tier.sort_order)
        except (ValueError, TypeError):
            messages.error(request, 'Invalid numeric value.')
            return redirect('superadmin_pricing_edit', tier_id=tier.id)
        tier.charge_setup_fee = request.POST.get('charge_setup_fee') == 'on'
        tier.is_active = request.POST.get('is_active') == 'on'
        tier.save()
        messages.success(request, f'Tier "{tier.name}" updated.')
        return redirect('superadmin_pricing')
    return render(request, 'superadmin/pricing_form.html', {'tier': tier})


@superadmin_required
@require_http_methods(["POST"])
def superadmin_pricing_sync(request, tier_id=None):
    """Sync one tier (if tier_id given) or all unsynchronised tiers to Stripe."""
    import os
    try:
        import stripe
    except ImportError:
        messages.error(request, 'Stripe library not installed.')
        return redirect('superadmin_pricing')

    secret_key = os.getenv('STRIPE_SECRET_KEY', '')
    if not secret_key:
        messages.error(request, 'STRIPE_SECRET_KEY is not configured.')
        return redirect('superadmin_pricing')
    stripe.api_key = secret_key

    if tier_id:
        tiers = PricingTier.objects.filter(id=tier_id)
    else:
        tiers = PricingTier.objects.filter(is_active=True)

    synced, errors = 0, 0
    for tier in tiers:
        try:
            _sync_tier_to_stripe(stripe, tier)
            synced += 1
        except Exception as e:
            messages.error(request, f'Error syncing "{tier.name}": {e}')
            errors += 1

    if synced:
        messages.success(request, f'Synced {synced} tier(s) to Stripe.')
    if not synced and not errors:
        messages.info(request, 'No tiers to sync.')
    return redirect('superadmin_pricing')


def _sync_tier_to_stripe(stripe, tier):
    if tier.stripe_product_id:
        stripe.Product.modify(tier.stripe_product_id, name=tier.name, description=tier.description or None)
        product_id = tier.stripe_product_id
    else:
        product = stripe.Product.create(
            name=tier.name,
            description=tier.description or None,
            metadata={'pricing_tier_code': tier.code},
        )
        product_id = product.id

    old_setup = tier.stripe_price_setup_id
    old_monthly = tier.stripe_price_monthly_id
    old_yearly = tier.stripe_price_yearly_id

    new_setup = stripe.Price.create(
        product=product_id,
        unit_amount=tier.setup_fee_cents,
        currency='usd',
        metadata={'tier': tier.code, 'type': 'setup'},
    )
    new_monthly = stripe.Price.create(
        product=product_id,
        unit_amount=tier.monthly_cents,
        currency='usd',
        recurring={'interval': 'month'},
        metadata={'tier': tier.code, 'type': 'monthly'},
    )
    new_yearly = stripe.Price.create(
        product=product_id,
        unit_amount=tier.yearly_cents,
        currency='usd',
        recurring={'interval': 'year'},
        metadata={'tier': tier.code, 'type': 'yearly'},
    )

    for old_id in [old_setup, old_monthly, old_yearly]:
        if old_id:
            try:
                stripe.Price.modify(old_id, active=False)
            except Exception:
                pass

    tier.stripe_product_id = product_id
    tier.stripe_price_setup_id = new_setup.id
    tier.stripe_price_monthly_id = new_monthly.id
    tier.stripe_price_yearly_id = new_yearly.id
    tier.stripe_synced_at = timezone.now()
    tier.save()


# ========== TENANT NOTIFICATIONS ==========

@superadmin_required
def superadmin_notifications(request):
    notifications = TenantNotification.objects.annotate(
        total_deliveries=Count('deliveries'),
        emails_sent=Count('deliveries', filter=Q(deliveries__email_sent_at__isnull=False)),
        modals_seen=Count('deliveries', filter=Q(deliveries__seen_at__isnull=False)),
        ctas_clicked=Count('deliveries', filter=Q(deliveries__clicked_at__isnull=False)),
    )
    return render(request, 'superadmin/notifications.html', {'notifications': notifications})


@superadmin_required
def superadmin_notification_create(request):
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        body = (request.POST.get('body') or '').strip()
        if not title or not body:
            messages.error(request, 'Title and body are required.')
            return redirect('superadmin_notification_create')

        cta_type = request.POST.get('cta_type', 'none')
        cta_label = (request.POST.get('cta_label') or '').strip()
        cta_custom_url = (request.POST.get('cta_custom_url') or '').strip()

        cta_tier_id = None
        if cta_type == 'upgrade':
            cta_tier_id = request.POST.get('cta_tier') or None
        elif cta_type == 'setup_fee':
            cta_tier_id = request.POST.get('cta_setup_fee_tier') or None

        notification = TenantNotification.objects.create(
            title=title,
            body=body,
            cta_type=cta_type,
            cta_label=cta_label,
            cta_tier_id=cta_tier_id,
            cta_billing_interval='',
            cta_custom_url=cta_custom_url if cta_type == 'url' else '',
            send_email=request.POST.get('send_email') == 'on',
            show_modal=request.POST.get('show_modal') == 'on',
            created_by=request.user,
        )

        recipient_mode = request.POST.get('recipient_mode', 'all')
        if recipient_mode == 'single':
            tenant_id = request.POST.get('single_tenant')
            if tenant_id:
                tenant_ids = [int(tenant_id)]
            else:
                tenant_ids = []
        elif recipient_mode == 'multi':
            tenant_ids = []
            for raw_id in request.POST.getlist('tenant_ids'):
                try:
                    tenant_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
        elif recipient_mode == 'plan':
            plan_code = (request.POST.get('filter_plan') or '').strip()
            tenant_ids = list(
                Tenant.objects.filter(is_archived=False, plan_code=plan_code).values_list('id', flat=True)
            )
        elif recipient_mode == 'unpaid_setup':
            tenant_ids = list(
                Tenant.objects.filter(is_archived=False, setup_fee_paid=False).values_list('id', flat=True)
            )
        else:
            tenant_ids = list(
                Tenant.objects.filter(is_archived=False).values_list('id', flat=True)
            )

        if not tenant_ids:
            messages.warning(request, 'No tenants matched — notification created with no recipients.')
            return redirect('superadmin_notifications')

        deliveries = [
            TenantNotificationDelivery(notification=notification, tenant_id=tid)
            for tid in tenant_ids
        ]
        TenantNotificationDelivery.objects.bulk_create(deliveries, ignore_conflicts=True)

        if notification.send_email:
            from .tasks import send_notification_emails
            send_notification_emails.enqueue(notification.id)

        messages.success(
            request,
            f'Notification "{title}" sent to {len(tenant_ids)} tenant(s).'
            + (' Emails queued.' if notification.send_email else ''),
        )
        return redirect('superadmin_notifications')

    tenants = Tenant.objects.filter(is_archived=False).order_by('name')
    tiers = PricingTier.objects.filter(is_active=True)
    plan_codes = list(
        Tenant.objects.filter(is_archived=False)
        .values_list('plan_code', flat=True)
        .distinct()
        .order_by('plan_code')
    )
    return render(request, 'superadmin/notification_form.html', {
        'tenants': tenants,
        'tiers': tiers,
        'plan_codes': plan_codes,
    })


@superadmin_required
def superadmin_notification_preview(request, notification_id):
    notification = get_object_or_404(TenantNotification, id=notification_id)
    return render(request, 'superadmin/notification_preview.html', {
        'notification': notification,
    })


@superadmin_required
@require_http_methods(["POST"])
def superadmin_notification_reshow(request, notification_id):
    notification = get_object_or_404(TenantNotification, id=notification_id)
    reset_count = notification.deliveries.filter(seen_at__isnull=False).update(
        seen_at=None, clicked_at=None,
    )
    if reset_count:
        messages.success(request, f'Modal re-queued for {reset_count} tenant(s) who already dismissed it.')
    else:
        messages.info(request, 'No tenants had dismissed this notification yet.')
    return redirect('superadmin_notifications')


@superadmin_required
@require_http_methods(["POST"])
def superadmin_notification_ai_improve(request):
    if not OPENAI_AVAILABLE:
        return JsonResponse({'success': False, 'error': 'OpenAI package is not installed.'}, status=500)
    api_key = os.getenv('OPENAI_API_KEY', '')
    if not api_key:
        return JsonResponse({'success': False, 'error': 'OPENAI_API_KEY is not configured.'}, status=500)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not title and not body:
        return JsonResponse({'success': False, 'error': 'Provide a title or body to improve.'}, status=400)

    prompt = (
        "You are writing a short notification for SaaS platform tenants (course academy owners).\n"
        "Rewrite the title and body to be clear, compelling, and professional.\n"
        "Keep the tone friendly and action-oriented. Be concise — this appears in a modal popup and email.\n"
        "Output the body as clean HTML (use <p>, <strong>, <ul>/<li> only). No markdown.\n"
        "Return JSON with exactly two keys: \"title\" and \"body\".\n\n"
        f"Current title: {title}\n"
        f"Current body: {body}"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert SaaS copywriter. Always return valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=800,
        )
        raw = (response.choices[0].message.content or '').strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
        result = json.loads(raw)
        return JsonResponse({
            'success': True,
            'title': (result.get('title') or title).strip(),
            'body': (result.get('body') or body).strip(),
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'AI returned invalid format. Try again.'}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)[:200]}, status=500)

