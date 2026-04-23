from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0029_tenant_is_archived'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantmembership',
            name='must_change_password',
            field=models.BooleanField(default=False),
        ),
    ]
