from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('myApp', '0066_lesson_video_script_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gdrive_refresh_token_encrypted', models.TextField(blank=True, default='', help_text='Encrypted Google Drive OAuth refresh token')),
                ('gdrive_scripts_root_id', models.CharField(blank=True, default='', help_text='Drive folder ID for SOP Course Video Scripts/', max_length=200)),
                ('gdrive_connected_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('gdrive_connected_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Platform Config',
                'verbose_name_plural': 'Platform Config',
            },
        ),
    ]
