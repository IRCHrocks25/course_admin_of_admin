import os
from unittest import mock

from django.test import SimpleTestCase

from myApp.integrations.ghl import config


class ScopeTests(SimpleTestCase):
    def test_rich_scopes_present(self):
        scopes = set(config._DEFAULT_SCOPES.split())
        for s in [
            "contacts.readonly",
            "opportunities.readonly",
            "calendars.readonly",
            "conversations.readonly",
            "users.readonly",
            "workflows.readonly",
        ]:
            self.assertIn(s, scopes)

    def test_no_sensitive_unused(self):
        self.assertNotIn("users.write", config._DEFAULT_SCOPES.split())

    def test_scopes_falls_back_to_default_when_env_blank(self):
        with mock.patch.dict(os.environ, {"GHL_SCOPES": ""}, clear=False):
            self.assertEqual(config.scopes(), config._DEFAULT_SCOPES)
