import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from myApp.models import Event, GHLConnection, Tenant


EVENTS = [
    {
        "id": "e1",
        "calendarId": "CALW",
        "title": "Webinar 1",
        "address": "https://zoom.test/1",
        "startTime": "2026-07-05T18:00:00+00:00",
        "endTime": "2026-07-05T19:00:00+00:00",
    }
]


class GhlEventBackfillTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd", ghl_enabled=True)
        self.conn = GHLConnection.objects.create(
            tenant=self.tenant,
            ghl_location_id="LOC1",
            event_calendar_ids="CALW",
            sync_status="connected",
            token_expires_at=timezone.now() + datetime.timedelta(hours=12),
        )
        self.conn.set_access_token("tok")
        self.conn.save()

    @mock.patch("myApp.integrations.ghl.calendar_api.get_calendar_events", return_value=EVENTS)
    def test_sync_connection_events_backfills_selected_calendars(self, _fetch):
        from myApp.integrations.ghl import event_backfill

        result = event_backfill.sync_connection_events(self.conn)

        self.assertEqual(result.upserted, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(Event.objects.filter(tenant=self.tenant, source="ghl").count(), 1)

    @mock.patch("myApp.integrations.ghl.calendar_api.get_calendar_events")
    def test_sync_connection_events_skips_without_selected_calendars(self, fetch):
        from myApp.integrations.ghl import event_backfill

        self.conn.event_calendar_ids = ""
        self.conn.save()
        result = event_backfill.sync_connection_events(self.conn)

        self.assertEqual(result.skipped, 1)
        fetch.assert_not_called()
