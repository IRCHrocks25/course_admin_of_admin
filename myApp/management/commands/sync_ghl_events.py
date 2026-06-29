"""Poll GHL calendar events into CourseForge live Events.

Run on a schedule. For each connected + ghl_enabled tenant, fetch events from
the connection's configured event calendars and upsert them (idempotent on the
GHL event id). Token refresh + single-use rotation are reused from
integrations.ghl.oauth, so this command is selection + fetch + upsert only.

  python manage.py sync_ghl_events
  python manage.py sync_ghl_events --days-back 30 --days-ahead 365
  python manage.py sync_ghl_events --dry-run
"""
from django.core.management.base import BaseCommand

from myApp.integrations.ghl import event_backfill
from myApp.models import GHLConnection


class Command(BaseCommand):
    help = "Sync GHL calendar events into CourseForge live Events."

    def add_arguments(self, parser):
        parser.add_argument("--days-back", type=int, default=180)
        parser.add_argument("--days-ahead", type=int, default=180)
        parser.add_argument("--dry-run", action="store_true",
                            help="Fetch and report without writing Events.")

    def handle(self, *args, **options):
        connections = (
            GHLConnection.objects
            .filter(tenant__ghl_enabled=True)
            .exclude(sync_status="revoked")
            .select_related("tenant")
        )
        result = event_backfill.sync_all_connections(
            connections,
            days_back=options["days_back"],
            days_ahead=options["days_ahead"],
            dry_run=options["dry_run"],
        )
        for error in result.errors:
            self.stdout.write(self.style.ERROR(error))

        self.stdout.write(self.style.NOTICE(
            f"GHL events sync: upserted={result.upserted} failed={result.failed}"))
