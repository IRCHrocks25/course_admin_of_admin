from unittest import mock
from django.test import TestCase
from myApp.models import Tenant
from myApp.models_ghl import GHLConnection
from myApp.integrations.ghl import state


class CallbackCompanyInstallTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")

    @mock.patch("myApp.ghl_views.oauth.get_location_token")
    @mock.patch("myApp.ghl_views.oauth.exchange_code")
    def test_company_token_mints_location_token(self, mock_exchange, mock_mint):
        mock_exchange.return_value = {
            "access_token": "company-tok", "refresh_token": "r",
            "expires_in": 3600, "companyId": "CO1", "userType": "Company", "scope": "x",
        }
        mock_mint.return_value = {
            "access_token": "loc-tok", "refresh_token": "r2",
            "expires_in": 3600, "locationId": "LOC9", "companyId": "CO1", "scope": "x",
        }
        token = state.encode(self.tenant.id)
        resp = self.client.get("/leadconnector/callback", {"code": "abc", "state": token})
        mock_mint.assert_called_once()
        conn = GHLConnection.objects.get(tenant=self.tenant)
        self.assertEqual(conn.ghl_location_id, "LOC9")
