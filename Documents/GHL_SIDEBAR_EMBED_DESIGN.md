# CourseForge ⇄ GoHighLevel — Sidebar Embed + Connect (Design Spec)

**Date:** 2026-06-25
**Author:** Bernard G. Tapiru, Jr.
**Repo:** `IRCHrocks25/course_admin_of_admin` (CourseForge, Django 5.x, multi-tenant)
**Status:** Design — approved, pending spec review → implementation plan
**Primary tenant for first rollout:** NCD (GHL location `0XnI4yojEhHfZAvCuUVf`)

---

## 1. Goal

Make CourseForge appear and work **inside the GoHighLevel (GHL) left sidebar** as a Custom Page, via our **own** GHL Marketplace App. When a GHL sub-account user opens the CourseForge Custom Page, they land **auto-logged-in** on their tenant's academy dashboard, rendered inside the GHL iframe.

This builds on an already-substantial OAuth scaffold in `myApp/integrations/ghl/`. The work is **finishing the embed half**, hardening connect, and adding contact webhooks — not greenfield.

### In scope (this build)
- **A. Sidebar embed with auto-login** (the main goal).
- **B. Rich-scope OAuth connect** + Company/agency-install hardening.
- **C. Contact webhooks** (Ed25519-verified receiver, Contact events → `GHLLink`).
- **D. Embed audit trail** (track GHL identity behind owner-fallback logins).

### Out of scope (explicitly deferred)
Course migration GHL→Academy · marketplace-initiated installs · payments/CRM integration · webinars/resource spaces · SOP Master (same pattern, replicated after CourseForge proves out).

---

## 2. What already exists (do not rebuild)

From `myApp/integrations/ghl/` and `myApp/ghl_views.py`:
- `oauth.py` — `build_authorize_url(state)`, `exchange_code(code)`, `get_location_token(company_access_token, company_id, location_id)`, `refresh_connection(id)` (per-tenant `select_for_update` + single-use refresh rotation), `needs_refresh()`. Endpoints hard-coded to `marketplace.leadconnectorhq.com` / `services.leadconnectorhq.com`, API version `2021-07-28`.
- `crypto.py` — Fernet encrypt/decrypt; key from `GHL_TOKEN_ENCRYPTION_KEY` (falls back to SHA-256 of `SECRET_KEY`).
- `state.py` — signed OAuth state token, 600 s TTL, carries `tenant_id` + `return_to`.
- `config.py` — reads `GHL_CLIENT_ID/SECRET/REDIRECT_URI/WEBHOOK_PUBLIC_KEY/SCOPES`; default scopes `contacts.readonly contacts.write locations.readonly`.
- `models_ghl.py` — `GHLConnection` (OneToOne→Tenant; **`ghl_location_id` unique**; encrypted access/refresh tokens; `apply_token_payload()`; `sync_status`; `is_healthy`) and `GHLLink` (Tenant + GHLConnection + optional User; `ghl_contact_id`; unique `(tenant, ghl_contact_id)`).
- `ghl_views.py` — `ghl_settings`, `ghl_connect` (POST→authorize), `ghl_callback` (state→tenant→exchange→upsert connection, flips `tenant.ghl_enabled`), `ghl_disconnect`.
- URLs: `/ghl/callback`, `/ghl/connect/`, `/ghl/disconnect/`, `/dashboard/integrations/ghl/`.
- `management/commands/ghl_refresh_tokens.py` — ready, not yet scheduled.

**Gaps this spec fills:** no Custom Page embed route; no User-Context decryption; no frame/CSP allowance (Django `XFrameOptionsMiddleware` defaults to `DENY`); no `location_id → tenant` embed resolver; callback rejects Company-token installs; no webhook endpoint (public key read but unused); no embed audit.

---

## 3. Architecture overview

Three entry points, all under `/ghl/`:

