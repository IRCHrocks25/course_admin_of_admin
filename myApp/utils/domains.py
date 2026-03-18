import os

from ..models import TenantDomain


def normalize_domain(value):
    value = (value or '').strip().lower()
    if value.startswith('http://'):
        value = value[7:]
    elif value.startswith('https://'):
        value = value[8:]
    return value.strip('/').strip()


def get_platform_base_domain():
    return (os.getenv('PLATFORM_BASE_DOMAIN') or '').strip().lower()


def build_temporary_domain(tenant_slug):
    base = get_platform_base_domain()
    if not base:
        return ''
    return f"{tenant_slug}.{base}"


def ensure_temporary_domain(tenant):
    domain = build_temporary_domain(tenant.slug)
    if not domain:
        return None
    td, _ = TenantDomain.objects.get_or_create(
        domain=domain,
        defaults={
            'tenant': tenant,
            'is_temporary': True,
            'is_primary': True,
            'is_verified': True,
            'verification_notes': 'System temporary domain',
        }
    )
    if td.tenant_id != tenant.id:
        return None
    # Keep temporary domain stable and verified.
    changed = False
    if not td.is_temporary:
        td.is_temporary = True
        changed = True
    if not td.is_verified:
        td.is_verified = True
        changed = True
    if not td.is_primary:
        td.is_primary = True
        changed = True
    if changed:
        td.save()
    return td


def get_tenant_public_home_url(request, tenant):
    """Return the best public landing URL for a tenant."""
    if tenant is None:
        return ''

    # Prefer verified primary domain, then verified temporary, then configured custom,
    # then generated temporary domain.
    primary = tenant.domains.filter(is_primary=True, is_verified=True).first()
    temporary = tenant.domains.filter(is_temporary=True, is_verified=True).first()
    domain = (
        (primary.domain if primary else '')
        or (temporary.domain if temporary else '')
        or (tenant.custom_domain or '').strip().lower()
        or build_temporary_domain(tenant.slug)
    )

    def _is_local(value):
        value = (value or '').lower()
        return value in {'localhost', '127.0.0.1'} or value.startswith('127.') or value.endswith('.local')

    def _split_host_port(raw_host):
        raw_host = (raw_host or '').strip()
        if ':' not in raw_host:
            return raw_host, ''
        host, port = raw_host.rsplit(':', 1)
        return host, port

    if domain:
        # Public/custom domains should default to HTTPS; local dev stays HTTP-friendly.
        forwarded = ''
        if request:
            forwarded = (request.META.get('HTTP_X_FORWARDED_PROTO') or '').split(',')[0].strip().lower()
        if _is_local(domain):
            if forwarded in {'http', 'https'}:
                scheme = forwarded
            else:
                scheme = request.scheme if request else 'http'
        else:
            scheme = 'https'
        return f'{scheme}://{domain}/'

    if request:
        host, port = _split_host_port(request.get_host())
        if _is_local(host):
            # Use lvh.me for reliable local subdomain routing to 127.0.0.1.
            tenant_host = f'{tenant.slug}.lvh.me'
            if port:
                tenant_host = f'{tenant_host}:{port}'
            return f'{request.scheme}://{tenant_host}/'
        return f'{request.scheme}://{request.get_host()}/?tenant={tenant.slug}'
    return ''

