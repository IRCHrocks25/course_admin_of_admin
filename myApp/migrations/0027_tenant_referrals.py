from django.db import migrations, models
import django.db.models.deletion
from django.utils.crypto import get_random_string
import re


def _seed_from_tenant(tenant):
    source = (tenant.slug or tenant.name or 'tenant').upper()
    seed = re.sub(r'[^A-Z0-9]', '', source)[:6]
    return seed or 'TENANT'


def _generate_unique_code(TenantModel, tenant, seen_codes):
    charset = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    seed = _seed_from_tenant(tenant)
    for _ in range(20):
        candidate = f"{seed}-{get_random_string(6, allowed_chars=charset)}"
        if candidate in seen_codes:
            continue
        if not TenantModel.objects.filter(referral_code=candidate).exclude(id=tenant.id).exists():
            seen_codes.add(candidate)
            return candidate
    fallback = f"TENANT-{get_random_string(8, allowed_chars=charset)}"
    seen_codes.add(fallback)
    return fallback


def backfill_referral_codes(apps, schema_editor):
    Tenant = apps.get_model('myApp', 'Tenant')
    seen_codes = set(Tenant.objects.exclude(referral_code='').values_list('referral_code', flat=True))
    for tenant in Tenant.objects.all().order_by('id'):
        if tenant.referral_code:
            continue
        tenant.referral_code = _generate_unique_code(Tenant, tenant, seen_codes)
        tenant.save(update_fields=['referral_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0026_course_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='referral_code',
            field=models.CharField(blank=True, default='', max_length=24),
        ),
        migrations.AddField(
            model_name='tenant',
            name='referred_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='referred_tenants', to='myApp.tenant'),
        ),
        migrations.AddField(
            model_name='tenant',
            name='referral_recorded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_referral_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='tenant',
            name='referral_code',
            field=models.CharField(blank=True, default='', max_length=24, unique=True),
        ),
    ]
