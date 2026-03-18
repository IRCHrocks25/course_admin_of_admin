import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_tenant_memberships(apps, schema_editor):
    Tenant = apps.get_model('myApp', 'Tenant')
    TenantMembership = apps.get_model('myApp', 'TenantMembership')
    User = apps.get_model('auth', 'User')

    default_tenant = Tenant.objects.filter(slug='default').first()
    if not default_tenant:
        return

    for user in User.objects.all().iterator():
        role = 'tenant_admin' if (user.is_staff or user.is_superuser) else 'student'
        TenantMembership.objects.get_or_create(
            tenant=default_tenant,
            user=user,
            defaults={
                'role': role,
                'is_active': True,
            }
        )


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0019_tenant_scoped_uniqueness_updates'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('tenant_admin', 'Tenant Admin'), ('student', 'Student')], default='student', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='myApp.tenant')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tenant_memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['tenant__name', 'user__username'],
                'indexes': [models.Index(fields=['tenant', 'role', 'is_active'], name='myApp_tenan_tenant__2ce5ff_idx'), models.Index(fields=['user', 'is_active'], name='myApp_tenan_user_id_3be96a_idx')],
                'unique_together': {('tenant', 'user')},
            },
        ),
        migrations.RunPython(backfill_tenant_memberships, migrations.RunPython.noop),
    ]

