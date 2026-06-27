"""Tests for the GHL calendar-event -> CourseForge Event writer.

apply_ghl_event maps a GHL appointment/calendar-event payload onto an Event,
idempotently keyed on the GHL event id. The join link comes from the GHL
`address` field (verified against the AppointmentCreate webhook schema).
"""
import datetime

from django.test import TestCase

from myApp.models import Event, Tenant
from myApp.integrations.ghl.events_sync import apply_ghl_event

# Shape mirrors the verified GHL appointment object (webhook + REST events).
PAYLOAD = {
    "id": "appt_123",
    "calendarId": "CAL1",
    "title": "NCD Webinar",
    "address": "https://zoom.us/j/123",
    "startTime": "2026-07-01T15:00:00+00:00",
    "endTime": "2026-07-01T16:30:00+00:00",
    "appointmentStatus": "confirmed",
}


class ApplyGhlEventTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")

    def test_creates_event_from_appointment(self):
        ev = apply_ghl_event(self.tenant, "CAL1", PAYLOAD)

        self.assertEqual(ev.tenant, self.tenant)
        self.assertEqual(ev.title, "NCD Webinar")
        self.assertEqual(ev.join_link, "https://zoom.us/j/123")
        self.assertEqual(ev.event_date, datetime.date(2026, 7, 1))
        self.assertEqual(ev.start_time, datetime.time(15, 0))
        self.assertEqual(ev.duration_minutes, 90)
        self.assertEqual(ev.ghl_event_id, "appt_123")
        self.assertEqual(ev.ghl_calendar_id, "CAL1")
        self.assertEqual(ev.source, "ghl")
        self.assertTrue(ev.slug)  # must populate the per-tenant unique slug

    def test_idempotent_on_ghl_event_id(self):
        first = apply_ghl_event(self.tenant, "CAL1", PAYLOAD)
        again = apply_ghl_event(self.tenant, "CAL1", {**PAYLOAD, "title": "NCD Webinar (updated)"})

        self.assertEqual(Event.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(again.slug, first.slug)  # slug stays stable across updates
        self.assertEqual(Event.objects.get(pk=first.pk).title, "NCD Webinar (updated)")

    def test_missing_end_time_defaults_duration(self):
        payload = {k: v for k, v in PAYLOAD.items() if k != "endTime"}
        ev = apply_ghl_event(self.tenant, "CAL1", payload)
        self.assertEqual(ev.duration_minutes, 60)
