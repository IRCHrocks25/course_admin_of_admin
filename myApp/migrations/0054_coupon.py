from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0053_lesson_show_student_sections'),
    ]

    operations = [
        migrations.CreateModel(
            name='Coupon',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('code', models.CharField(help_text='Public coupon code used in the shareable link', max_length=50)),
                ('description', models.TextField(blank=True)),
                ('discount_type', models.CharField(choices=[('percent', 'Percent off'), ('fixed', 'Fixed amount off')], default='percent', max_length=20)),
                ('discount_value', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('target_type', models.CharField(choices=[('course', 'Course'), ('bundle', 'Bundle'), ('custom', 'Custom URL'), ('site', 'Site home')], default='site', max_length=20)),
                ('custom_url', models.URLField(blank=True, max_length=500)),
                ('qr_code_url', models.URLField(blank=True, help_text='Iceberg CDN URL for the coupon QR image', max_length=500)),
                ('is_active', models.BooleanField(default=True)),
                ('max_uses', models.PositiveIntegerField(blank=True, help_text='Leave blank for unlimited uses', null=True)),
                ('uses_count', models.PositiveIntegerField(default=0)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('bundle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='coupons', to='myApp.bundle')),
                ('course', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='coupons', to='myApp.course')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='coupons', to='myApp.tenant')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='coupon',
            constraint=models.UniqueConstraint(fields=('tenant', 'code'), name='uniq_coupon_tenant_code'),
        ),
    ]
