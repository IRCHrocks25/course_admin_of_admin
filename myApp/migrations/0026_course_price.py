from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0025_tenantconfig_own_stripe_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Leave blank or 0 for free. Set a price to require purchase.',
                max_digits=8,
                null=True,
            ),
        ),
    ]
