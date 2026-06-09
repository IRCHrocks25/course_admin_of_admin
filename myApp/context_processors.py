from .utils.branding import get_tenant_branding
from .utils.domains import get_tenant_public_home_url
from .utils.tenancy import get_default_tenant
from .models import TenantMembership, Tenant, TenantNotificationDelivery


def ai_generation_context(request):
    """Add AI generating courses list for stacked floating widget"""
    if request.path.startswith('/dashboard/'):
        courses = request.session.get('ai_generating_courses', [])
        if not isinstance(courses, list):
            courses = []
        # Backwards compatibility: if old single-id format exists, convert
        old_id = request.session.get('ai_generating_course_id')
        if old_id and not courses:
            old_name = request.session.get('ai_generating_course_name', '')
            courses = [{'id': old_id, 'name': old_name}]
        return {'ai_generating_courses': courses}
    return {'ai_generating_courses': []}


def tenant_context(request):
    tenant = getattr(request, 'tenant', None)
    dashboard_available_tenants = []
    dashboard_impersonating = False
    dashboard_default_tenant_slug = ''
    is_superadmin = bool(getattr(request, 'user', None) and request.user.is_authenticated and request.user.is_superuser)
    clear_tenant_requested = (request.GET.get('clear_tenant') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    clear_tenant_requested = clear_tenant_requested or ((request.GET.get('tenant') or '').strip().lower() == 'clear')
    if not clear_tenant_requested and 'tenant' in request.GET and not request.GET.get('tenant', '').strip():
        clear_tenant_requested = True

    if is_superadmin and clear_tenant_requested:
        request.session.pop('superadmin_tenant_id', None)
        tenant = None

    if tenant is None and is_superadmin and not clear_tenant_requested:
        selected_id = request.session.get('superadmin_tenant_id')
        if selected_id:
            selected = Tenant.objects.filter(id=selected_id).first()
            if selected:
                tenant = selected
                dashboard_impersonating = True
            else:
                request.session.pop('superadmin_tenant_id', None)

    if tenant is None and getattr(request, 'user', None) and request.user.is_authenticated and not is_superadmin:
        membership = (
            TenantMembership.objects
            .filter(user=request.user, role='tenant_admin', is_active=True)
            .select_related('tenant')
            .first()
        )
        if membership is None:
            membership = (
                TenantMembership.objects
                .filter(user=request.user, is_active=True)
                .select_related('tenant')
                .first()
            )
        if membership:
            tenant = membership.tenant

    if is_superadmin:
        dashboard_available_tenants = list(
            Tenant.objects.order_by('name').only('id', 'name', 'slug', 'is_archived')
        )
        default_tenant = get_default_tenant()
        if default_tenant and default_tenant.is_active and not default_tenant.is_archived:
            dashboard_default_tenant_slug = default_tenant.slug

    pending_notification = None
    if tenant and getattr(request, 'user', None) and request.user.is_authenticated:
        pending_notification = (
            TenantNotificationDelivery.objects
            .filter(
                tenant=tenant,
                seen_at__isnull=True,
                notification__show_modal=True,
            )
            .select_related('notification', 'notification__cta_tier')
            .order_by('notification__created_at')
            .first()
        )

    tenant_branding = get_tenant_branding(tenant)
    effective_theme_mode = tenant_branding.get('theme_mode', 'dark')
    membership_theme = ''
    if tenant and getattr(request, 'user', None) and request.user.is_authenticated:
        membership = TenantMembership.objects.filter(
            tenant=tenant, user=request.user, is_active=True,
        ).only('theme_preference').first()
        if membership and membership.theme_preference:
            membership_theme = membership.theme_preference
    if membership_theme:
        effective_theme_mode = membership_theme
    elif request.session.get('theme_preference'):
        # Fallback for users without a tenant membership (e.g. superadmins),
        # whose toggle_theme preference is stored in the session.
        effective_theme_mode = request.session['theme_preference']

    return {
        'tenant': tenant,
        'tenant_branding': tenant_branding,
        'effective_theme_mode': effective_theme_mode,
        'tenant_site_url': get_tenant_public_home_url(request, tenant),
        'dashboard_available_tenants': dashboard_available_tenants,
        'dashboard_impersonating': dashboard_impersonating,
        'dashboard_default_tenant_slug': dashboard_default_tenant_slug,
        'pending_notification': pending_notification,
    }
