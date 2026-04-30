from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0030_tenantmembership_must_change_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='generation_settings',
            field=models.JSONField(blank=True, default=dict, help_text='LessonGenerationSettings dict captured at last AI generation'),
        ),
    ]
