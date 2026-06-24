import time
from django.test import SimpleTestCase, override_settings
from django.core.cache import cache

from myApp.integrations.ghl import sso


class SsoTokenTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_roundtrip(self):
        token = sso.issue(user_id=7, tenant_id=3, embed_session_id=99)
        data = sso.consume(token)
        self.assertEqual(data, {"u": 7, "t": 3, "e": 99})

    def test_single_use(self):
        token = sso.issue(user_id=7, tenant_id=3, embed_session_id=99)
        sso.consume(token)
        with self.assertRaises(sso.SsoError):
            sso.consume(token)

    @override_settings(GHL_SSO_TTL_SECONDS=0)
    def test_expired(self):
        token = sso.issue(user_id=7, tenant_id=3, embed_session_id=99)
        time.sleep(1)
        with self.assertRaises(sso.SsoError):
            sso.consume(token)

    def test_tampered(self):
        with self.assertRaises(sso.SsoError):
            sso.consume("garbage.token.value")
