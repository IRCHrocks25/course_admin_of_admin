# CourseForge — GoHighLevel Marketplace App Setup (prod-only, step by step)

> One new CourseForge-owned marketplace app, pointed straight at production
> (`courseforge.katek-ai.com`). Created once in the HighLevel developer portal
> UI — no API. No dev app / tunnel for now.

**Before any of this works:** the GHL embed code (merged to `main`) must be **deployed** to `courseforge.katek-ai.com` (CourseForge deploys from `main` on Railway → push `main`, Railway redeploys), and the env vars in Step 8 must be set on the Railway prod service.

**Safety:** do the first smoke test on a **throwaway test sub-account** under the Katek agency, then flip the same app on for NCD's real sub-account.

The app needs three URLs, all on the prod host, **no trailing slashes** (Django `APPEND_SLASH` would 301 and break the handshake):

| Purpose             | URL                                              |
| ------------------- | ------------------------------------------------ |
| OAuth redirect      | `https://courseforge.katek-ai.com/ghl/callback`  |
| Custom Page (embed) | `https://courseforge.katek-ai.com/ghl/embed`     |
| Webhook             | `https://courseforge.katek-ai.com/ghl/webhook`   |

---

## Prerequisites

- HighLevel **agency** account (Katek's; agency owner or above) + developer portal access: `marketplace.gohighlevel.com`.
- The embed code **deployed** to `courseforge.katek-ai.com` (push `main`).
- A **test sub-account** inside the Katek agency for the first smoke test (Agency dashboard → Sub-Accounts → Create), plus NCD's real sub-account for go-live.
- The CourseForge app logo: `static/img/courseforge-icon-512.png` (in this repo).

---

## 1. Create the app

Developer portal → **My Apps → Create App**.

- **Name:** `CourseForge`
- **Logo:** upload `static/img/courseforge-icon-512.png`
- **Description:** e.g. "Embed your CourseForge academy inside GoHighLevel and sync contacts."
- App type: **OAuth / Marketplace app** (not a private integration).

---

## 2. Distribution settings (CRITICAL)

All three must be set or marketplace installs misbehave:

| Setting             | Required value   |
| ------------------- | ---------------- |
| **Target User**     | Sub-Account      |
| **Who Can Install** | Sub-Account only |
| **Bulk Install**    | Disabled (OFF)   |

(The UI scatters these across the Distribution / Settings tabs — set all three before saving.)

---

## 3. Scopes (OAuth consent set)

Authoritative list = `myApp/integrations/ghl/config.py` → `_DEFAULT_SCOPES`. Tick each:

```
contacts.readonly
contacts.write
opportunities.readonly
opportunities.write
locations.readonly
locations/customValues.readonly
locations/customValues.write
locations/tags.readonly
locations/tags.write
locations/tasks.readonly
calendars.readonly
calendars.write
calendars/events.readonly
calendars/events.write
conversations.readonly
conversations.write
conversations/message.readonly
conversations/message.write
users.readonly
businesses.readonly
forms.readonly
surveys.readonly
workflows.readonly
```

**Shortcut:** on the app's scope-picker tab, DevTools → Console, paste `business-center/select-subaccount-scopes.js`, Enter. It ticks every Sub-Account-compatible scope and leaves Sensitive-but-unused ones (e.g. `users.write`) off — matching `_DEFAULT_SCOPES`. Check its console report.

> If OAuth later fails with `invalid_scope`, a scope was renamed/removed — fix it in `_DEFAULT_SCOPES` and re-test.

---

## 4. Redirect URL

App → **Settings → Redirect URLs** → Add exactly:

```
https://courseforge.katek-ai.com/ghl/callback
```

Exact match — scheme, host, path, no trailing slash. Mismatch → `redirect_uri_mismatch`.

---

## 5. Custom Page (the sidebar embed)

App → **Custom Pages / App Pages** (a.k.a. "Custom Menu Link") → Add:

- **Page name / menu label:** `CourseForge Academy`
- **Page URL:** `https://courseforge.katek-ai.com/ghl/embed`
- **Icon:** reuse `static/img/courseforge-icon-512.png` if it allows an upload.

How it works: GHL loads `/ghl/embed` in an iframe with an `encryptedUserData` blob → CourseForge decrypts it with the **Shared Secret** (Step 8) → finds the tenant by GHL `locationId` → auto-logs the user in → renders their academy dashboard in the iframe.

---

## 6. Webhook URL + events

App → **Webhooks**:

- **Webhook URL:** `https://courseforge.katek-ai.com/ghl/webhook`
- **Events:** CourseForge handles **Contact** events today (others ignored safely). Subscribe broadly (no re-consent cost): Webhooks → Events tab, DevTools → Console, paste `business-center/enable-webhook-events.js`, Enter.

---

## 7. Webhook signing (Ed25519)

App → Webhooks → **Public Key** → copy → set as `GHL_WEBHOOK_PUBLIC_KEY`. CourseForge verifies each webhook's `X-GHL-Signature` over the raw body with this key. If empty, send a test event first, then copy it.

---

## 8. Credentials, Shared Secret, and env vars

App → **Settings → Credentials**: Client ID, Client Secret.
App → **Advanced Settings → Auth**: Shared Secret Key (distinct from Client Secret — decrypts the Custom Page User Context).

Set these on the **Railway prod service** for CourseForge:

| Var | Value / source |
|---|---|
| `GHL_CLIENT_ID` | Step 8 |
| `GHL_CLIENT_SECRET` | Step 8 |
| `GHL_REDIRECT_URI` | `https://courseforge.katek-ai.com/ghl/callback` |
| `GHL_SHARED_SECRET_KEY` | Step 8 (Advanced Settings → Auth) |
| `GHL_WEBHOOK_PUBLIC_KEY` | Step 7 |
| `GHL_TOKEN_ENCRYPTION_KEY` | generate (below) |
| `GHL_SCOPES` | leave **blank** (uses `_DEFAULT_SCOPES`) |
| `PLATFORM_BASE_DOMAIN` | `courseforge.katek-ai.com` (so the embed builds `<slug>.courseforge.katek-ai.com` redirects) |
| `GHL_EMBED_HOST_OVERRIDE` | leave **blank** in prod |

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> No separate OAuth-state secret — CourseForge signs the OAuth `state` and the one-time SSO token with Django's existing `SECRET_KEY`.

After setting env vars, redeploy so they take effect.

---

## 9. Smoke test (in order)

**A. Connect (links tenant ↔ location):**
1. Log into CourseForge as a tenant admin of your **test** tenant.
2. `/dashboard/integrations/ghl/` → **Connect GoHighLevel**.
3. Choose your **test** sub-account → grant scopes.
4. Redirects back with `?ghl=connected`; a `GHLConnection` row now holds the sub-account's `ghl_location_id`.

**B. Sidebar embed (the goal):**
5. In that same sub-account, open **CourseForge Academy** from the GHL sidebar.
6. It should land on the academy dashboard, logged in, **inside the GHL iframe**.

**C. Webhook:**
7. Create/edit a contact in that sub-account → a `GHLLink` row appears for the tenant.

**Go live:** repeat A (Connect) for NCD's real sub-account from NCD's CourseForge tenant.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `redirect_uri_mismatch` | The Redirect URL isn't exactly `https://courseforge.katek-ai.com/ghl/callback` (trailing slash / scheme). |
| Embed: **"Open from a sub-account"** | Opened at agency level / no `locationId`. Open from inside a sub-account. |
| Embed: **"Academy not connected"** | That sub-account hasn't done step A. Run Connect first. |
| Iframe **blank** | Confirm the deploy includes `GhlEmbedFrameMiddleware` and `GHL_EMBED_FRAME_ANCESTORS` covers `*.gohighlevel.com *.leadconnectorhq.com`. |
| Logged out / loop in iframe | Session cookie needs `SameSite=None; Secure; Partitioned`. Prod is HTTPS so this works; if behind a proxy, ensure `Secure` isn't stripped. |
| Webhook **401** | `GHL_WEBHOOK_PUBLIC_KEY` mismatch, or GHL's header isn't `X-GHL-Signature`. Confirm key; adjust `ghl_webhook` if the header name differs. |
| Company/agency install error | Distribution must be **Sub-Account** (Step 2). Multi-location agency picker isn't built yet. |

---

## Confirm against live GHL (safe fallbacks already in code)
1. Webhook signature **header name/casing** (code expects `X-GHL-Signature`).
2. Contact webhook **id key** (code accepts `id` or `contactId`).

## Logo / favicon assets (this repo, `static/img/`)
- `courseforge-icon-512.png` — **upload as the marketplace app logo** (Step 1).
- `courseforge-logo.svg` — vector source.
- `courseforge-favicon.ico` (16/32/48), `courseforge-favicon-32.png`, `-16.png`, `courseforge-apple-touch-180.png` — site favicon.
