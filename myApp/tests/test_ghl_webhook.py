import base64
from django.test import SimpleTestCase, override_settings
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from myApp.integrations.ghl import webhook

_priv = Ed25519PrivateKey.generate()
_pub_b64 = base64.b64encode(
    _priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
).decode()


@override_settings(GHL_WEBHOOK_PUBLIC_KEY=_pub_b64)
class WebhookVerifyTests(SimpleTestCase):
    def test_valid_signature(self):
        body = b'{"type":"ContactCreate"}'
        sig = base64.b64encode(_priv.sign(body)).decode()
        self.assertTrue(webhook.verify(body, sig))

    def test_bad_signature(self):
        self.assertFalse(webhook.verify(b'{"type":"X"}', base64.b64encode(b"wrong").decode()))

    def test_tampered_body(self):
        sig = base64.b64encode(_priv.sign(b'{"type":"A"}')).decode()
        self.assertFalse(webhook.verify(b'{"type":"B"}', sig))


import json
from django.test import TestCase, Client
from myApp.models import Tenant, Event
from myApp.models_ghl import GHLConnection, GHLLink


@override_settings(GHL_WEBHOOK_PUBLIC_KEY=_pub_b64)
class WebhookViewTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")
        self.conn = GHLConnection.objects.create(tenant=self.tenant, ghl_location_id="LOC1")
        self.client = Client()

    def _post(self, payload):
        body = json.dumps(payload).encode()
        sig = base64.b64encode(_priv.sign(body)).decode()
        return self.client.post(
            "/leadconnector/webhook", data=body, content_type="application/json",
            HTTP_X_GHL_SIGNATURE=sig,
        )

    def test_bad_signature_rejected(self):
        resp = self.client.post("/leadconnector/webhook", data=b"{}", content_type="application/json",
                                HTTP_X_GHL_SIGNATURE="bad")
        self.assertEqual(resp.status_code, 401)

    def test_contact_create_makes_link(self):
        resp = self._post({"type": "ContactCreate", "locationId": "LOC1", "id": "C9"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(GHLLink.objects.filter(tenant=self.tenant, ghl_contact_id="C9").exists())

    def test_unknown_event_ignored(self):
        resp = self._post({"type": "InvoicePaid", "locationId": "LOC1"})
        self.assertEqual(resp.status_code, 200)
        self.assertJSONEqual(resp.content, {"status": "ignored"})


@override_settings(GHL_WEBHOOK_PUBLIC_KEY=_pub_b64)
class WebhookAppointmentTests(TestCase):
    """AppointmentCreate/Update upserts an Event; AppointmentDelete removes it.

    Payload shape mirrors the verified GHL AppointmentCreate webhook: top-level
    type + locationId, with the event under a nested `appointment` object whose
    join link is in `address`.
    """

    APPT = {
        "type": "AppointmentCreate",
        "locationId": "LOCA",
        "appointment": {
            "id": "appt_77",
            "calendarId": "CALW",
            "title": "Webinar Session",
            "address": "https://zoom.us/j/777",
            "startTime": "2026-07-05T18:00:00+00:00",
            "endTime": "2026-07-05T19:00:00+00:00",
        },
    }

    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd-appt")
        GHLConnection.objects.create(tenant=self.tenant, ghl_location_id="LOCA")
        self.client = Client()

    def _post(self, payload):
        body = json.dumps(payload).encode()
        sig = base64.b64encode(_priv.sign(body)).decode()
        return self.client.post(
            "/leadconnector/webhook", data=body, content_type="application/json",
            HTTP_X_GHL_SIGNATURE=sig,
        )

    def test_appointment_create_makes_event(self):
        resp = self._post(self.APPT)
        self.assertEqual(resp.status_code, 200)
        ev = Event.objects.get(tenant=self.tenant, ghl_event_id="appt_77")
        self.assertEqual(ev.join_link, "https://zoom.us/j/777")
        self.assertEqual(ev.ghl_calendar_id, "CALW")
        self.assertEqual(ev.source, "ghl")

    def test_appointment_delete_removes_event(self):
        self._post(self.APPT)
        resp = self._post({
            "type": "AppointmentDelete", "locationId": "LOCA",
            "appointment": {"id": "appt_77"},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            Event.objects.filter(tenant=self.tenant, ghl_event_id="appt_77").exists()
        )


from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class DefaultWebhookKeyTests(SimpleTestCase):
    """GHL's webhook public key is global; we bake it in as the settings default
    so webhooks verify without per-env config."""

    def test_default_key_is_valid_ed25519(self):
        # No override -> uses settings default (GHL's published global key).
        key = webhook._load_public_key()
        self.assertIsInstance(key, Ed25519PublicKey)
