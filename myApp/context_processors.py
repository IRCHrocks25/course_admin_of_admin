from .utils.branding import get_tenant_branding
from .utils.domains import get_tenant_public_home_url
from .models import TenantMembership


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
    if tenant is None and getattr(request, 'user', None) and request.user.is_authenticated:
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

    return {
        'tenant': tenant,
        'tenant_branding': get_tenant_branding(tenant),
        'tenant_site_url': get_tenant_public_home_url(request, tenant),
    }
