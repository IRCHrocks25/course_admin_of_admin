from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0063_pendingregistration'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantconfig',
            name='registration_webhook',
            field=models.URLField(
                blank=True,
                help_text='Katalyst CRM webhook URL. POSTed when a student self-registers. Leave blank to disable.',
            ),
        ),
    ]
