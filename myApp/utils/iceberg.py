"""
Iceberg CDN client (self-hosted CDN on Cloudflare R2).

Public URL shape:
    {ICEBERG_CDN_BASE}/{ICEBERG_TENANT_SEGMENT}/{key}

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
    """Build the public CDN URL for a key."""
    segment = _tenant_segment()
    if segment:
        return f'{_cdn_base()}/{segment}/{key}'
    return f'{_cdn_base()}/{key}'


def key_from_url(url):
    """Extract the storage key from a CDN URL, or '' if it doesn't match."""
    prefix = public_url('')
    if url and prefix and url.startswith(prefix):
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
        return public_url(key)
    except Exception as e:
        logger.warning('Iceberg upload failed for %s: %s', key, e)
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
    """Best-effort delete; returns True on success."""
    if not is_configured():
        return False
    try:
        resp = requests.delete(
            f'{_api_base()}/assets/{key}',
            headers=_auth_headers(),
            timeout=_TIMEOUT,
        )
        return resp.ok
    except Exception as e:
        logger.warning('Iceberg delete failed for %s: %s', key, e)
        return False
