"""Tests for the sync_ghl_events poll command.

The command selects connected+enabled tenants, reads each connection's
configured event calendar ids, fetches calendar events from GHL, and upserts
them as Events. The GHL HTTP fetch is the external boundary and is patched;
selection + upsert run against the real DB.
"""
import datetime
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from myApp.models import Event, GHLConnection, Tenant

EVENTS = [
    {"id": "e1", "calendarId": "CALW", "title": "W1", "address": "https://z/1",
     "startTime": "2026-07-05T18:00:00+00:00", "endTime": "2026-07-05T19:00:00+00:00"},
    {"id": "e2", "calendarId": "CALW", "title": "W2", "address": "https://z/2",
     "startTime": "2026-07-12T18:00:00+00:00", "endTime": "2026-07-12T19:00:00+00:00"},
]


class SyncGhlEventsCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd", ghl_enabled=True)
        self.conn = GHLConnection.objects.create(
            tenant=self.tenant, ghl_location_id="LOC1",
            event_calendar_ids="CALW", sync_status="connected",
            token_expires_at=timezone.now() + datetime.timedelta(hours=12),
        )

    @mock.patch("myApp.integrations.ghl.calendar_api.get_calendar_events", return_value=EVENTS)
    def test_syncs_events_for_connected_tenant(self, _fetch):
        call_command("sync_ghl_events")
        self.assertEqual(Event.objects.filter(tenant=self.tenant, source="ghl").count(), 2)

    @mock.patch("myApp.integrations.ghl.calendar_api.get_calendar_events", return_value=EVENTS)
    def test_skips_connection_without_event_calendars(self, fetch):
        self.conn.event_calendar_ids = ""
        self.conn.save()
        call_command("sync_ghl_events")
        fetch.assert_not_called()
        self.assertEqual(Event.objects.filter(source="ghl").count(), 0)

    @mock.patch("myApp.integrations.ghl.calendar_api.get_calendar_events", return_value=EVENTS)
    def test_skips_disabled_tenant(self, fetch):
        self.tenant.ghl_enabled = False
        self.tenant.save()
        call_command("sync_ghl_events")
        fetch.assert_not_called()
