# Generated manually for Lesson.ai_generation_status partial choice

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0064_tenantconfig_registration_webhook'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lesson',
            name='ai_generation_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('partial', 'Partial'),
                    ('generated', 'Generated'),
                    ('approved', 'Approved'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
