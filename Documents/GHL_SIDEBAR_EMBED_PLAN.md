# CourseForge GHL Sidebar Embed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CourseForge appear in the GoHighLevel sidebar as a Custom Page that auto-logs the GHL user into their tenant's academy, via our own marketplace app, with rich-scope connect, contact webhooks, and an impersonation audit trail.

**Architecture:** Finish the existing `myApp/integrations/ghl/` OAuth scaffold by adding a platform-host embed entry (`/ghl/embed`) that decrypts GHL's User Context, resolves tenant via the unique `GHLConnection.ghl_location_id`, then hops to the tenant host (`/ghl/sso`) where a one-time token establishes an iframe-safe session and renders the existing dashboard. A frame-policy middleware allows GHL to iframe embed sessions. An Ed25519-verified `/ghl/webhook` ingests Contact events.

**Tech Stack:** Django 5.x, `cryptography` (already a dep, used by Fernet), Django `signing` + cache, GHL/LeadConnector marketplace app. Tests via `python manage.py test`.

**Spec:** `Documents/GHL_SIDEBAR_EMBED_DESIGN.md`

---

## File Structure

**New files**
- `myApp/integrations/ghl/user_context.py` — decrypt GHL Custom Page User Context (AES-256-CBC / CryptoJS).
- `myApp/integrations/ghl/sso.py` — one-time cross-host login token.
- `myApp/integrations/ghl/webhook.py` — Ed25519 webhook signature verification.
- `myApp/integrations/ghl/embed.py` — user resolution + audit helper (keeps views thin).
- `myApp/templates/ghl/embed_unauthorized.html`, `embed_not_connected.html`, `embed_error.html`.
- `myApp/tests/test_ghl_user_context.py`, `test_ghl_sso.py`, `test_ghl_webhook.py`, `test_ghl_embed.py`, `test_ghl_frame.py`.
- Migration `myApp/migrations/00XX_ghlembedsession.py` (generated).

**Modified files**
- `myProject/settings.py` — new env vars, MIDDLEWARE entry, session cookie flags.
- `myProject/urls.py` — `/ghl/embed`, `/ghl/sso`, `/ghl/webhook`.
- `myApp/middleware.py` — `GhlEmbedFrameMiddleware`.
- `myApp/ghl_views.py` — `ghl_embed`, `ghl_sso`, `ghl_webhook`; harden `ghl_callback`.
- `myApp/models_ghl.py` — `GhlEmbedSession`.
- `myApp/integrations/ghl/config.py` — rich `DEFAULT_GHL_SCOPES`.
- `.env.example` — new vars.

---

## Task 0: Feature branch + local dev prerequisites

**Files:** none (environment setup)

- [ ] **Step 1: Create a feature branch in the CourseForge repo**

```bash
cd /home/bernardjr/Desktop/Code/work/katalyst-ai/admin-of-admin/course_admin_of_admin
git checkout -b feat/ghl-sidebar-embed
```

- [ ] **Step 2: Confirm test runner works on a clean checkout**

Run: `python manage.py test myApp.tests -v 1`
Expected: existing tests pass (or collect with no import errors).

- [ ] **Step 3: Register a DEV marketplace app + start an HTTPS tunnel** (manual, no commit)

- Start the app locally and expose it over HTTPS (e.g. `cloudflared tunnel --url http://localhost:8000` or ngrok). Note the HTTPS URL `<TUNNEL>`.
- In the GHL marketplace, create a **new** app (Sub-Account distribution) with:
  - Redirect URI: `<TUNNEL>/ghl/callback`
  - Custom Page URL: `<TUNNEL>/ghl/embed`
  - Webhook URL: `<TUNNEL>/ghl/webhook`
- Record `client_id`, `client_secret`, and the **Shared Secret** (Advanced Settings → Auth) for `.env`.
- Note: embed requires `Secure` cookies → must test via the **HTTPS tunnel**, not plain `http://localhost`.

---

## Task 1: Settings + env vars

**Files:**
- Modify: `myProject/settings.py` (GHL settings block, ~292–305)
- Modify: `.env.example` (GHL block, ~65–80)

- [ ] **Step 1: Add new settings**

In `myProject/settings.py`, after the existing GHL settings block, add:

```python
# GHL Custom Page (sidebar embed)
GHL_SHARED_SECRET_KEY = os.getenv("GHL_SHARED_SECRET_KEY", "").strip()
GHL_EMBED_FRAME_ANCESTORS = os.getenv(
    "GHL_EMBED_FRAME_ANCESTORS",
    "https://*.gohighlevel.com https://*.leadconnectorhq.com",
).strip()
GHL_EMBED_FRAME_ANCESTORS_CSP = f"frame-ancestors 'self' {GHL_EMBED_FRAME_ANCESTORS}"
# Tenant-host override for local dev (e.g. "lvh.me:8000"); blank in prod.
GHL_EMBED_HOST_OVERRIDE = os.getenv("GHL_EMBED_HOST_OVERRIDE", "").strip()
GHL_SSO_TTL_SECONDS = int(os.getenv("GHL_SSO_TTL_SECONDS", "60"))
```

- [ ] **Step 2: Make embed session cookies iframe-compatible**

