"""Pull paid student memberships from Stripe so records don't drift.

Webhooks are the primary sync path, but own-keys / Connect tenants can drift if
an event is missed. Run this on a schedule (e.g. cron / scheduled worker) a few
times a day to reconcile status + period end straight from Stripe. Complimentary
memberships are skipped (nothing to pull); use ``expire_memberships`` for those.

  python manage.py sync_memberships                 # reconcile all paid subs
  python manage.py sync_memberships --tenant slug   # limit to one tenant
  python manage.py sync_memberships --dry-run       # report only
"""
from django.core.management.base import BaseCommand

from myApp.models import StudentSubscription, Tenant
from myApp.utils.membership_sync import pull_subscription_from_stripe, sync_paid_subscriptions


class Command(BaseCommand):
    help = "Pull paid membership status/period from Stripe (webhook reconciliation net)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Limit to a single tenant slug.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report which subs would be pulled without calling Stripe.")

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant")
        dry_run = options["dry_run"]

        tenant = None
        if tenant_slug:
            try:
                tenant = Tenant.objects.get(slug=tenant_slug)
            except Tenant.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"No tenant with slug '{tenant_slug}'"))
                return

        if dry_run:
            qs = (
                StudentSubscription.objects
                .filter(is_complimentary=False, status__in=('active', 'past_due', 'incomplete'))
                .exclude(stripe_subscription_id='')
                .select_related('tenant', 'user')
            )
            if tenant is not None:
                qs = qs.filter(tenant=tenant)
            count = 0
            for sub in qs.iterator():
                count += 1
                self.stdout.write(
                    f"[dry-run] would pull {sub.user.username} @ {sub.tenant.slug} "
                    f"(sub {sub.stripe_subscription_id}, status {sub.status})")
            self.stdout.write(self.style.NOTICE(f"Paid subscriptions that would be pulled: {count}"))
            return

        summary = sync_paid_subscriptions(tenant=tenant)
        for sub, err in summary['error_detail']:
            self.stdout.write(self.style.WARNING(
                f"  ! {sub.user.username} @ {sub.tenant.slug}: {err}"))
        self.stdout.write(self.style.SUCCESS(
            f"Membership sync: checked={summary['checked']} "
            f"changed={summary['changed']} errors={summary['errors']}"))
