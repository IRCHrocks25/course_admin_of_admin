"""GHL OAuth 2.0 service (V2 / LeadConnector).

Responsibilities:
  * build the authorize URL (with signed state),
  * exchange an authorization code for tokens,
  * refresh access tokens with SINGLE-USE refresh-token rotation under a
    per-tenant lock,
  * exchange an agency (Company) token for a location-scoped token.

GHL refresh tokens are single-use: every refresh returns a NEW refresh_token and
invalidates the old one. If two workers refresh concurrently, one wins and the
other's token becomes invalid (invalid_grant), breaking the connection. We guard
the whole read-refresh-persist cycle with ``select_for_update`` on the
connection row so only one worker rotates at a time and the new token is
persisted atomically.
"""
import logging
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.db import transaction
from django.utils import timezone

from . import config

logger = logging.getLogger("myApp.ghl")

# Refresh a little before the ~24h access token actually expires.
REFRESH_SKEW_SECONDS = 600
_HTTP_TIMEOUT = 20


class GHLOAuthError(Exception):
    """Raised when a token mint/refresh/exchange call fails."""


# ─── Authorize ───

def build_authorize_url(state: str) -> str:
    """Build the GHL consent URL the admin is redirected to."""
    client_id = config.client_id()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": config.redirect_uri(),
        "scope": config.scopes(),
        "state": state,
    }
    # GHL pins the install to a specific app version; version_id is the client_id
    # prefix before the '-' (matches GHL's own whitelabel install link).
    if "-" in client_id:
        params["version_id"] = client_id.split("-", 1)[0]
    return f"{config.AUTHORIZE_URL}?{urlencode(params)}"


# ─── Token calls ───

def _post_token(data: dict) -> dict:
    data = {
        "client_id": config.client_id(),
        "client_secret": config.client_secret(),
        "user_type": config.USER_TYPE,
        **data,
    }
    try:
        resp = requests.post(
            config.TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GHLOAuthError(f"token request failed: {exc}") from exc

    if resp.status_code != 200:
        # Never log the body verbatim at info level (may echo secrets); keep it
        # to the error channel and trim.
        logger.error("GHL token call %s -> %s: %s", data.get("grant_type"),
                     resp.status_code, resp.text[:500])
        raise GHLOAuthError(f"token call returned {resp.status_code}")
    return resp.json()


def exchange_code(code: str) -> dict:
    """Exchange an authorization code for the initial token set.

    Returns the raw GHL token payload (access_token, refresh_token, expires_in,
    locationId, companyId, scope, ...).
    """
    payload = _post_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri(),
    })
    if not payload.get("access_token"):
        raise GHLOAuthError("token payload missing access_token")
    return payload


def get_location_token(company_access_token: str, company_id: str, location_id: str) -> dict:
    """Agency->location exchange.

    When an install yields a Company (agency) token, sub-account endpoints need a
    location-scoped token. POST /oauth/locationToken with the company token.
    """
    try:
        resp = requests.post(
            config.LOCATION_TOKEN_URL,
            data={"companyId": company_id, "locationId": location_id},
            headers={
                "Authorization": f"Bearer {company_access_token}",
                "Version": config.API_VERSION,
                "Accept": "application/json",
            },
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GHLOAuthError(f"locationToken request failed: {exc}") from exc

    if resp.status_code != 200:
        logger.error("GHL locationToken -> %s: %s", resp.status_code, resp.text[:500])
        raise GHLOAuthError(f"locationToken returned {resp.status_code}")
    return resp.json()


# ─── Refresh with single-use rotation under a per-tenant lock ───

def refresh_connection(connection_id: int):
    """Refresh one connection's access token, rotating the refresh token.

    Locks the connection row for the duration so concurrent workers serialize
    and we never spend an already-rotated refresh token. Returns the refreshed
    connection, or None if it could not be refreshed (and marks it errored).
    """
    from ...models import GHLConnection

    with transaction.atomic():
        try:
            conn = (
                GHLConnection.objects
                .select_for_update()
                .get(pk=connection_id)
            )
        except GHLConnection.DoesNotExist:
            return None

        refresh_token = conn.get_refresh_token()
        if not refresh_token:
            conn.mark_error("missing refresh token")
            conn.save(update_fields=["sync_status", "status_detail", "updated_at"])
            return None

        try:
            payload = _post_token({
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            })
        except GHLOAuthError as exc:
            conn.mark_error(str(exc)[:250])
            conn.save(update_fields=["sync_status", "status_detail", "updated_at"])
            return None

        conn.apply_token_payload(payload)
        conn.save()
        return conn


def needs_refresh(connection) -> bool:
    if connection.token_expires_at is None:
        return True
    return timezone.now() >= connection.token_expires_at - timedelta(seconds=REFRESH_SKEW_SECONDS)
