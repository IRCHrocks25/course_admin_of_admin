from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0028_rename_myapp_aiusa_tenant__8ff736_idx_myapp_aiusa_tenant__dee2b5_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
    ]
