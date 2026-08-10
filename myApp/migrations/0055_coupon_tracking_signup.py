from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0054_coupon'),
    ]

    operations = [
        migrations.AlterField(
            model_name='coupon',
            name='discount_type',
            field=models.CharField(
                choices=[
                    ('none', 'No discount (tracking only)'),
                    ('percent', 'Percent off'),
                    ('fixed', 'Fixed amount off'),
                ],
                default='percent',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='tenantmembership',
            name='signup_coupon',
            field=models.ForeignKey(
                blank=True,
                help_text='Coupon used when this student created their account',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='signup_memberships',
                to='myApp.coupon',
            ),
        ),
    ]
