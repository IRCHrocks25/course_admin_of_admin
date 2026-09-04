"""
Platform-level Google Drive helper for lesson video-script Docs.

Uses a single OAuth user. The refresh token lives encrypted on PlatformConfig
(Superadmin Connect button). Client ID/secret stay in env. If credentials are
missing or an API call fails, callers should log and continue — lesson JSON
still saves.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

logger = logging.getLogger(__name__)

DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive'
FOLDER_MIME = 'application/vnd.google-apps.folder'
DOC_MIME = 'application/vnd.google-apps.document'
_OAUTH_STATE_SALT = 'gdrive.oauth.state.v1'
_OAUTH_STATE_MAX_AGE = 600


def oauth_client_configured() -> bool:
    return bool(
        getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
        and getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '')
    )


def get_refresh_token() -> str:
    """DB token first, then env fallback (legacy .env setups)."""
    try:
        from myApp.models import PlatformConfig
        token = PlatformConfig.get_solo().get_gdrive_refresh_token()
        if token:
            return token
    except Exception:
        logger.exception('Failed to read Drive refresh token from PlatformConfig')
    return (getattr(settings, 'GOOGLE_OAUTH_REFRESH_TOKEN', '') or '').strip()


def get_scripts_root_id() -> str:
    try:
        from myApp.models import PlatformConfig
        root = (PlatformConfig.get_solo().gdrive_scripts_root_id or '').strip()
        if root:
            return root
    except Exception:
        logger.exception('Failed to read Drive scripts root from PlatformConfig')
    return (getattr(settings, 'GDRIVE_SCRIPTS_ROOT_ID', '') or '').strip()


def save_refresh_token(token: str, user=None) -> None:
    from myApp.models import PlatformConfig
    config = PlatformConfig.get_solo()
    config.set_gdrive_refresh_token(token)
    config.gdrive_connected_at = timezone.now() if token else None
    config.gdrive_connected_by = user if token else None
    config.save(update_fields=[
        'gdrive_refresh_token_encrypted',
        'gdrive_connected_at',
        'gdrive_connected_by',
        'updated_at',
    ])


def clear_refresh_token() -> None:
    save_refresh_token('', user=None)


def is_gdrive_configured() -> bool:
    return bool(oauth_client_configured() and get_refresh_token() and get_scripts_root_id())


def resolve_redirect_uri(request=None) -> str:
    override = (getattr(settings, 'GOOGLE_OAUTH_REDIRECT_URI', '') or '').strip()
    if override:
        return override
    if request is not None:
        return request.build_absolute_uri(reverse('superadmin_gdrive_callback'))
    return ''


def encode_oauth_state(user_id: int) -> str:
    return signing.dumps(
        {'u': int(user_id), 'n': get_random_string(16)},
        salt=_OAUTH_STATE_SALT,
        compress=True,
    )


def decode_oauth_state(state: str) -> dict:
    return signing.loads(state, salt=_OAUTH_STATE_SALT, max_age=_OAUTH_STATE_MAX_AGE)


def _client_config(redirect_uri: str) -> dict:
    return {
        'web': {
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [redirect_uri],
        }
    }


def _allow_insecure_transport():
    if getattr(settings, 'DEBUG', False):
        import os
        os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')


def build_authorize_url(redirect_uri: str, state: str) -> str:
    from google_auth_oauthlib.flow import Flow

    _allow_insecure_transport()
    flow = Flow.from_client_config(
        _client_config(redirect_uri),
        scopes=[DRIVE_SCOPE],
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=state,
    )
    return auth_url


def exchange_code(code: str, redirect_uri: str) -> str:
    """Exchange an auth code for a refresh token. Raises on failure."""
    from google_auth_oauthlib.flow import Flow

    _allow_insecure_transport()
    flow = Flow.from_client_config(
        _client_config(redirect_uri),
        scopes=[DRIVE_SCOPE],
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    token = getattr(flow.credentials, 'refresh_token', None) or ''
    if not token:
        raise ValueError(
            'Google did not return a refresh token. Disconnect the app at '
            'https://myaccount.google.com/permissions and connect again.'
        )
    return token


def _escape_drive_query(value: str) -> str:
    return (value or '').replace('\\', '\\\\').replace("'", "\\'")


def _credentials():
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=None,
        refresh_token=get_refresh_token(),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=[DRIVE_SCOPE],
    )


def _drive_service():
    from googleapiclient.discovery import build

    return build('drive', 'v3', credentials=_credentials(), cache_discovery=False)


def ensure_course_folder(course_name: str) -> Optional[str]:
    """Return the Drive folder id for SOP Course Video Scripts/<course_name>/."""
    if not is_gdrive_configured():
        return None
    name = (course_name or 'Untitled Course').strip() or 'Untitled Course'
    parent = get_scripts_root_id()
    service = _drive_service()
    query = (
        f"name = '{_escape_drive_query(name)}' "
        f"and mimeType = '{FOLDER_MIME}' "
        f"and '{parent}' in parents "
        f"and trashed = false"
    )
    found = service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)',
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = found.get('files') or []
    if files:
        return files[0]['id']
    created = service.files().create(
        body={
            'name': name,
            'mimeType': FOLDER_MIME,
            'parents': [parent],
        },
        fields='id',
        supportsAllDrives=True,
    ).execute()
    return created.get('id')


def create_or_update_script_doc(
    folder_id: str,
    title: str,
    html: str,
    existing_id: str | None = None,
) -> tuple[str, str]:
    """
    Convert HTML into a Google Doc in folder_id.

    Updates existing_id when set; otherwise creates a new Doc.
    Returns (file_id, web_url).
    """
    from googleapiclient.http import MediaIoBaseUpload

    service = _drive_service()
    media = MediaIoBaseUpload(
        io.BytesIO((html or '').encode('utf-8')),
        mimetype='text/html',
        resumable=False,
    )
    existing = (existing_id or '').strip()
    if existing:
        try:
            updated = service.files().update(
                fileId=existing,
                body={'name': title},
                media_body=media,
                fields='id, webViewLink',
                supportsAllDrives=True,
            ).execute()
            file_id = updated.get('id') or existing
            url = updated.get('webViewLink') or f'https://docs.google.com/document/d/{file_id}/edit'
            return file_id, url
        except Exception as exc:
            logger.warning('Drive update failed for %s (%s); creating a new Doc', existing, exc)

    created = service.files().create(
        body={
            'name': title,
            'mimeType': DOC_MIME,
            'parents': [folder_id],
        },
        media_body=media,
        fields='id, webViewLink',
        supportsAllDrives=True,
    ).execute()
    file_id = created.get('id') or ''
    url = created.get('webViewLink') or (
        f'https://docs.google.com/document/d/{file_id}/edit' if file_id else ''
    )
    return file_id, url
