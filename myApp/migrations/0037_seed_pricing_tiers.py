from django.db import migrations


TIERS = [
    {
        'code': 'essential',
        'name': 'Essential',
        'description': 'Everything you need to launch your first course.',
        'setup_fee_cents': 35000,
        'monthly_cents': 9700,
        'yearly_cents': 97000,
        'sort_order': 0,
    },
    {
        'code': 'premium',
        'name': 'Premium',
        'description': 'Advanced features for growing academies.',
        'setup_fee_cents': 55000,
        'monthly_cents': 14700,
        'yearly_cents': 147000,
        'sort_order': 1,
    },
    {
        'code': 'enterprise',
        'name': 'Enterprise',
        'description': 'Full platform power for established businesses.',
        'setup_fee_cents': 75000,
        'monthly_cents': 19700,
        'yearly_cents': 197000,
        'sort_order': 2,
    },
]


def seed_tiers(apps, schema_editor):
    PricingTier = apps.get_model('myApp', 'PricingTier')
    for tier in TIERS:
        PricingTier.objects.update_or_create(
            code=tier['code'],
            defaults=tier,
        )


def remove_tiers(apps, schema_editor):
    PricingTier = apps.get_model('myApp', 'PricingTier')
    PricingTier.objects.filter(code__in=[t['code'] for t in TIERS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0036_pricing_and_notifications'),
    ]

    operations = [
        migrations.RunPython(seed_tiers, remove_tiers),
    ]
