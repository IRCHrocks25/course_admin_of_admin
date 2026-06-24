import os
from unittest import mock

from django.test import SimpleTestCase

from myApp.integrations.ghl import oauth


class AuthorizeUrlTests(SimpleTestCase):
    @mock.patch.dict(
        os.environ,
        {
            "GHL_CLIENT_ID": "appid123-verxyz",
            "GHL_REDIRECT_URI": "https://courseforge.katek-ai.com/leadconnector/callback",
        },
        clear=False,
    )
    def test_includes_version_id_from_client_id(self):
        url = oauth.build_authorize_url("state123")
        self.assertIn("client_id=appid123-verxyz", url)
        self.assertIn("version_id=appid123", url)
        self.assertIn("state=state123", url)
        self.assertIn("leadconnector%2Fcallback", url)

    @mock.patch.dict(os.environ, {"GHL_CLIENT_ID": "plainid"}, clear=False)
    def test_no_version_id_when_client_id_has_no_suffix(self):
        url = oauth.build_authorize_url("s")
        self.assertNotIn("version_id=", url)
