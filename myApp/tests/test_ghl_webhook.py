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
from myApp.models import Tenant
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
