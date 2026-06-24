from django.test import TestCase
from django.contrib.auth import get_user_model
from myApp.models import Tenant, TenantMembership
from myApp.models_ghl import GhlEmbedSession
from myApp.integrations.ghl import embed as embed_helper
from myApp.integrations.ghl.user_context import GhlUserContext

User = get_user_model()


class GhlEmbedSessionModelTests(TestCase):
    def test_create_audit_row(self):
        tenant = Tenant.objects.create(name="NCD", slug="ncd")
        row = GhlEmbedSession.objects.create(
            tenant=tenant,
            ghl_location_id="LOC123",
            ghl_email="user@ncd.com",
            impersonated_owner=True,
        )
        self.assertTrue(row.impersonated_owner)
        self.assertEqual(row.tenant, tenant)


class ResolveEmbedUserTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")
        self.owner = User.objects.create_user(username="owner", email="owner@ncd.com", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.owner, role="tenant_admin", is_active=True)
        self.member = User.objects.create_user(username="mem", email="mem@ncd.com", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.member, role="tenant_admin", is_active=True)

    def test_email_match_uses_member(self):
        ctx = GhlUserContext(location_id="L", email="mem@ncd.com")
        user, impersonated = embed_helper.resolve_user(self.tenant, ctx)
        self.assertEqual(user, self.member)
        self.assertFalse(impersonated)

    def test_no_match_falls_back_to_owner(self):
        ctx = GhlUserContext(location_id="L", email="stranger@x.com")
        user, impersonated = embed_helper.resolve_user(self.tenant, ctx)
        self.assertEqual(user, self.owner)
        self.assertTrue(impersonated)


from django.test import Client, override_settings
from myApp.models_ghl import GHLConnection
import json

SECRET = "embed-secret"


@override_settings(GHL_SHARED_SECRET_KEY=SECRET, ALLOWED_HOSTS=["*"])
class EmbedViewTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")
        owner = User.objects.create_user(username="o", email="o@ncd.com", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=owner, role="tenant_admin", is_active=True)
        GHLConnection.objects.create(tenant=self.tenant, ghl_location_id="LOC123")
        self.client = Client()

    def _blob(self, payload):
        from myApp.tests.test_ghl_user_context import _cryptojs_encrypt
        return _cryptojs_encrypt(json.dumps(payload), SECRET)

    def test_missing_blob_renders_unauthorized(self):
        resp = self.client.get("/leadconnector/embed")
        self.assertContains(resp, "Open from a sub-account", status_code=200)

    def test_unknown_location_renders_not_connected(self):
        resp = self.client.get("/leadconnector/embed", {"encryptedUserData": self._blob({"locationId": "NOPE"})})
        self.assertContains(resp, "not connected", status_code=200)

    def test_known_location_redirects_to_sso(self):
        resp = self.client.get("/leadconnector/embed", {"encryptedUserData": self._blob({"locationId": "LOC123", "email": "o@ncd.com"})})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/leadconnector/sso", resp["Location"])
        self.assertEqual(GhlEmbedSession.objects.count(), 1)

    def test_agency_context_renders_unauthorized(self):
        blob = self._blob({"locationId": "LOC123", "type": "agency"})
        resp = self.client.get("/leadconnector/embed", {"encryptedUserData": blob})
        self.assertContains(resp, "Open from a sub-account", status_code=200)


from myApp.integrations.ghl import sso


@override_settings(ALLOWED_HOSTS=["*"])
class SsoViewTests(TestCase):
    # Tenant resolves from the host subdomain slug via TenantMiddleware.
    HOST = "ncd.localhost"

    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd", is_active=True)
        self.user = User.objects.create_user(username="u", email="u@ncd.com", password="x")
        self.audit = GhlEmbedSession.objects.create(tenant=self.tenant, ghl_location_id="L")
        self.client = Client()

    def _token(self, tenant_id=None):
        return sso.issue(
            user_id=self.user.id,
            tenant_id=tenant_id or self.tenant.id,
            embed_session_id=self.audit.id,
        )

    def test_valid_token_logs_in_and_redirects(self):
        resp = self.client.get(f"/leadconnector/sso?t={self._token()}&next=/dashboard", HTTP_HOST=self.HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/dashboard")
        self.assertIn("_auth_user_id", self.client.session)
        self.assertTrue(self.client.session.get("ghl_embed"))
        from django.conf import settings
        out = resp.cookies[settings.SESSION_COOKIE_NAME].OutputString()
        self.assertIn("Partitioned", out)
        self.assertNotIn("partitioned=True", out)
        self.assertIn("SameSite=None", out)
        self.assertIn("Secure", out)

    def test_replayed_token_returns_403(self):
        token = self._token()
        self.client.get(f"/leadconnector/sso?t={token}", HTTP_HOST=self.HOST)
        resp = self.client.get(f"/leadconnector/sso?t={token}", HTTP_HOST=self.HOST)
        self.assertEqual(resp.status_code, 403)

    def test_wrong_tenant_returns_403(self):
        other = Tenant.objects.create(name="X", slug="x", is_active=True)
        resp = self.client.get(f"/leadconnector/sso?t={self._token(tenant_id=other.id)}", HTTP_HOST=self.HOST)
        self.assertEqual(resp.status_code, 403)

    def test_open_redirect_blocked(self):
        resp = self.client.get(f"/leadconnector/sso?t={self._token()}&next=//evil.com", HTTP_HOST=self.HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/dashboard")
