from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0033_studentiplog'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='category',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='course',
            name='display_order',
            field=models.PositiveIntegerField(default=0, help_text='Lower numbers appear first in course listings.'),
        ),
    ]
