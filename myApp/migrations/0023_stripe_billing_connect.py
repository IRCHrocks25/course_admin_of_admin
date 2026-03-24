from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myApp", "0022_aiusagelog"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="billing_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("active", "Active"),
                    ("past_due", "Past Due"),
                    ("canceled", "Canceled"),
                ],
                default="active",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="plan_code",
            field=models.CharField(blank=True, default="starter", max_length=50),
        ),
        migrations.AddField(
            model_name="tenant",
            name="stripe_customer_id",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="tenant",
            name="stripe_subscription_id",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="stripe_connect_account_id",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="stripe_connect_charges_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="stripe_connect_onboarding_complete",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="StripeEventLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.CharField(max_length=120, unique=True)),
                ("event_type", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
