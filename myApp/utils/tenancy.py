from ..models import Tenant


_CLEAR_TRUTHY = {'1', 'true', 'yes', 'on'}


def is_clear_tenant_requested(request):
    """
    Return True when the request is asking a superadmin's impersonation to be
    cleared (back to the Global Superadmin View).

    Recognises every signal the UI can emit so the view, the context processor
    and the AJAX resolver all agree:

        * ``?clear_tenant=1`` (truthy values)
        * ``?tenant=clear``
        * ``?tenant=`` present but blank (e.g. the "Global Superadmin View"
          option in the switcher)
    """
    get = getattr(request, 'GET', None)
    if get is None:
        return False
    if (get.get('clear_tenant') or '').strip().lower() in _CLEAR_TRUTHY:
        return True
    if 'tenant' in get:
        value = (get.get('tenant') or '').strip().lower()
        if value in ('', 'clear'):
            return True
    return False


def resolve_request_tenant(request):
    """
    Resolve the tenant for a request, mirroring the fallback chain used by the
    ``tenant_context`` context processor.

    The ``TenantMiddleware`` only sets ``request.tenant`` from the host, so on
    platform hosts (localhost/127.0.0.1) it stays None unless ``?tenant=<slug>``
    is supplied. AJAX endpoints that POST without that query param therefore see
    no tenant even though the page that triggered them rendered one. This helper
    reproduces the display-side resolution so views agree with the template:

        1. host-resolved tenant (``request.tenant``)
        2. superadmin session impersonation (``superadmin_tenant_id``)
        3. the user's active membership (preferring ``tenant_admin``)
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is not None:
        return tenant

    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return None

    if user.is_superuser:
        # A clear request must win over a stale session, otherwise AJAX views
        # keep operating on the old tenant after the chrome shows "Global".
        if is_clear_tenant_requested(request):
            request.session.pop('superadmin_tenant_id', None)
            return None
        selected_id = request.session.get('superadmin_tenant_id')
        if selected_id:
            return Tenant.objects.filter(id=selected_id).first()
        return None

    from ..models import TenantMembership
    membership = (
        TenantMembership.objects
        .filter(user=user, role='tenant_admin', is_active=True)
        .select_related('tenant')
        .first()
    )
    if membership is None:
        membership = (
            TenantMembership.objects
            .filter(user=user, is_active=True)
            .select_related('tenant')
            .first()
        )
    return membership.tenant if membership else None


def get_default_tenant():
    """
    Transitional helper for Phase 1 migrations.
    Until request-based tenant resolution is implemented, this keeps new rows tenant-linked.
    """
    tenant, _ = Tenant.objects.get_or_create(
        slug='default',
        defaults={
            'name': 'Default Tenant',
            'primary_color': '#3B82F6',
            'is_active': True,
        }
    )
    return tenant

