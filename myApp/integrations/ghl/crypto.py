"""Symmetric encryption for GHL OAuth tokens at rest.

Tokens are stored encrypted in the DB. We use Fernet (AES-128-CBC + HMAC).
The key comes from ``GHL_TOKEN_ENCRYPTION_KEY`` when set; otherwise we derive a
stable key from ``SECRET_KEY`` so the feature works without extra setup. For
production you should set a dedicated ``GHL_TOKEN_ENCRYPTION_KEY`` (a urlsafe
base64 32-byte key, e.g. ``Fernet.generate_key()``) so rotating Django's
SECRET_KEY does not orphan stored tokens.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _build_fernet():
    raw = (os.getenv("GHL_TOKEN_ENCRYPTION_KEY") or "").strip()
    if raw:
        # Accept either a ready Fernet key or arbitrary string we normalize.
        try:
            return Fernet(raw.encode())
        except (ValueError, TypeError):
            digest = hashlib.sha256(raw.encode()).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
    # Fallback: derive deterministically from SECRET_KEY.
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    """Encrypt a token string -> opaque ascii ciphertext (or '' for empty)."""
    if not plaintext:
        return ""
    token = _build_fernet().encrypt(plaintext.encode())
    return token.decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt ciphertext -> plaintext. Returns '' on empty/tampered input."""
    if not ciphertext:
        return ""
    try:
        return _build_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return ""
