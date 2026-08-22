"""Expire lapsed student memberships whose billing period has ended.

Run on a schedule (e.g. cron / scheduled worker) once or twice a day. This is
the reconciliation net for memberships webhooks can't close on their own:

* Complimentary grants (no Stripe subscription) never get a lifecycle event, so
  once their period ends they must be expired here.
* Paid subscriptions can drift if a renewal webhook is missed; they get a grace
  window before we expire, so a late ``invoice.paid`` can still renew them.

  python manage.py expire_memberships                 # expire lapsed memberships
  python manage.py expire_memberships --tenant slug   # limit to one tenant
  python manage.py expire_memberships --grace-hours 24
  python manage.py expire_memberships --dry-run       # report only
"""
from django.core.management.base import BaseCommand

from myApp.models import StudentSubscription, Tenant
from myApp.utils.membership import expire_lapsed_subscriptions


class Command(BaseCommand):
    help = "Expire student memberships whose period has ended (comp + drifted paid)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Limit to a single tenant slug.")
        parser.add_argument("--grace-hours", type=int, default=72,
                            help="Grace window for paid subscriptions before expiring (default 72).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would expire without saving changes.")

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant")
        grace_hours = options["grace_hours"]
        dry_run = options["dry_run"]

        tenant = None
        if tenant_slug:
            try:
                tenant = Tenant.objects.get(slug=tenant_slug)
            except Tenant.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"No tenant with slug '{tenant_slug}'"))
                return

        if dry_run:
            from django.utils import timezone
            import datetime

            now = timezone.now()
            paid_cutoff = now - datetime.timedelta(hours=max(grace_hours, 0))
            qs = StudentSubscription.objects.filter(
                status='active', current_period_end__isnull=False,
            ).select_related('tenant', 'user')
            if tenant is not None:
                qs = qs.filter(tenant=tenant)

            would = 0
            for sub in qs.iterator():
                is_comp = sub.is_complimentary or not sub.stripe_subscription_id
                cutoff = now if is_comp else paid_cutoff
                if sub.current_period_end <= cutoff:
                    would += 1
                    kind = "comp" if is_comp else "paid"
                    self.stdout.write(
                        f"[dry-run] would expire {sub.user.username} @ {sub.tenant.slug} "
                        f"({kind}, ended {sub.current_period_end:%Y-%m-%d})")
            self.stdout.write(self.style.NOTICE(f"Memberships that would expire: {would}"))
            return

        expired = expire_lapsed_subscriptions(tenant=tenant, paid_grace_hours=grace_hours)
        self.stdout.write(self.style.SUCCESS(f"Expired {expired} lapsed membership(s)."))
