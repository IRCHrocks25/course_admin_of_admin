from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0059_studentsubscription_status_expired'),
    ]

    operations = [
        migrations.AddField(
            model_name='membershipplan',
            name='past_due_grace_days',
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    'Days a member keeps access after a failed renewal (status past_due) '
                    'while Stripe retries payment. 0 = revoke access immediately. A few '
                    'days avoids locking out members over a transient card decline.'
                ),
            ),
        ),
    ]
