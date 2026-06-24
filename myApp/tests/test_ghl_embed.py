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
