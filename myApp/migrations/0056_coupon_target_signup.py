from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0055_coupon_tracking_signup'),
    ]

    operations = [
        migrations.AlterField(
            model_name='coupon',
            name='target_type',
            field=models.CharField(
                choices=[
                    ('signup', 'Tenant signup page'),
                    ('course', 'Course'),
                    ('bundle', 'Bundle'),
                    ('custom', 'Custom URL'),
                    ('site', 'Site home'),
                ],
                default='signup',
                max_length=20,
            ),
        ),
    ]
