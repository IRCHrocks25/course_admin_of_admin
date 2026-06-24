"""One-time, short-lived token to carry an authenticated identity from the
platform-host /leadconnector/embed view to the tenant-host /leadconnector/sso view."""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core import signing
from django.core.cache import cache

_SALT = "ghl.embed.sso.v1"


class SsoError(Exception):
    pass


def _ttl() -> int:
    return int(getattr(settings, "GHL_SSO_TTL_SECONDS", 60))


def issue(user_id: int, tenant_id: int, embed_session_id: int) -> str:
    jti = uuid.uuid4().hex
    return signing.dumps(
        {"u": user_id, "t": tenant_id, "e": embed_session_id, "j": jti},
        salt=_SALT,
    )


def consume(token: str) -> dict:
    """Validate signature + TTL, enforce single use. Returns {u,t,e}."""
    try:
        data = signing.loads(token, salt=_SALT, max_age=_ttl())
    except signing.BadSignature as exc:
        raise SsoError("invalid or expired token") from exc
    jti = data.get("j")
    if not jti or not cache.add(f"ghl:sso:{jti}", "1", timeout=max(_ttl() * 2, 120)):
        raise SsoError("token already used")
    return {"u": data["u"], "t": data["t"], "e": data["e"]}