In `myProject/settings.py`, add (or set) near other session config:

```python
# Required so the session cookie survives inside the GHL third-party iframe.
SESSION_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SECURE = True
```

> Trade-off (documented in spec §8): this relaxes SameSite globally to None; acceptable because all envs are HTTPS. `Partitioned` (CHIPS) is appended for embed responses in Task 5.

- [ ] **Step 3: Document the vars in `.env.example`**

Add under the GHL block:

```
# GHL Custom Page User-Context decryption (HL marketplace → Advanced Settings → Auth)
GHL_SHARED_SECRET_KEY=
# Space-separated origins allowed to iframe the embed (default = GHL domains)
GHL_EMBED_FRAME_ANCESTORS=https://*.gohighlevel.com https://*.leadconnectorhq.com
# Local dev only: tenant host override, e.g. lvh.me:8000
GHL_EMBED_HOST_OVERRIDE=
GHL_SSO_TTL_SECONDS=60
```

- [ ] **Step 4: Commit**

```bash
git add myProject/settings.py .env.example
git commit -m "feat(ghl): add embed settings + env vars"
```

---

## Task 2: User-Context decryptor

**Files:**
- Create: `myApp/integrations/ghl/user_context.py`
- Test: `myApp/tests/test_ghl_user_context.py`

- [ ] **Step 1: Write the failing test**

```python
# myApp/tests/test_ghl_user_context.py
import base64
import hashlib
import json
from django.test import SimpleTestCase
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from myApp.integrations.ghl import user_context


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len=32, iv_len=16):
    d = b""
    prev = b""
    while len(d) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        d += prev
    return d[:key_len], d[key_len : key_len + iv_len]


def _cryptojs_encrypt(plaintext: str, secret: str) -> str:
    """Mirror CryptoJS AES.encrypt(str, passphrase) → OpenSSL Salted__ format."""
    salt = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    key, iv = _evp_bytes_to_key(secret.encode(), salt)
    data = plaintext.encode("utf-8")
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(b"Salted__" + salt + ct).decode()


class UserContextTests(SimpleTestCase):
    SECRET = "test-shared-secret"

    def test_decrypts_valid_blob(self):
        payload = {"locationId": "LOC123", "email": "a@b.com", "type": "location"}
        blob = _cryptojs_encrypt(json.dumps(payload), self.SECRET)
        ctx = user_context.decrypt(blob, self.SECRET)
        self.assertEqual(ctx.location_id, "LOC123")
        self.assertEqual(ctx.email, "a@b.com")

    def test_tampered_blob_returns_none(self):
        self.assertIsNone(user_context.decrypt("not-base64!!", self.SECRET))

    def test_wrong_secret_returns_none(self):
        blob = _cryptojs_encrypt('{"locationId":"X"}', self.SECRET)
        self.assertIsNone(user_context.decrypt(blob, "wrong-secret"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_user_context -v 2`
Expected: FAIL — `ModuleNotFoundError: myApp.integrations.ghl.user_context`.

- [ ] **Step 3: Write the implementation**

```python
# myApp/integrations/ghl/user_context.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_user_context -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add myApp/integrations/ghl/user_context.py myApp/tests/test_ghl_user_context.py
git commit -m "feat(ghl): add Custom Page user-context decryptor"
```

---

## Task 3: One-time SSO token

**Files:**
- Create: `myApp/integrations/ghl/sso.py`
- Test: `myApp/tests/test_ghl_sso.py`

- [ ] **Step 1: Write the failing test**

```python
# myApp/tests/test_ghl_sso.py
import time
from django.test import SimpleTestCase, override_settings
from django.core.cache import cache

from myApp.integrations.ghl import sso


class SsoTokenTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_roundtrip(self):
        token = sso.issue(user_id=7, tenant_id=3, embed_session_id=99)
        data = sso.consume(token)
        self.assertEqual(data, {"u": 7, "t": 3, "e": 99})

    def test_single_use(self):
        token = sso.issue(user_id=7, tenant_id=3, embed_session_id=99)
        sso.consume(token)
        with self.assertRaises(sso.SsoError):
            sso.consume(token)

    @override_settings(GHL_SSO_TTL_SECONDS=0)
    def test_expired(self):
        token = sso.issue(user_id=7, tenant_id=3, embed_session_id=99)
        time.sleep(1)
        with self.assertRaises(sso.SsoError):
            sso.consume(token)

    def test_tampered(self):
        with self.assertRaises(sso.SsoError):
            sso.consume("garbage.token.value")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_sso -v 2`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# myApp/integrations/ghl/sso.py
