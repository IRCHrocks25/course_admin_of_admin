import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0056_coupon_target_signup'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MembershipPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_enabled', models.BooleanField(default=False)),
                ('name', models.CharField(default='All-Access Membership', max_length=200)),
                ('description', models.TextField(blank=True, help_text='Student-facing pitch for the membership')),
                ('monthly_price', models.DecimalField(blank=True, decimal_places=2, help_text='Monthly price in USD. Leave blank to disable monthly billing.', max_digits=8, null=True)),
                ('yearly_price', models.DecimalField(blank=True, decimal_places=2, help_text='Yearly price in USD. Leave blank to disable yearly billing.', max_digits=8, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='membership_plan', to='myApp.tenant')),
            ],
        ),
        migrations.CreateModel(
            name='StudentSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_subscription_id', models.CharField(blank=True, default='', max_length=120)),
                ('stripe_customer_id', models.CharField(blank=True, default='', max_length=120)),
                ('interval', models.CharField(choices=[('month', 'Monthly'), ('year', 'Yearly')], default='month', max_length=10)),
                ('status', models.CharField(choices=[('incomplete', 'Incomplete'), ('active', 'Active'), ('past_due', 'Past Due'), ('canceled', 'Canceled')], default='incomplete', max_length=20)),
                ('is_complimentary', models.BooleanField(default=False, help_text='Admin-granted free membership (no Stripe subscription).')),
                ('current_period_end', models.DateTimeField(blank=True, null=True)),
                ('canceled_at', models.DateTimeField(blank=True, null=True)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_subscriptions', to='myApp.tenant')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_subscriptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['tenant', 'user', 'status'], name='myApp_stude_tenant__92c5e1_idx'), models.Index(fields=['stripe_subscription_id'], name='myApp_stude_stripe__11c958_idx'), models.Index(fields=['stripe_customer_id'], name='myApp_stude_stripe__856b9d_idx')],
                'unique_together': {('tenant', 'user')},
            },
        ),
    ]
