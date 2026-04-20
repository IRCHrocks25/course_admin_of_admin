from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0024_course_creation_blueprint'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantconfig',
            name='stripe_own_secret_key',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='tenantconfig',
            name='stripe_own_publishable_key',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='tenantconfig',
            name='stripe_own_webhook_secret',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
