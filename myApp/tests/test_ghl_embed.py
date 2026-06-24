from django.test import TestCase
from myApp.models import Tenant
from myApp.models_ghl import GhlEmbedSession


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
