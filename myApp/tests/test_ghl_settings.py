import datetime
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from myApp.models import Event, GHLConnection, GHLLink, Tenant, TenantMembership

User = get_user_model()


@override_settings(ALLOWED_HOSTS=["*"])
class GhlSettingsPageTests(TestCase):
    HOST = "ncd.localhost"

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "GHL_CLIENT_ID": "client-id",
            "GHL_CLIENT_SECRET": "client-secret",
            "GHL_REDIRECT_URI": "https://courseforge.katek-ai.com/leadconnector/callback",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd", is_active=True, ghl_enabled=True)
        self.user = User.objects.create_user(username="admin", email="admin@ncd.test", password="pw")
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role="tenant_admin", is_active=True
        )
        self.conn = GHLConnection.objects.create(
            tenant=self.tenant,
            ghl_location_id="LOC1",
            event_calendar_ids="CALW",
            sync_status="connected",
            token_expires_at=timezone.now() + datetime.timedelta(hours=12),
        )
        self.conn.set_access_token("tok")
        self.conn.save()
        Event.objects.create(
            tenant=self.tenant,
            title="Synced Webinar",
            slug="synced-webinar",
            source="ghl",
            ghl_event_id="evt_1",
            ghl_calendar_id="CALW",
        )
        GHLLink.objects.create(tenant=self.tenant, connection=self.conn, ghl_contact_id="C1")
        self.client.force_login(self.user)

    @mock.patch("myApp.ghl_views.calendar_api.get_calendars", return_value=[
        {"id": "CALW", "name": "Webinar", "calendarType": "class_booking", "description": ""}
    ])
    def test_settings_page_shows_calendar_controls_and_backfill_counts(self, _calendars):
        resp = self.client.get("/dashboard/integrations/ghl/", HTTP_HOST=self.HOST)

        self.assertContains(resp, "Webinar")
        self.assertContains(resp, "Selected event calendars")
        self.assertContains(resp, "1 GHL event")
        self.assertContains(resp, "1 GHL contact link")
        self.assertContains(resp, "Run event sync now")

    def test_post_save_event_calendars_updates_connection(self):
        resp = self.client.post(
            "/dashboard/integrations/ghl/",
            {"action": "save_event_calendars", "event_calendar_ids": ["CALW", "CAL2"]},
            HTTP_HOST=self.HOST,
        )

        self.assertEqual(resp.status_code, 302)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.event_calendar_id_list, ["CALW", "CAL2"])

    @mock.patch("myApp.ghl_views.event_backfill.sync_connection_events")
    def test_post_run_event_sync_uses_connection_sync_service(self, sync):
        sync.return_value.upserted = 2
        sync.return_value.failed = 0
        sync.return_value.skipped = 0

        resp = self.client.post(
            "/dashboard/integrations/ghl/",
            {"action": "run_event_sync"},
            HTTP_HOST=self.HOST,
        )

        self.assertEqual(resp.status_code, 302)
        sync.assert_called_once()
