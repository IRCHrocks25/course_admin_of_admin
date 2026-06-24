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