"""One-time, short-lived token to carry an authenticated identity from the
platform-host /ghl/embed view to the tenant-host /ghl/sso view."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_sso -v 2`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add myApp/integrations/ghl/sso.py myApp/tests/test_ghl_sso.py
git commit -m "feat(ghl): add one-time SSO token for cross-host embed login"
```

---

## Task 4: GhlEmbedSession audit model

**Files:**
- Modify: `myApp/models_ghl.py` (append)
- Test: `myApp/tests/test_ghl_embed.py` (model portion)

- [ ] **Step 1: Write the failing test**

```python
# myApp/tests/test_ghl_embed.py
from django.test import TestCase
from myApp.models import Tenant
from myApp.models_ghl import GhlEmbedSession


class GhlEmbedSessionModelTests(TestCase):
    def test_create_audit_row(self):
        tenant = Tenant.objects.create(name="NCD", slug="ncd")
        row = GhlEmbedSession.objects.create(
            tenant=tenant,
            ghl_location_id="LOC123",
            ghl_email="user@ncd.com",
            impersonated_owner=True,
        )
        self.assertTrue(row.impersonated_owner)
        self.assertEqual(row.tenant, tenant)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_embed.GhlEmbedSessionModelTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'GhlEmbedSession'`.

- [ ] **Step 3: Append the model to `myApp/models_ghl.py`**

```python
class GhlEmbedSession(models.Model):
    """Audit trail for GHL sidebar auto-logins. Captures the real GHL identity
    behind each embed login so owner-fallback impersonations are attributable."""

    tenant = models.ForeignKey("myApp.Tenant", on_delete=models.CASCADE, related_name="ghl_embed_sessions")
    connection = models.ForeignKey("myApp.GHLConnection", on_delete=models.SET_NULL, null=True, blank=True)
    ghl_location_id = models.CharField(max_length=128, blank=True, default="")
    ghl_user_id = models.CharField(max_length=128, blank=True, default="")
    ghl_email = models.CharField(max_length=255, blank=True, default="")
    ghl_user_name = models.CharField(max_length=255, blank=True, default="")
    ghl_role = models.CharField(max_length=64, blank=True, default="")
    ghl_user_type = models.CharField(max_length=64, blank=True, default="")
    resolved_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    impersonated_owner = models.BooleanField(default=False)
    django_session_key = models.CharField(max_length=64, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["ghl_location_id"]),
        ]

    def __str__(self):
        return f"GhlEmbedSession(t={self.tenant_id}, loc={self.ghl_location_id}, owner={self.impersonated_owner})"
```

Ensure the top of `models_ghl.py` imports settings: `from django.conf import settings` (add if absent).

- [ ] **Step 4: Generate + run the migration**

Run: `python manage.py makemigrations myApp && python manage.py test myApp.tests.test_ghl_embed.GhlEmbedSessionModelTests -v 2`
Expected: migration created; test PASS.

- [ ] **Step 5: Commit**

```bash
git add myApp/models_ghl.py myApp/migrations/00*_ghlembedsession*.py myApp/tests/test_ghl_embed.py
git commit -m "feat(ghl): add GhlEmbedSession audit model + migration"
```

---

## Task 5: Embed frame-policy middleware

**Files:**
- Modify: `myApp/middleware.py` (append class)
- Modify: `myProject/settings.py` (MIDDLEWARE list)
- Test: `myApp/tests/test_ghl_frame.py`

- [ ] **Step 1: Write the failing test**

```python
# myApp/tests/test_ghl_frame.py
from django.test import TestCase, RequestFactory
from django.http import HttpResponse
from myApp.middleware import GhlEmbedFrameMiddleware


class FrameMiddlewareTests(TestCase):
    def _run(self, path, session=None):
        rf = RequestFactory()
        req = rf.get(path)
        req.session = session or {}
        mw = GhlEmbedFrameMiddleware(lambda r: HttpResponse("ok", headers={"X-Frame-Options": "DENY"}))
        return mw(req)

    def test_embed_path_sets_csp_and_drops_xfo(self):
        resp = self._run("/ghl/embed")
        self.assertIn("frame-ancestors", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("X-Frame-Options", resp.headers)

    def test_embed_session_dashboard_allows_frame(self):
        resp = self._run("/dashboard/", session={"ghl_embed": True})
        self.assertIn("leadconnectorhq.com", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("X-Frame-Options", resp.headers)

    def test_non_embed_keeps_deny(self):
        resp = self._run("/dashboard/")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_frame -v 2`
Expected: FAIL — `ImportError: cannot import name 'GhlEmbedFrameMiddleware'`.

- [ ] **Step 3: Append the middleware to `myApp/middleware.py`**

```python
class GhlEmbedFrameMiddleware:
    """Allow GHL to iframe embed responses; everyone else keeps X-Frame-Options.

    Applies to the /ghl/embed and /ghl/sso routes and to any request whose
    session is flagged ghl_embed=True (the dashboard inside the GHL iframe).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _is_embed(self, request):
        path = request.path or ""
        if path.startswith("/ghl/embed") or path.startswith("/ghl/sso"):
            return True
        session = getattr(request, "session", None)
        return bool(session and session.get("ghl_embed"))

    def __call__(self, request):
        response = self.get_response(request)
        if not self._is_embed(request):
            return response

        from django.conf import settings

        response.headers["Content-Security-Policy"] = settings.GHL_EMBED_FRAME_ANCESTORS_CSP
        response.headers.pop("X-Frame-Options", None)

        # Make the session cookie usable in a third-party iframe (CHIPS).
        morsel = response.cookies.get(settings.SESSION_COOKIE_NAME)
        if morsel is not None:
            morsel["samesite"] = "None"
            morsel["secure"] = True
            try:
                morsel["partitioned"] = True  # Python 3.14+ http.cookies
            except Exception:
                # Older Python: append manually so Chrome accepts the cookie.
                if "; Partitioned" not in morsel.OutputString():
                    morsel._reserved.setdefault("partitioned", "Partitioned")
                    morsel.__setitem__("partitioned", True)
        return response
