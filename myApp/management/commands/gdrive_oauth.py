"""
Obtain a Google Drive refresh token for lesson video-script Docs.

Prefer Superadmin → Google Drive → Connect. This command is a fallback
(local Desktop / installed-app flow). It now writes the token into
PlatformConfig instead of asking you to paste it into .env.

Testing-mode Cloud OAuth apps expire the refresh token after 7 days.
Reconnect from Superadmin (or re-run this command) weekly.

  python manage.py gdrive_oauth
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from myApp.utils.gdrive import DRIVE_SCOPE, save_refresh_token


class Command(BaseCommand):
    help = 'Run Google Drive OAuth and store the refresh token in the database'

    def handle(self, *args, **options):
        client_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
        client_secret = getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '')
        if not client_id or not client_secret:
            raise CommandError(
                'Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET first.'
            )

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise CommandError(
                'google-auth-oauthlib is required. Install project requirements.'
            ) from exc

        flow = InstalledAppFlow.from_client_config(
            {
                'installed': {
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                    'token_uri': 'https://oauth2.googleapis.com/token',
                    'redirect_uris': ['http://localhost:8080/'],
                }
            },
            scopes=[DRIVE_SCOPE],
        )
        creds = flow.run_local_server(port=8080, prompt='consent')
        token = getattr(creds, 'refresh_token', None) or ''
        if not token:
            raise CommandError(
                'Google did not return a refresh token. Revoke the app at '
                'https://myaccount.google.com/permissions and try again with prompt=consent.'
            )

        save_refresh_token(token)
        self.stdout.write(self.style.SUCCESS(
            'Refresh token saved to PlatformConfig (Superadmin → Google Drive).'
        ))
        self.stdout.write(
            'Testing-mode OAuth clients expire this token after 7 days. '
            'Reconnect from Superadmin weekly or new Docs will fail while lesson JSON still saves.'
        )
