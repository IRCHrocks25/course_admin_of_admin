"""Signed OAuth ``state`` token.

The OAuth redirect URI is a SINGLE central endpoint shared by every tenant, so
the callback cannot learn the tenant from the host. We carry tenant identity in
the ``state`` param instead: a signed, timestamped token that encodes
``tenant_id`` plus a random nonce. Validating it on the callback both resolves
the tenant AND serves as our CSRF defense (an attacker cannot forge a valid
signature without SECRET_KEY).

We sign with django.core.signing (SECRET_KEY + a dedicated salt) rather than the
session, because connect happens on the tenant's domain while the callback lands
on the central platform domain — they don't share a session cookie.
"""
from django.core import signing
from django.utils.crypto import get_random_string

_SALT = "ghl.oauth.state.v1"
# State is short-lived: the user goes straight from connect -> GHL -> callback.
MAX_AGE_SECONDS = 600


def encode(tenant_id: int, return_to: str = "") -> str:
    payload = {
        "t": int(tenant_id),
        "n": get_random_string(16),
        "r": return_to or "",
    }
    return signing.dumps(payload, salt=_SALT, compress=True)


def decode(state: str) -> dict:
    """Return the validated payload dict.

    Raises ``signing.BadSignature`` (incl. ``SignatureExpired``) if the token is
    forged, tampered, or older than MAX_AGE_SECONDS. Callers MUST treat any
    exception as a rejected callback.
    """
    return signing.loads(state, salt=_SALT, max_age=MAX_AGE_SECONDS)