| Route | Host | Purpose | Auth |
|---|---|---|---|
| `/ghl/connect/`, `/ghl/callback`, `/ghl/disconnect/` | platform + tenant | OAuth install (exists; hardened) | session (connect/disconnect), state (callback) |
| `/ghl/embed` | **platform** | GHL Custom Page; decrypt context → resolve tenant+user → SSO redirect | none (trusts decrypted GHL context) |
| `/ghl/sso` | **tenant** | consume one-time SSO token → `login()` → dashboard | one-time token |
| `/ghl/webhook` | platform | Ed25519-verified event receiver | signature |

Tenant resolution stays **host-based** (existing `TenantMiddleware`) for the dashboard; the embed resolves tenant from the decrypted GHL `locationId` and **hops to the tenant host** so all existing dashboard code runs unchanged and custom-domain tenants work.

---

## 4. Part A — Sidebar embed with auto-login

### 4.1 New module: `integrations/ghl/user_context.py`
Decrypts GHL's Custom Page User Context blob.
- Input: `encryptedUserData` (or `userData`) query param.
- Format: base64(`Salted__` ‖ 8-byte salt ‖ ciphertext); **AES-256-CBC**; key+IV via OpenSSL `EVP_BytesToKey` with **MD5** (CryptoJS-legacy compatible).
- Secret: new env **`GHL_SHARED_SECRET_KEY`** (distinct from client secret).
- Output: dataclass `GhlUserContext { location_id, user_id, company_id, user_type, user_name, email, role, type }`. Returns `None` on any failure (soft-fail → unauthorized card).
- Pure + unit-tested against a known CryptoJS vector.

### 4.2 New module: `integrations/ghl/sso.py`
One-time cross-host login token.
- `issue(user_id, tenant_id, embed_session_id) -> token` — Django `signing.dumps` with a dedicated salt, short TTL (default **60 s**).
- `consume(token) -> {user_id, tenant_id, embed_session_id}` — verifies signature + TTL; enforces **single-use** via a cache key (`ghl:sso:<jti>`); raises on reuse/expiry/tamper.

### 4.3 New view: `ghl_embed` (platform host) — `GET /ghl/embed`
1. `@csrf_exempt`, `@xframe_options_exempt`; response carries embed CSP (see §7).
2. Read `encryptedUserData|userData` → `user_context.decrypt()`.
3. No blob / decrypt fail / `type == "agency"` / no `location_id` → render **`embed_unauthorized.html`** ("open from a sub-account").
4. `GHLConnection.objects.select_related('tenant').filter(ghl_location_id=location_id).first()`; none → **`embed_not_connected.html`** ("connect CourseForge to GHL first").
5. **Resolve user** (see §6): email-match → owner-fallback.
6. Write **`GhlEmbedSession`** audit row (see §6.2); stamp nothing yet (no session on platform host).
7. `token = sso.issue(user.id, tenant.id, embed_session.id)`; `302` → `https://<tenant_host>/ghl/sso?t=<token>&next=/dashboard`.
   - `<tenant_host>` derived from tenant (custom domain if set, else `<slug>.<PLATFORM_BASE_DOMAIN>`); honors a `GHL_EMBED_HOST_OVERRIDE`/`lvh.me` style for local dev.

