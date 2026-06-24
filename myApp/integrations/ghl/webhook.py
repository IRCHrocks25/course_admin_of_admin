"""Verify GoHighLevel webhook signatures (Ed25519 over the raw request body)."""
from __future__ import annotations

import base64

from django.conf import settings
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    load_der_public_key,
    load_pem_public_key,
)


def _load_public_key():
    raw = (settings.GHL_WEBHOOK_PUBLIC_KEY or "").strip()
    if not raw:
        return None
    if "BEGIN PUBLIC KEY" in raw:
        return load_pem_public_key(raw.encode())
    return load_der_public_key(base64.b64decode(raw))


def verify(raw_body: bytes, signature_b64: str) -> bool:
    """True iff signature is a valid Ed25519 signature of raw_body."""
    try:
        key = _load_public_key()
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(base64.b64decode(signature_b64), raw_body)
        return True
    except Exception:
        return False
