from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0058_course_grants_membership_months_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='studentsubscription',
            name='status',
            field=models.CharField(
                choices=[
                    ('incomplete', 'Incomplete'),
                    ('active', 'Active'),
                    ('past_due', 'Past Due'),
                    ('canceled', 'Canceled'),
                    ('expired', 'Expired'),
                ],
                default='incomplete',
                max_length=20,
            ),
        ),
    ]