### 4.4 New view: `ghl_sso` (tenant host) — `GET /ghl/sso`
1. `@xframe_options_exempt`; embed CSP on response.
2. `payload = sso.consume(request.GET['t'])`; on failure → **`embed_error.html`** (403).
3. Guard: `payload.tenant_id == request.tenant.id` (host must match token's tenant) else 403.
4. `login(request, user)`.
5. Set **iframe session cookie**: `SameSite=None; Secure; Partitioned` (CHIPS). Set `session['ghl_embed'] = True` and `session['ghl_actor'] = {embed_session_id, ghl_user_id, email, name, role, location_id}`.
6. `302` → `next` (default `/dashboard`).

### 4.5 Dashboard renders in-frame
`GhlEmbedFrameMiddleware` (see §7) lets the existing dashboard render inside the GHL iframe **only** for `session['ghl_embed']` requests. No dashboard view changes.

---

## 5. Part B — Rich-scope OAuth connect + hardening

- **Scopes:** request the **full Sub-Account-compatible set** at connect time so later phases need no partner re-consent. Configured on the app via `business-center/select-subaccount-scopes.js` (idempotent DevTools paste; auto-ticks "Sub-Account" + "Sub + agency" rows, **denylists Sensitive-but-unused** e.g. `users.write`). Mirror the same list into `config.py` `DEFAULT_GHL_SCOPES` so code ↔ app stay in sync. Keep the denylist (matches standing "no unused sensitive scopes" policy).
- **Company/agency install hardening:** in `ghl_callback`, if `exchange_code` returns a Company token / no `locationId`, call existing `oauth.get_location_token(company_access_token, company_id, location_id)` to mint a Location token before upserting, instead of the current "needs_location" error. App distribution = **Sub-Account only + `chooselocation`** authorize URL (so Location tokens are the normal case; Company path is a guard).
- **Token refresh:** wire `ghl_refresh_tokens` to a schedule (cron/host-cron exec, consistent with existing VPS pattern) — out-of-band of request flow.

---

## 6. Part D — User resolution + embed audit

### 6.1 Resolution order (per approved decision)
1. **Email match:** active `TenantMembership` user in this tenant whose email == `ctx.email` → use them.
2. **Owner fallback:** else the tenant "owner" — defined as the tenant's primary admin (earliest active `TenantMembership` with `role='tenant_admin'`; confirm whether the model has an explicit owner flag during impl) — and mark `impersonated_owner = True`.
3. (Auto-provision is **not** done in this build.)

### 6.2 New model: `GhlEmbedSession` (audit)
Every embed login writes one row:
```
tenant            FK Tenant
connection        FK GHLConnection (null=True)
ghl_location_id   CharField
ghl_user_id       CharField(blank)
ghl_email         CharField(blank)
ghl_user_name     CharField(blank)
ghl_role          CharField(blank)
ghl_user_type     CharField(blank)      # location|agency
resolved_user     FK User (null=True)   # who we logged in as
impersonated_owner BooleanField         # True when owner-fallback used
django_session_key CharField(blank)
ip_address        GenericIPAddressField(null=True)
user_agent        TextField(blank)
created_at        DateTimeField(auto_now_add)
indexes: (tenant, created_at), (ghl_location_id)
```
The session also carries `ghl_actor` (§4.4) so in-session actions are attributable to the real GHL person even under owner-fallback. New migration required.

---

## 7. Part C — Contact webhooks

- **New module `integrations/ghl/webhook.py`:** `verify(raw_body, signature_header) -> bool` using Ed25519 over the **raw** request body with `GHL_WEBHOOK_PUBLIC_KEY` (base64 or PEM). Header `X-GHL-Signature` (confirm exact casing against GHL docs during impl).
- **New view `ghl_webhook` — `POST /ghl/webhook`:** `@csrf_exempt`; read `request.body` **before** parsing; verify signature (else `401`); parse JSON; resolve tenant via payload `locationId` → `GHLConnection`.
  - **Handle:** `ContactCreate` / `ContactUpdate` / `ContactDelete` → upsert/soft-delete `GHLLink(tenant, ghl_contact_id, …)`.
  - **All other event types → `200 {"status":"ignored"}` with no writes** (IBC pattern; webhook subscription is broad, handling is narrow).
- **App config:** webhook URL = `https://courseforge.katek-ai.com/ghl/webhook` (single per app). Subscribe events via `business-center/enable-webhook-events.js`. No re-consent needed to change subscriptions later.

---

## 8. Frame / CSP / cookies

- **`GhlEmbedFrameMiddleware`** (added in `myApp/middleware.py`): for requests with `session.get('ghl_embed')` (and for the `/ghl/embed`, `/ghl/sso` routes), set
  `Content-Security-Policy: frame-ancestors 'self' https://*.gohighlevel.com https://*.leadconnectorhq.com` and **remove** `X-Frame-Options`. All other requests keep the default `DENY` (tenant sites stay non-embeddable elsewhere).
- **Cookies:** embed session cookie must be `SameSite=None; Secure; Partitioned`. Scope this to the embed flow (do not globally weaken non-embed sessions if avoidable); document the Chrome CHIPS `Partitioned` requirement and the Django version's handling (may require manual `Set-Cookie`).

---

## 9. Settings / env

New:
- `GHL_SHARED_SECRET_KEY` — User-Context decryption (per env).
- `GHL_EMBED_FRAME_ANCESTORS` (default the two GHL domains).
- iframe cookie flags (embed-scoped).

Existing (already wired): `GHL_CLIENT_ID`, `GHL_CLIENT_SECRET`, `GHL_REDIRECT_URI`, `GHL_SCOPES`, `GHL_WEBHOOK_PUBLIC_KEY`, `GHL_TOKEN_ENCRYPTION_KEY`. Add all new vars to `.env.example` with comments, and (per repo convention) a Dockerfile placeholder + compose passthrough if build-time evaluation requires it.

---

## 10. Marketplace app setup (dev → prod)

| Field | Dev | Prod |
|---|---|---|
| Redirect URI | `https://<tunnel>/ghl/callback` | `https://courseforge.katek-ai.com/ghl/callback` |
| Custom Page URL | `https://<tunnel>/ghl/embed` | `https://courseforge.katek-ai.com/ghl/embed` |
| Webhook URL | `https://<tunnel>/ghl/webhook` | `https://courseforge.katek-ai.com/ghl/webhook` |
| Distribution | Sub-Account only | Sub-Account only |
| Scopes | run `select-subaccount-scopes.js` | same |
| Webhook events | run `enable-webhook-events.js` | same |

Build + test the full flow locally against a **test** GHL location, then point the prod app at `courseforge.katek-ai.com` and connect NCD.

---

## 11. Testing (TDD)

- **Unit:** `user_context.decrypt` (known CryptoJS vector; tamper → None); `sso.issue/consume` (valid / expired / replay / wrong-tenant); `webhook.verify` (good / bad / wrong-key Ed25519); user-resolution (email-match vs owner-fallback flags); `location_id → tenant` resolver.
- **View:** `/ghl/embed` valid / missing-blob / agency-context / not-connected → correct card or 302; `/ghl/sso` valid / expired / replay / host-mismatch → login or 403; `/ghl/webhook` good-sig Contact event → `GHLLink` write, bad-sig → 401, unknown event → 200 ignored.
- **Headers:** embed + dashboard-in-embed responses carry the frame-ancestors CSP and **no** `X-Frame-Options`; non-embed responses keep `DENY`.
- **Audit:** every embed login writes a `GhlEmbedSession`; owner-fallback sets `impersonated_owner=True`.

---

## 12. New / changed files

**New:** `integrations/ghl/user_context.py`, `integrations/ghl/sso.py`, `integrations/ghl/webhook.py`; `templates/ghl/embed_unauthorized.html`, `embed_not_connected.html`, `embed_error.html`; migration for `GhlEmbedSession`.
**Changed:** `ghl_views.py` (+`ghl_embed`, `ghl_sso`, `ghl_webhook`; harden `ghl_callback`); `myProject/urls.py` (+3 routes); `myApp/middleware.py` (+`GhlEmbedFrameMiddleware`); `myProject/settings.py` + `.env.example` (new vars, cookies); `integrations/ghl/config.py` (rich `DEFAULT_GHL_SCOPES`); `models_ghl.py` (+`GhlEmbedSession`).

---

## 13. Open items to confirm during implementation
1. Exact GHL webhook signature header name/casing + signing scheme (verify against current GHL docs; IBC uses `X-GHL-Signature` Ed25519 over raw body).
2. Current GHL scope-name drift (e.g. `customFields.*` → `customValues.*`, 2026-05) — reconcile picker vs `config.py`.
3. Django version's native support for the `Partitioned` cookie attribute vs manual `Set-Cookie`.
4. NCD tenant host: confirm `ncd.courseforge.katek-ai.com` vs a custom domain (affects the SSO redirect target).
