import os

import django.db.models.deletion
from django.db import migrations, models


def backfill_domains(apps, schema_editor):
    Tenant = apps.get_model('myApp', 'Tenant')
    TenantDomain = apps.get_model('myApp', 'TenantDomain')

    base_domain = (os.getenv('PLATFORM_BASE_DOMAIN') or '').strip().lower()

    for tenant in Tenant.objects.all().iterator():
        created_any = False

        if tenant.custom_domain:
            domain = tenant.custom_domain.strip().lower()
            obj, _ = TenantDomain.objects.get_or_create(
                domain=domain,
                defaults={
                    'tenant': tenant,
                    'is_temporary': False,
                    'is_primary': True,
                    'is_verified': True,
                    'verification_notes': 'Backfilled from tenant.custom_domain',
                }
            )
            if obj.tenant_id == tenant.id:
                created_any = True

        if base_domain:
            temp_domain = f"{tenant.slug}.{base_domain}"
            obj, _ = TenantDomain.objects.get_or_create(
                domain=temp_domain,
                defaults={
                    'tenant': tenant,
                    'is_temporary': True,
                    'is_primary': not created_any,
                    'is_verified': True,
                    'verification_notes': 'System temporary domain',
                }
            )
            if obj.tenant_id == tenant.id and not created_any:
                created_any = True

        if created_any:
            # Ensure only one primary domain per tenant after backfill.
            primary = TenantDomain.objects.filter(tenant=tenant, is_primary=True).order_by('is_temporary', 'id').first()
            if primary:
                TenantDomain.objects.filter(tenant=tenant).exclude(id=primary.id).update(is_primary=False)


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0020_tenantmembership'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantDomain',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(max_length=255, unique=True)),
                ('is_temporary', models.BooleanField(default=False, help_text='System-provided temporary subdomain')),
                ('is_primary', models.BooleanField(default=False, help_text='Primary public domain for this tenant')),
                ('is_verified', models.BooleanField(default=False, help_text='Whether DNS/ownership is verified')),
                ('verification_notes', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='domains', to='myApp.tenant')),
            ],
            options={
                'ordering': ['-is_primary', 'domain'],
                'indexes': [models.Index(fields=['tenant', 'is_primary', 'is_verified'], name='myApp_tenan_tenant__ff596f_idx')],
                'unique_together': {('tenant', 'domain')},
            },
        ),
        migrations.RunPython(backfill_domains, migrations.RunPython.noop),
    ]

