"""
Iceberg CDN client (self-hosted CDN on Cloudflare R2).

Public URL shape (legacy tenant, e.g. t1):
    {ICEBERG_CDN_BASE}/{ICEBERG_TENANT_SEGMENT}/{key}

Public URL shape (current Iceberg tenants):
    {ICEBERG_CDN_BASE}/{StorageKey}   # StorageKey is "objects/{asset_id}"
    from the assets/complete response. New uploads must use that URL —
    the legacy segment/key path 404s on the new tenant.

Upload flow (bytes go directly to R2, not through the Iceberg API):
    1. POST {ICEBERG_API_BASE}/assets/init-upload   -> presigned R2 PUT URL
    2. PUT  <presigned URL> with the raw bytes
    3. POST {ICEBERG_API_BASE}/assets/complete      -> catalog row marked ready

All network calls are defensive: misconfiguration or upload failure logs a
warning and returns '' — the surrounding request/thread is never hard-blocked.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

USER_UPLOAD_ERROR = (
    "Something went wrong while saving your file. Please try again in a moment — "
    "lots of people are using the platform right now, and we're on it."
)

_TIMEOUT = 30


def _api_base():
    return (os.getenv('ICEBERG_API_BASE') or '').rstrip('/')


def _cdn_base():
    return (os.getenv('ICEBERG_CDN_BASE') or '').rstrip('/')


def _tenant_segment():
    return (os.getenv('ICEBERG_TENANT_SEGMENT') or '').strip('/')


def _token():
    return os.getenv('ICEBERG_API_TOKEN') or ''


def _auth_headers():
    return {'Authorization': f'Bearer {_token()}'}


def is_configured():
    """True when the token, API base, and CDN base are all set."""
    return bool(_token() and _api_base() and _cdn_base())


def public_url(key):
    """Build the legacy public CDN URL for a key (segment/key path)."""
    segment = _tenant_segment()
    if segment:
        return f'{_cdn_base()}/{segment}/{key}'
    return f'{_cdn_base()}/{key}'


def public_url_from_asset(payload, key):
    """Prefer Iceberg's StorageKey (objects/{id}); fall back to the legacy path."""
    storage_key = ((payload or {}).get('StorageKey') or (payload or {}).get('storage_key') or '').strip().lstrip('/')
    if storage_key:
        return f'{_cdn_base()}/{storage_key}'
    return public_url(key)


def key_from_url(url):
    """Extract the storage key from a CDN URL, or '' if it doesn't match.

    Understands both the legacy ``/{segment}/{key}`` URLs and the current
    ``/objects/{id}`` URLs (returns ``objects/{id}`` in that case).
    """
    if not url:
        return ''
    cdn = _cdn_base()
    if cdn and url.startswith(cdn + '/objects/'):
        return url[len(cdn) + 1:]
    prefix = public_url('')
    if prefix and url.startswith(prefix):
        return url[len(prefix):]
    return ''


def _init_upload(key, content_type):
    resp = requests.post(
        f'{_api_base()}/assets/init-upload',
        json={'key': key, 'content_type': content_type},
        headers=_auth_headers(),
        timeout=_TIMEOUT,
    )
    return resp


def upload_bytes(data, key, content_type):
    """
    Upload raw bytes to Iceberg under key; return the public URL or ''.

    Retries init-upload once after a delete when the key already exists
    (409 from an interrupted prior run).
    """
    if not is_configured():
        logger.warning('Iceberg is not configured; cannot upload %s', key)
        return ''
    try:
        resp = _init_upload(key, content_type)
        if resp.status_code == 409:
            delete(key)
            resp = _init_upload(key, content_type)
        if resp.status_code in (401, 403):
            logger.warning(
                'Iceberg auth failed (%s) for %s — check ICEBERG_API_TOKEN and restart the server',
                resp.status_code,
                key,
            )
            return ''
        resp.raise_for_status()
        upload_url = (resp.json() or {}).get('upload_url')
        if not upload_url:
            logger.warning('Iceberg init-upload returned no upload_url for %s', key)
            return ''

        put = requests.put(
            upload_url,
            data=data,
            headers={'Content-Type': content_type},
            timeout=max(_TIMEOUT, 120),
        )
        if put.status_code >= 500:
            # R2 occasionally returns a transient 502; one retry clears it.
            logger.warning('Iceberg PUT got %s for %s; retrying once', put.status_code, key)
            put = requests.put(
                upload_url,
                data=data,
                headers={'Content-Type': content_type},
                timeout=max(_TIMEOUT, 120),
            )
        put.raise_for_status()

        done = requests.post(
            f'{_api_base()}/assets/complete',
            json={'key': key},
            headers=_auth_headers(),
            timeout=_TIMEOUT,
        )
        done.raise_for_status()
        return public_url_from_asset(done.json() if done.content else {}, key)
    except Exception as e:
        logger.warning('Iceberg upload failed for %s: %s', key, e)
        return ''


def last_auth_error_hint():
    """Best-effort probe used by admin UI when uploads fail."""
    if not is_configured():
        return 'Iceberg is not configured (missing ICEBERG_API_BASE / ICEBERG_CDN_BASE / ICEBERG_API_TOKEN).'
    try:
        resp = requests.post(
            f'{_api_base()}/assets/init-upload',
            json={'key': '_auth_probe/ping.txt', 'content_type': 'text/plain'},
            headers=_auth_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code in (401, 403):
            return (
                f'Iceberg rejected the API token (HTTP {resp.status_code}). '
                'Check ICEBERG_API_TOKEN in .env and restart the Django server.'
            )
        if resp.status_code >= 400:
            return f'Iceberg init-upload failed (HTTP {resp.status_code}): {(resp.text or "")[:180]}'
    except Exception as e:
        return f'Could not reach Iceberg API: {e}'
    return ''


def upload_fileobj(fileobj, key, content_type):
    """Read a file-like object and upload it; return the public URL or ''."""
    try:
        data = fileobj.read()
    except Exception as e:
        logger.warning('Iceberg upload could not read fileobj for %s: %s', key, e)
        return ''
    return upload_bytes(data, key, content_type)


def delete(key):
    """Best-effort delete; returns True on success.

    ``key`` may be the original object key (``lesson_hero_images/...``) or a
    StorageKey (``objects/{id}``). Iceberg accepts the catalog key; for
    objects/ URLs we try the asset id as well.
    """
    if not is_configured() or not key:
        return False
    try:
        resp = requests.delete(
            f'{_api_base()}/assets/{key}',
            headers=_auth_headers(),
            timeout=_TIMEOUT,
        )
        if resp.ok:
            return True
        if key.startswith('objects/'):
            resp = requests.delete(
                f'{_api_base()}/assets/{key.split("/", 1)[1]}',
                headers=_auth_headers(),
                timeout=_TIMEOUT,
            )
            return resp.ok
        return False
    except Exception as e:
        logger.warning('Iceberg delete failed for %s: %s', key, e)
        return False
