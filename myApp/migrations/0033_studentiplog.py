from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0032_class_length_to_dropdown'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentIPLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address', models.CharField(max_length=64)),
                ('country', models.CharField(blank=True, default='', max_length=120)),
                ('region', models.CharField(blank=True, default='', max_length=120)),
                ('city', models.CharField(blank=True, default='', max_length=120)),
                ('is_private_ip', models.BooleanField(default=False)),
                ('last_path', models.CharField(blank=True, default='', max_length=500)),
                ('hit_count', models.PositiveIntegerField(default=1)),
                ('first_seen', models.DateTimeField(auto_now_add=True)),
                ('last_seen', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_ip_logs', to='myApp.tenant')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_ip_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-last_seen'],
            },
        ),
        migrations.AddConstraint(
            model_name='studentiplog',
            constraint=models.UniqueConstraint(fields=('tenant', 'user', 'ip_address'), name='uniq_student_iplog_tenant_user_ip'),
        ),
        migrations.AddIndex(
            model_name='studentiplog',
            index=models.Index(fields=['tenant', 'last_seen'], name='myApp_stude_tenant__4a6412_idx'),
        ),
        migrations.AddIndex(
            model_name='studentiplog',
            index=models.Index(fields=['tenant', 'ip_address'], name='myApp_stude_tenant__2cdb38_idx'),
        ),
        migrations.AddIndex(
            model_name='studentiplog',
            index=models.Index(fields=['tenant', 'is_private_ip'], name='myApp_stude_tenant__f71547_idx'),
        ),
        migrations.AddIndex(
            model_name='studentiplog',
            index=models.Index(fields=['tenant', 'country'], name='myApp_stude_tenant__7cfd4f_idx'),
        ),
    ]
