"""Poll GHL calendar events into CourseForge live Events.

Run on a schedule. For each connected + ghl_enabled tenant, fetch events from
the connection's configured event calendars and upsert them (idempotent on the
GHL event id). Token refresh + single-use rotation are reused from
integrations.ghl.oauth, so this command is selection + fetch + upsert only.

  python manage.py sync_ghl_events
  python manage.py sync_ghl_events --days-back 30 --days-ahead 365
  python manage.py sync_ghl_events --dry-run
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from myApp.integrations.ghl import calendar_api, events_sync, oauth
from myApp.models import GHLConnection


class Command(BaseCommand):
    help = "Sync GHL calendar events into CourseForge live Events."

    def add_arguments(self, parser):
        parser.add_argument("--days-back", type=int, default=180)
        parser.add_argument("--days-ahead", type=int, default=180)
        parser.add_argument("--dry-run", action="store_true",
                            help="Fetch and report without writing Events.")

    def handle(self, *args, **options):
        now = timezone.now()
        start_ms = int((now - timedelta(days=options["days_back"])).timestamp() * 1000)
        end_ms = int((now + timedelta(days=options["days_ahead"])).timestamp() * 1000)
        dry_run = options["dry_run"]

        connections = (
            GHLConnection.objects
            .filter(tenant__ghl_enabled=True)
            .exclude(sync_status="revoked")
            .select_related("tenant")
        )

        upserted = failed = 0
        for conn in connections:
            cal_ids = [c.strip() for c in (conn.event_calendar_ids or "").split(",") if c.strip()]
            if not cal_ids:
                continue

            if oauth.needs_refresh(conn):
                refreshed = oauth.refresh_connection(conn.id)
                if not (refreshed and refreshed.is_healthy):
                    failed += 1
                    self.stdout.write(self.style.ERROR(
                        f"skip {conn.tenant.slug}: token refresh failed"))
                    continue
                conn = refreshed

            token = conn.get_access_token()
            for cal_id in cal_ids:
                try:
                    events = calendar_api.get_calendar_events(
                        token, conn.ghl_location_id, cal_id, start_ms, end_ms)
                except Exception as exc:
                    failed += 1
                    self.stdout.write(self.style.ERROR(f"{conn.tenant.slug}/{cal_id}: {exc}"))
                    continue
                for ev in events:
                    if dry_run:
                        continue
                    events_sync.apply_ghl_event(conn.tenant, cal_id, ev)
                    upserted += 1

        self.stdout.write(self.style.NOTICE(
            f"GHL events sync: upserted={upserted} failed={failed}"))
