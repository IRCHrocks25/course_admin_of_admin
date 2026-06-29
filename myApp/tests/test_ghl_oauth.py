import os
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from myApp.integrations.ghl import config, oauth


class AuthorizeUrlTests(SimpleTestCase):
    @mock.patch.dict(os.environ, {"GHL_INSTALL_URL": "", "GHL_SCOPES": ""}, clear=False)
    def test_uses_fixed_marketplace_install_url_and_appends_state(self):
        url = oauth.build_authorize_url("state123")
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)

        self.assertEqual(
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            "https://marketplace.leadconnectorhq.com/v2/oauth/chooselocation",
        )
        self.assertEqual(params["client_id"], ["6a3c63e708b022331c8b15d5-mqspg6bj"])
        self.assertEqual(params["version_id"], ["6a3c63e708b022331c8b15d5"])
        self.assertEqual(params["state"], ["state123"])
        self.assertIn("leadconnector%2Fcallback", url)
        self.assertIn("funnels%2Fpage.readonly", url)
        self.assertIn("funnels%2Ffunnel.readonly", url)
        self.assertIn("funnels%2Fpagecount.readonly", url)

    @mock.patch.dict(os.environ, {"GHL_INSTALL_URL": "", "GHL_SCOPES": ""}, clear=False)
    def test_default_scopes_match_fixed_install_url(self):
        scopes = config.scopes().split()

        self.assertIn("funnels/page.readonly", scopes)
        self.assertIn("funnels/funnel.readonly", scopes)
        self.assertIn("funnels/pagecount.readonly", scopes)
