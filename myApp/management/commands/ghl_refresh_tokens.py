"""Refresh GHL access tokens for connected tenants only.

Run on a schedule (e.g. cron / scheduled worker) a few times an hour. GHL access
tokens last ~24h; we refresh ahead of expiry. Refresh-token rotation + the
per-tenant row lock live in integrations.ghl.oauth.refresh_connection, so this
command is just selection + iteration.

Selection gates on the opt-in: only tenants with ghl_enabled AND a healthy-ish
connection that is near expiry. Disconnected tenants are skipped entirely.

  python manage.py ghl_refresh_tokens          # refresh those near expiry
  python manage.py ghl_refresh_tokens --all     # force-refresh every connection
  python manage.py ghl_refresh_tokens --dry-run # report only
"""
from django.core.management.base import BaseCommand

from myApp.integrations.ghl import oauth
from myApp.models import GHLConnection


class Command(BaseCommand):
    help = "Refresh GHL OAuth access tokens for connected tenants."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true",
                            help="Refresh every connection regardless of expiry.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would refresh without calling GHL.")

    def handle(self, *args, **options):
        force_all = options["all"]
        dry_run = options["dry_run"]

        connections = (
            GHLConnection.objects
            .filter(tenant__ghl_enabled=True)
            .exclude(sync_status="revoked")
            .select_related("tenant")
        )

        checked = refreshed = skipped = failed = 0
        for conn in connections:
            checked += 1
            if not force_all and not oauth.needs_refresh(conn):
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"[dry-run] would refresh {conn.tenant.slug} "
                                  f"(loc {conn.ghl_location_id}, expires {conn.token_expires_at})")
                refreshed += 1
                continue

            result = oauth.refresh_connection(conn.id)
            if result and result.is_healthy:
                refreshed += 1
                self.stdout.write(self.style.SUCCESS(f"refreshed {conn.tenant.slug}"))
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(
                    f"failed {conn.tenant.slug}: {getattr(result, 'status_detail', 'unknown')}"))

        self.stdout.write(self.style.NOTICE(
            f"GHL refresh: checked={checked} refreshed={refreshed} "
            f"skipped={skipped} failed={failed}"))
