"""Platform Drive OAuth: DB token storage and Superadmin gate."""
from django.test import TestCase, override_settings
from django.urls import reverse

from myApp.models import PlatformConfig
from myApp.tests.base import SeededTestCase
from myApp.utils import gdrive


class PlatformConfigTokenTests(TestCase):
    def test_encrypts_and_reads_refresh_token(self):
        config = PlatformConfig.get_solo()
        config.set_gdrive_refresh_token('rt-secret-123')
        config.gdrive_scripts_root_id = 'folderRoot'
        config.save()

        fresh = PlatformConfig.get_solo()
        self.assertEqual(fresh.get_gdrive_refresh_token(), 'rt-secret-123')
        self.assertTrue(fresh.gdrive_connected)
        self.assertNotEqual(fresh.gdrive_refresh_token_encrypted, 'rt-secret-123')

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID='cid',
        GOOGLE_OAUTH_CLIENT_SECRET='csecret',
        GOOGLE_OAUTH_REFRESH_TOKEN='',
        GDRIVE_SCRIPTS_ROOT_ID='',
    )
    def test_is_configured_reads_db_not_env(self):
        config = PlatformConfig.get_solo()
        config.set_gdrive_refresh_token('rt-from-db')
        config.gdrive_scripts_root_id = 'root-from-db'
        config.save()
        self.assertTrue(gdrive.is_gdrive_configured())
        self.assertEqual(gdrive.get_refresh_token(), 'rt-from-db')
        self.assertEqual(gdrive.get_scripts_root_id(), 'root-from-db')

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID='cid',
        GOOGLE_OAUTH_CLIENT_SECRET='csecret',
        GOOGLE_OAUTH_REFRESH_TOKEN='rt-from-env',
        GDRIVE_SCRIPTS_ROOT_ID='root-from-env',
    )
    def test_env_fallback_when_db_empty(self):
        PlatformConfig.get_solo()
        self.assertEqual(gdrive.get_refresh_token(), 'rt-from-env')
        self.assertEqual(gdrive.get_scripts_root_id(), 'root-from-env')
        self.assertTrue(gdrive.is_gdrive_configured())


class SuperadminGdriveAccessTests(SeededTestCase):
    def test_connect_without_client_creds_redirects(self):
        url = reverse('superadmin_gdrive_connect')
        client = self.client_for('super')
        with override_settings(GOOGLE_OAUTH_CLIENT_ID='', GOOGLE_OAUTH_CLIENT_SECRET=''):
            resp = client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('superadmin_gdrive_settings'))