```

> Note: `morsel._reserved` is a documented attribute of `http.cookies.Morsel`. If the running Python rejects the `partitioned` key entirely, fall back to a WSGI header rewrite (flagged in spec §13); verify which path your Python needs during this task.

- [ ] **Step 4: Register the middleware**

In `myProject/settings.py`, add to `MIDDLEWARE` immediately after `XFrameOptionsMiddleware`:

```python
    "myApp.middleware.GhlEmbedFrameMiddleware",
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_frame -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add myApp/middleware.py myProject/settings.py myApp/tests/test_ghl_frame.py
git commit -m "feat(ghl): add embed frame-policy middleware"
```

---

## Task 6: Embed user-resolution + audit helper

**Files:**
- Create: `myApp/integrations/ghl/embed.py`
- Test: `myApp/tests/test_ghl_embed.py` (resolution portion — append)

- [ ] **Step 1: Append the failing test**

```python
# append to myApp/tests/test_ghl_embed.py
from django.contrib.auth import get_user_model
from myApp.models import TenantMembership
from myApp.integrations.ghl import embed as embed_helper
from myApp.integrations.ghl.user_context import GhlUserContext

User = get_user_model()


class ResolveEmbedUserTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")
        self.owner = User.objects.create_user(username="owner", email="owner@ncd.com", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.owner, role="tenant_admin", is_active=True)
        self.member = User.objects.create_user(username="mem", email="mem@ncd.com", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.member, role="tenant_admin", is_active=True)

    def test_email_match_uses_member(self):
        ctx = GhlUserContext(location_id="L", email="mem@ncd.com")
        user, impersonated = embed_helper.resolve_user(self.tenant, ctx)
        self.assertEqual(user, self.member)
        self.assertFalse(impersonated)

    def test_no_match_falls_back_to_owner(self):
        ctx = GhlUserContext(location_id="L", email="stranger@x.com")
        user, impersonated = embed_helper.resolve_user(self.tenant, ctx)
        self.assertEqual(user, self.owner)
        self.assertTrue(impersonated)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_embed.ResolveEmbedUserTests -v 2`
Expected: FAIL — module not found.

> If `TenantMembership` field names differ from `(tenant, user, role, is_active)`, adjust the test setup AND the query in Step 3 to match the real model (verify in `myApp/models.py`).

- [ ] **Step 3: Write the helper**

```python
# myApp/integrations/ghl/embed.py
"""Resolve which CourseForge user a GHL sidebar visitor logs in as, and write
the audit row. Policy: email-match an active tenant admin, else owner fallback."""
from __future__ import annotations

from typing import Optional, Tuple

from myApp.models import TenantMembership
from myApp.models_ghl import GhlEmbedSession
from .user_context import GhlUserContext


def _tenant_owner(tenant):
    """Primary admin = earliest active tenant_admin membership."""
    membership = (
        TenantMembership.objects.filter(tenant=tenant, role="tenant_admin", is_active=True)
        .order_by("id")
        .select_related("user")
        .first()
    )
    return membership.user if membership else None


def resolve_user(tenant, ctx: GhlUserContext) -> Tuple[Optional[object], bool]:
    """Return (user, impersonated_owner)."""
    if ctx.email:
        membership = (
            TenantMembership.objects.filter(
                tenant=tenant, is_active=True, user__email__iexact=ctx.email
            )
            .select_related("user")
            .first()
        )
        if membership:
            return membership.user, False
    return _tenant_owner(tenant), True


