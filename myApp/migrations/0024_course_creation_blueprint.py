from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0023_stripe_billing_connect'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='creation_blueprint',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
