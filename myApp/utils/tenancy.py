from ..models import Tenant


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