def record_session(*, tenant, connection, ctx: GhlUserContext, user, impersonated, request) -> GhlEmbedSession:
    return GhlEmbedSession.objects.create(
        tenant=tenant,
        connection=connection,
        ghl_location_id=ctx.location_id,
        ghl_user_id=ctx.user_id,
        ghl_email=ctx.email,
        ghl_user_name=ctx.user_name,
        ghl_role=ctx.role,
        ghl_user_type=ctx.user_type or ctx.type,
        resolved_user=user,
        impersonated_owner=impersonated,
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_embed.ResolveEmbedUserTests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add myApp/integrations/ghl/embed.py myApp/tests/test_ghl_embed.py
git commit -m "feat(ghl): add embed user-resolution + audit helper"
```

---

## Task 7: Embed templates

**Files:**
- Create: `myApp/templates/ghl/embed_unauthorized.html`, `embed_not_connected.html`, `embed_error.html`

- [ ] **Step 1: Create the three templates**

`myApp/templates/ghl/embed_unauthorized.html`:
```html
{% load static %}<!doctype html><html><head><meta charset="utf-8">
<title>CourseForge</title><meta name="robots" content="noindex,nofollow"></head>
<body style="font-family:system-ui;padding:2rem;text-align:center">
<h2>Open from a sub-account</h2>
<p>This page must be opened from inside a GoHighLevel sub-account.</p>
</body></html>
```

`myApp/templates/ghl/embed_not_connected.html`:
```html
{% load static %}<!doctype html><html><head><meta charset="utf-8">
<title>CourseForge</title><meta name="robots" content="noindex,nofollow"></head>
<body style="font-family:system-ui;padding:2rem;text-align:center">
<h2>Academy not connected</h2>
<p>Connect your CourseForge academy to GoHighLevel first, then reopen this page.</p>
</body></html>
```

`myApp/templates/ghl/embed_error.html`:
```html
{% load static %}<!doctype html><html><head><meta charset="utf-8">
<title>CourseForge</title><meta name="robots" content="noindex,nofollow"></head>
<body style="font-family:system-ui;padding:2rem;text-align:center">
<h2>Session expired</h2>
<p>Please reopen the CourseForge page from the GoHighLevel sidebar.</p>
</body></html>
```

- [ ] **Step 2: Commit**

```bash
git add myApp/templates/ghl/
git commit -m "feat(ghl): add embed status templates"
```

---

## Task 8: Embed + SSO views

**Files:**
- Modify: `myApp/ghl_views.py` (append `ghl_embed`, `ghl_sso`)
- Test: `myApp/tests/test_ghl_embed.py` (view portion — append)

- [ ] **Step 1: Append the failing test**

```python
# append to myApp/tests/test_ghl_embed.py
from django.urls import reverse
from django.test import Client, override_settings
from myApp.models_ghl import GHLConnection
from myApp.tests.test_ghl_user_context import _cryptojs_encrypt
import json

SECRET = "embed-secret"


@override_settings(GHL_SHARED_SECRET_KEY=SECRET, ALLOW_ALL_HOSTS=True)
class EmbedViewTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")
        owner = User.objects.create_user(username="o", email="o@ncd.com", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=owner, role="tenant_admin", is_active=True)
        GHLConnection.objects.create(tenant=self.tenant, ghl_location_id="LOC123")
        self.client = Client()

    def _blob(self, payload):
        return _cryptojs_encrypt(json.dumps(payload), SECRET)

    def test_missing_blob_renders_unauthorized(self):
        resp = self.client.get("/ghl/embed")
        self.assertContains(resp, "Open from a sub-account", status_code=200)

    def test_unknown_location_renders_not_connected(self):
        resp = self.client.get("/ghl/embed", {"encryptedUserData": self._blob({"locationId": "NOPE"})})
        self.assertContains(resp, "not connected", status_code=200)

    def test_known_location_redirects_to_sso(self):
        resp = self.client.get("/ghl/embed", {"encryptedUserData": self._blob({"locationId": "LOC123", "email": "o@ncd.com"})})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/ghl/sso", resp["Location"])
        self.assertEqual(GhlEmbedSession.objects.count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_embed.EmbedViewTests -v 2`
Expected: FAIL — 404 (routes not added yet) / view missing.

- [ ] **Step 3: Append the views to `myApp/ghl_views.py`**

```python
from django.conf import settings
from django.contrib.auth import login as auth_login
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from myApp.models_ghl import GHLConnection
from myApp.integrations.ghl import user_context, sso
from myApp.integrations.ghl import embed as ghl_embed_helper
from myApp.integrations.ghl import config as ghl_config


def _tenant_host(tenant):
    override = getattr(settings, "GHL_EMBED_HOST_OVERRIDE", "").strip()
    base = override or getattr(settings, "PLATFORM_BASE_DOMAIN", "").strip()
    if getattr(tenant, "custom_domain", "") :
        return tenant.custom_domain
    if base:
        return f"{tenant.slug}.{base}"
    return ""


@csrf_exempt
@xframe_options_exempt
@require_http_methods(["GET"])
def ghl_embed(request):
    blob = request.GET.get("encryptedUserData") or request.GET.get("userData") or ""
    ctx = user_context.decrypt(blob, settings.GHL_SHARED_SECRET_KEY)
    if not ctx or not ctx.location_id or (ctx.type or "").lower() == "agency":
        return render(request, "ghl/embed_unauthorized.html")

    connection = (
        GHLConnection.objects.select_related("tenant")
        .filter(ghl_location_id=ctx.location_id)
        .first()
    )
    if not connection:
        return render(request, "ghl/embed_not_connected.html")

    tenant = connection.tenant
    user, impersonated = ghl_embed_helper.resolve_user(tenant, ctx)
    if user is None:
        return render(request, "ghl/embed_not_connected.html")

    audit = ghl_embed_helper.record_session(
        tenant=tenant, connection=connection, ctx=ctx,
        user=user, impersonated=impersonated, request=request,
    )

    token = sso.issue(user_id=user.id, tenant_id=tenant.id, embed_session_id=audit.id)
    host = _tenant_host(tenant)
    scheme = "http" if getattr(settings, "GHL_EMBED_HOST_OVERRIDE", "") else "https"
    return redirect(f"{scheme}://{host}/ghl/sso?t={token}&next=/dashboard")


@xframe_options_exempt
@require_http_methods(["GET"])
def ghl_sso(request):
    token = request.GET.get("t", "")
    try:
        data = sso.consume(token)
    except sso.SsoError:
        return render(request, "ghl/embed_error.html", status=403)

    if not request.tenant or request.tenant.id != data["t"]:
        return render(request, "ghl/embed_error.html", status=403)

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(id=data["u"]).first()
    if not user:
        return render(request, "ghl/embed_error.html", status=403)

    auth_login(request, user)
    request.session["ghl_embed"] = True
    request.session["ghl_actor"] = {"embed_session_id": data["e"]}

    nxt = request.GET.get("next", "/dashboard")
    if not nxt.startswith("/"):
        nxt = "/dashboard"
    return redirect(nxt)
```

> If `auth_login` requires an explicit backend (multiple `AUTHENTICATION_BACKENDS`), pass `backend="django.contrib.auth.backends.ModelBackend"`. Verify during this task.

- [ ] **Step 4: Add routes** (covered fully in Task 11, but add now to make the test pass)

In `myProject/urls.py`, add:
```python
    path('ghl/embed', ghl_views.ghl_embed, name='ghl_embed'),
    path('ghl/sso', ghl_views.ghl_sso, name='ghl_sso'),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_embed.EmbedViewTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add myApp/ghl_views.py myProject/urls.py myApp/tests/test_ghl_embed.py
git commit -m "feat(ghl): add /ghl/embed + /ghl/sso views"
```

---

## Task 9: Webhook signature verifier

**Files:**
- Create: `myApp/integrations/ghl/webhook.py`
- Test: `myApp/tests/test_ghl_webhook.py`

- [ ] **Step 1: Write the failing test**

```python
# myApp/tests/test_ghl_webhook.py
import base64
from django.test import SimpleTestCase, override_settings
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from myApp.integrations.ghl import webhook

_priv = Ed25519PrivateKey.generate()
_pub_b64 = base64.b64encode(
    _priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
).decode()


@override_settings(GHL_WEBHOOK_PUBLIC_KEY=_pub_b64)
class WebhookVerifyTests(SimpleTestCase):
    def test_valid_signature(self):
        body = b'{"type":"ContactCreate"}'
        sig = base64.b64encode(_priv.sign(body)).decode()
        self.assertTrue(webhook.verify(body, sig))

    def test_bad_signature(self):
        self.assertFalse(webhook.verify(b'{"type":"X"}', base64.b64encode(b"wrong").decode()))

    def test_tampered_body(self):
        sig = base64.b64encode(_priv.sign(b'{"type":"A"}')).decode()
        self.assertFalse(webhook.verify(b'{"type":"B"}', sig))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_webhook.WebhookVerifyTests -v 2`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# myApp/integrations/ghl/webhook.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_webhook.WebhookVerifyTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add myApp/integrations/ghl/webhook.py myApp/tests/test_ghl_webhook.py
git commit -m "feat(ghl): add Ed25519 webhook signature verifier"
```

---

## Task 10: Webhook receiver view

**Files:**
- Modify: `myApp/ghl_views.py` (append `ghl_webhook`)
- Test: `myApp/tests/test_ghl_webhook.py` (view portion — append)

- [ ] **Step 1: Append the failing test**

```python
# append to myApp/tests/test_ghl_webhook.py
import json
from django.test import TestCase, Client, override_settings
from myApp.models import Tenant
from myApp.models_ghl import GHLConnection, GHLLink


@override_settings(GHL_WEBHOOK_PUBLIC_KEY=_pub_b64)
class WebhookViewTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")
        self.conn = GHLConnection.objects.create(tenant=self.tenant, ghl_location_id="LOC1")
        self.client = Client()

    def _post(self, payload):
        body = json.dumps(payload).encode()
        sig = base64.b64encode(_priv.sign(body)).decode()
        return self.client.post(
            "/ghl/webhook", data=body, content_type="application/json",
            HTTP_X_GHL_SIGNATURE=sig,
        )

    def test_bad_signature_rejected(self):
        resp = self.client.post("/ghl/webhook", data=b"{}", content_type="application/json",
                                HTTP_X_GHL_SIGNATURE="bad")
        self.assertEqual(resp.status_code, 401)

    def test_contact_create_makes_link(self):
        resp = self._post({"type": "ContactCreate", "locationId": "LOC1", "id": "C9"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(GHLLink.objects.filter(tenant=self.tenant, ghl_contact_id="C9").exists())

    def test_unknown_event_ignored(self):
        resp = self._post({"type": "InvoicePaid", "locationId": "LOC1"})
        self.assertEqual(resp.status_code, 200)
        self.assertJSONEqual(resp.content, {"status": "ignored"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_webhook.WebhookViewTests -v 2`
Expected: FAIL — 404 / view missing.

- [ ] **Step 3: Append the view to `myApp/ghl_views.py`**

```python
import json
from django.http import JsonResponse, HttpResponse
from myApp.models_ghl import GHLLink
from myApp.integrations.ghl import webhook as ghl_webhook


@csrf_exempt
@require_http_methods(["POST"])
def ghl_webhook(request):
    raw = request.body  # must read before parsing
    sig = request.headers.get("X-GHL-Signature", "")
    if not ghl_webhook.verify(raw, sig):
        return HttpResponse(status=401)

    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        return HttpResponse(status=400)

    location_id = str(event.get("locationId") or "").strip()
    connection = (
        GHLConnection.objects.select_related("tenant")
        .filter(ghl_location_id=location_id)
        .first()
    )
    if not connection:
        return JsonResponse({"status": "ignored"})

    etype = event.get("type", "")
    tenant = connection.tenant

    if etype in ("ContactCreate", "ContactUpdate"):
        contact_id = str(event.get("id") or event.get("contactId") or "").strip()
        if contact_id:
            GHLLink.objects.update_or_create(
                tenant=tenant, ghl_contact_id=contact_id,
                defaults={"connection": connection, "sync_status": "active"},
            )
        return JsonResponse({"status": "ok"})

    if etype == "ContactDelete":
        contact_id = str(event.get("id") or event.get("contactId") or "").strip()
        GHLLink.objects.filter(tenant=tenant, ghl_contact_id=contact_id).update(sync_status="error")
        return JsonResponse({"status": "ok"})

    return JsonResponse({"status": "ignored"})
```

> Confirm `GHLLink` has a `sync_status` field with an `"active"`/`"error"` choice (exploration showed it does). Confirm the GHL Contact event key for the contact id (`id` vs `contactId`) against a real captured payload during this task.

- [ ] **Step 4: Add the route**

In `myProject/urls.py`:
```python
    path('ghl/webhook', ghl_views.ghl_webhook, name='ghl_webhook'),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_webhook.WebhookViewTests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add myApp/ghl_views.py myProject/urls.py myApp/tests/test_ghl_webhook.py
git commit -m "feat(ghl): add /ghl/webhook receiver for Contact events"
```

---

## Task 11: Verify all routes wired

**Files:**
- Modify: `myProject/urls.py` (confirm)

- [ ] **Step 1: Confirm the GHL URL block reads**

```python
    path('ghl/callback', ghl_views.ghl_callback, name='ghl_callback'),
    path('ghl/connect/', ghl_views.ghl_connect, name='ghl_connect'),
    path('ghl/disconnect/', ghl_views.ghl_disconnect, name='ghl_disconnect'),
    path('ghl/embed', ghl_views.ghl_embed, name='ghl_embed'),
    path('ghl/sso', ghl_views.ghl_sso, name='ghl_sso'),
    path('ghl/webhook', ghl_views.ghl_webhook, name='ghl_webhook'),
    path('dashboard/integrations/ghl/', ghl_views.ghl_settings, name='ghl_settings'),
```

- [ ] **Step 2: Run the full GHL test module**

Run: `python manage.py test myApp.tests.test_ghl_user_context myApp.tests.test_ghl_sso myApp.tests.test_ghl_embed myApp.tests.test_ghl_webhook myApp.tests.test_ghl_frame -v 2`
Expected: all PASS.

- [ ] **Step 3: Commit (if any changes)**

```bash
git add myProject/urls.py
git commit -m "chore(ghl): confirm embed/sso/webhook routes wired" || echo "nothing to commit"
```

---

## Task 12: Harden callback for Company/agency installs

**Files:**
- Modify: `myApp/ghl_views.py` (`ghl_callback`)
- Test: `myApp/tests/test_ghl_callback.py`

- [ ] **Step 1: Write the failing test**

```python
# myApp/tests/test_ghl_callback.py
from unittest import mock
from django.test import TestCase
from myApp.models import Tenant
from myApp.models_ghl import GHLConnection
from myApp.integrations.ghl import state


class CallbackCompanyInstallTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="NCD", slug="ncd")

    @mock.patch("myApp.ghl_views.oauth.get_location_token")
    @mock.patch("myApp.ghl_views.oauth.exchange_code")
    def test_company_token_mints_location_token(self, mock_exchange, mock_mint):
        mock_exchange.return_value = {
            "access_token": "company-tok", "refresh_token": "r",
            "expires_in": 3600, "companyId": "CO1", "userType": "Company", "scope": "x",
        }
        mock_mint.return_value = {
            "access_token": "loc-tok", "refresh_token": "r2",
            "expires_in": 3600, "locationId": "LOC9", "companyId": "CO1", "scope": "x",
        }
        token = state.encode(self.tenant.id)
        resp = self.client.get("/ghl/callback", {"code": "abc", "state": token})
        mock_mint.assert_called_once()
        conn = GHLConnection.objects.get(tenant=self.tenant)
        self.assertEqual(conn.ghl_location_id, "LOC9")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_callback -v 2`
Expected: FAIL — current callback errors on missing locationId instead of minting.

- [ ] **Step 3: Edit `ghl_callback`**

In `myApp/ghl_views.py`, in `ghl_callback`, replace the "needs_location" branch so that when the token payload lacks `locationId` but has `companyId`, it mints a Location token:

```python
    token_payload = oauth.exchange_code(code)
    location_id = token_payload.get("locationId")
    company_id = token_payload.get("companyId")

    if not location_id and company_id:
        # Agency/Company install — mint a Location-scoped token.
        # NOTE: with Sub-Account distribution + chooselocation this is the
        # fallback path; if multiple locations exist this needs a picker
        # (deferred). For the single-location case, GHL returns the chosen one.
        minted = oauth.get_location_token(
            token_payload.get("access_token"), company_id, location_id or ""
        )
        if minted and minted.get("locationId"):
            token_payload = minted
            location_id = minted.get("locationId")

    if not location_id:
        return redirect(f"{return_to}?ghl=needs_location")
```

Keep the existing connection upsert below unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_callback -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add myApp/ghl_views.py myApp/tests/test_ghl_callback.py
git commit -m "feat(ghl): mint location token for Company/agency installs in callback"
```

---

## Task 13: Rich default scopes

**Files:**
- Modify: `myApp/integrations/ghl/config.py`
- Test: `myApp/tests/test_ghl_config.py`

- [ ] **Step 1: Write the failing test**

```python
# myApp/tests/test_ghl_config.py
from django.test import SimpleTestCase
from myApp.integrations.ghl import config


class ScopeTests(SimpleTestCase):
    def test_rich_scopes_present(self):
        scopes = set(config.DEFAULT_GHL_SCOPES.split())
        for s in ["contacts.readonly", "opportunities.readonly", "calendars.readonly",
                  "conversations.readonly", "users.readonly", "workflows.readonly"]:
            self.assertIn(s, scopes)

    def test_no_sensitive_unused(self):
        self.assertNotIn("users.write", config.DEFAULT_GHL_SCOPES.split())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test myApp.tests.test_ghl_config -v 2`
Expected: FAIL — current default is the minimal 3-scope string.

- [ ] **Step 3: Set the rich scope default in `config.py`**

Replace the default scopes constant with (kept in sync with `select-subaccount-scopes.js`; `users.write` deliberately excluded):

```python
DEFAULT_GHL_SCOPES = (
    "contacts.readonly contacts.write "
    "opportunities.readonly opportunities.write "
    "locations.readonly "
    "locations/customValues.readonly locations/customValues.write "
    "locations/tags.readonly locations/tags.write "
    "locations/tasks.readonly "
    "calendars.readonly calendars.write "
    "calendars/events.readonly calendars/events.write "
    "conversations.readonly conversations.write "
    "conversations/message.readonly conversations/message.write "
    "users.readonly businesses.readonly forms.readonly "
    "surveys.readonly workflows.readonly"
)
```

(Ensure `get_scopes()`/`SCOPES` falls back to `DEFAULT_GHL_SCOPES` when the `GHL_SCOPES` env is blank — confirm existing logic in `config.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test myApp.tests.test_ghl_config -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add myApp/integrations/ghl/config.py myApp/tests/test_ghl_config.py
git commit -m "feat(ghl): request full sub-account scope set by default"
```

---

## Task 14: Full suite + manual end-to-end verification

**Files:** none (verification)

- [ ] **Step 1: Run the complete test suite**

Run: `python manage.py test myApp -v 1`
Expected: all PASS (no regressions in existing tests).

- [ ] **Step 2: Configure the dev marketplace app**

- On the app's scope picker: paste `business-center/select-subaccount-scopes.js` in DevTools console; confirm the report.
- On the app's Webhooks → Events tab: paste `business-center/enable-webhook-events.js`; confirm the report.
- Set dev `.env`: `GHL_CLIENT_ID`, `GHL_CLIENT_SECRET`, `GHL_SHARED_SECRET_KEY`, `GHL_REDIRECT_URI=<TUNNEL>/ghl/callback`, `GHL_TOKEN_ENCRYPTION_KEY`, `GHL_WEBHOOK_PUBLIC_KEY`.

- [ ] **Step 3: Manual flow against a test GHL location**

1. Log into CourseForge as the test tenant admin → `/dashboard/integrations/ghl/` → "Connect GoHighLevel" → choose the test location → confirm `GHLConnection` row created with `ghl_location_id`.
2. In GHL, open the CourseForge Custom Page in the sidebar → confirm it lands on the academy dashboard **inside the iframe** (check: no `X-Frame-Options` on the response, CSP `frame-ancestors` present, session cookie has `SameSite=None; Secure; Partitioned`).
3. Confirm a `GhlEmbedSession` row was written; if the GHL user's email didn't match a member, confirm `impersonated_owner=True`.
4. Create/edit a contact in GHL → confirm a `GHLLink` row appears (webhook path).

- [ ] **Step 4: Record results** in `Documents/GHL_SIDEBAR_EMBED_DESIGN.md` (append a "Verification" note) and resolve the 4 open items in spec §13.

---

## Self-Review (completed by plan author)

**Spec coverage:** A (embed) → Tasks 2,3,7,8; B (rich scopes + Company hardening) → Tasks 12,13; C (webhooks) → Tasks 9,10; D (audit) → Tasks 4,6; frame/CSP/cookies → Tasks 1,5; settings/env → Task 1; routes → Tasks 8,10,11; testing → every task + Task 14. All spec sections mapped.

**Placeholder scan:** No "TBD/handle edge cases" steps; every code step shows code. The 4 "confirm during impl" notes are genuine external unknowns (GHL header casing, contact-id key, Python `Partitioned` support, `TenantMembership`/`auth_login` backend specifics) — each is paired with a concrete fallback, not a deferral of design.

**Type consistency:** `GhlUserContext` fields used identically across Tasks 2/6/8; `sso.issue/consume` signatures match Tasks 3/8; `GHLConnection.ghl_location_id`, `GHLLink.ghl_contact_id/sync_status`, `GhlEmbedSession` fields consistent across model + helper + views.
