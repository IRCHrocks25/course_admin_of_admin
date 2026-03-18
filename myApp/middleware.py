import os

from .models import Tenant, TenantDomain


class TenantMiddleware:
    """
    Resolve tenant from host for domain/subdomain-based multi-tenant behavior.
    Platform hosts intentionally resolve to no tenant.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        tenant = None
        platform_hosts = {
            h.strip().lower()
            for h in os.getenv('PLATFORM_HOSTS', 'localhost,127.0.0.1').split(',')
            if h.strip()
        }

        if host in platform_hosts:
            # Dev override: allow local tenant preview with ?tenant=<slug>
            tenant_slug = (request.GET.get('tenant') or '').strip().lower()
            if tenant_slug:
                tenant = Tenant.objects.filter(slug=tenant_slug, is_active=True).first()
        else:
            tenant_domain = TenantDomain.objects.filter(
                domain=host,
                is_verified=True,
                tenant__is_active=True
            ).select_related('tenant').first()
            if tenant_domain:
                tenant = tenant_domain.tenant

            if tenant is None:
                tenant = Tenant.objects.filter(custom_domain=host, is_active=True).first()
            if tenant is None and '.' in host:
                maybe_slug = host.split('.')[0]
                tenant = Tenant.objects.filter(slug=maybe_slug, is_active=True).first()

        request.tenant = tenant
        return self.get_response(request)

