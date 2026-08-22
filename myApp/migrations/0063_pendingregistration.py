from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0062_membershipplan_comp_grant_reset_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='PendingRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(max_length=150)),
                ('email', models.EmailField(blank=True, default='', max_length=254)),
                ('password', models.CharField(help_text='Already hashed (make_password).', max_length=256)),
                ('interval', models.CharField(default='month', max_length=10)),
                ('stripe_checkout_session_id', models.CharField(blank=True, db_index=True, default='', max_length=200)),
                ('consumed', models.BooleanField(default=False, help_text='Account has been created from this record.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pending_registrations', to='myApp.tenant')),
                ('tier', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pending_registrations', to='myApp.membershiptier')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='pendingregistration',
            index=models.Index(fields=['stripe_checkout_session_id'], name='myApp_pendi_stripe__10549e_idx'),
        ),
        migrations.AddIndex(
            model_name='pendingregistration',
            index=models.Index(fields=['consumed', 'created_at'], name='myApp_pendi_consume_7c6c2c_idx'),
        ),
    ]
