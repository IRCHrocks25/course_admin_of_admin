"""Decrypt GoHighLevel Custom Page 'User Context' blobs.

GHL encrypts the context with CryptoJS AES.encrypt(JSON, sharedSecret), which
emits the OpenSSL "Salted__" envelope: base64( b"Salted__" + 8-byte salt +
AES-256-CBC ciphertext ), with key+iv derived via EVP_BytesToKey using MD5.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


@dataclass
class GhlUserContext:
    location_id: str = ""
    user_id: str = ""
    company_id: str = ""
    user_type: str = ""
    user_name: str = ""
    email: str = ""
    role: str = ""
    type: str = ""


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16):
    d = b""
    prev = b""
    while len(d) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        d += prev
    return d[:key_len], d[key_len : key_len + iv_len]


def decrypt(blob: str, secret: str) -> Optional[GhlUserContext]:
    """Return a GhlUserContext, or None on any failure (soft-fail)."""
    if not blob or not secret:
        return None
    try:
        raw = base64.b64decode(blob)
        if raw[:8] != b"Salted__":
            return None
        salt, ct = raw[8:16], raw[16:]
        key, iv = _evp_bytes_to_key(secret.encode(), salt)
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = dec.update(ct) + dec.finalize()
        pad = padded[-1]
        if pad < 1 or pad > 16:
            return None
        data = json.loads(padded[:-pad].decode("utf-8"))
        if not isinstance(data, dict):
            return None
    except Exception:
        return None
    return GhlUserContext(
        location_id=str(data.get("locationId") or "").strip(),
        user_id=str(data.get("userId") or "").strip(),
        company_id=str(data.get("companyId") or "").strip(),
        user_type=str(data.get("userType") or "").strip(),
        user_name=str(data.get("userName") or "").strip(),
        email=str(data.get("email") or "").strip(),
        role=str(data.get("role") or "").strip(),
        type=str(data.get("type") or "").strip(),
    )
