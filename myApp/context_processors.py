from .utils.branding import get_tenant_branding
from .utils.domains import get_tenant_public_home_url
from .models import TenantMembership, Tenant


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
    is_superadmin = bool(getattr(request, 'user', None) and request.user.is_authenticated and request.user.is_superuser)

    if tenant is None and is_superadmin:
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

    return {
        'tenant': tenant,
        'tenant_branding': get_tenant_branding(tenant),
        'tenant_site_url': get_tenant_public_home_url(request, tenant),
        'dashboard_available_tenants': dashboard_available_tenants,
        'dashboard_impersonating': dashboard_impersonating,
    }
