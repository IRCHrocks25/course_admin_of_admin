# Adds a per-tenant display order to course categories so admins can reorder them.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0041_coursecategory'),
    ]

    operations = [
        migrations.AddField(
            model_name='coursecategory',
            name='display_order',
            field=models.PositiveIntegerField(db_index=True, default=0),
        ),
        migrations.AlterModelOptions(
            name='coursecategory',
            options={
                'ordering': ['display_order', 'name'],
                'verbose_name': 'Course category',
                'verbose_name_plural': 'Course categories',
            },
        ),
    ]
