# Automatic Subdomain Creation Flow

This document explains how the platform automatically creates and uses a tenant subdomain when a new academy is created, based on the onboarding flow from:

- `myApp/templates/platform/start_academy.html`
- `myApp/templates/platform/academy_created.html`

---

## 1) User Entry Point (`start_academy.html`)

The onboarding form collects:

- `academy_name`
- owner/admin credentials
- plan selection and optional profile/referral fields

Important UX note:

- The URL input is intentionally disabled and labeled auto-generated.
- The user does **not** type a subdomain.
- The hint uses `platform_base_domain` to show the final shape:
  - `<tenant-slug>.<PLATFORM_BASE_DOMAIN>`

So subdomain generation is server-controlled, not user-controlled.

---

## 2) Tenant Slug Generation (Server Side)

In `start_academy()` (`myApp/views.py`), after validation:

1. Base slug is generated from academy name:
   - `base_slug = slugify(academy_name)`
2. Uniqueness is enforced by suffixing `-1`, `-2`, etc.:
   - loop while `Tenant.objects.filter(slug=tenant_slug).exists()`
3. Tenant record is created using that final unique slug.

This slug is the source for the automatic subdomain.

---

## 3) Domain Record Creation (`ensure_temporary_domain`)

The automatic subdomain is created through `ensure_temporary_domain(tenant)` in `myApp/utils/domains.py`.

### How the domain value is built

- `build_temporary_domain(tenant.slug)` returns:
  - `f"{tenant.slug}.{PLATFORM_BASE_DOMAIN}"`
- If `PLATFORM_BASE_DOMAIN` is missing/empty, no temporary domain is created.

### How it is persisted

`ensure_temporary_domain()` performs a `get_or_create` on `TenantDomain` with:

- `domain=<slug>.<base-domain>`
- `is_temporary=True`
- `is_primary=True`
- `is_verified=True`
- `verification_notes="System temporary domain"`

It also re-normalizes existing records so those flags remain true.

### Collision protection

If the same domain already belongs to another tenant, the function returns `None` and does not reassign it.

---

## 4) Where Temporary Domain Creation Is Triggered

It is triggered in both activation paths:

1. **Free-local onboarding path**
   - `start_academy()` -> `_activate_signup_free_local(...)` -> render success
2. **Stripe-paid onboarding path**
   - webhook or checkout-success fallback calls `_activate_signup_from_checkout_session(...)`
   - this function explicitly calls `ensure_temporary_domain(tenant)`

Additionally, the success renderer calls it again:

- `_render_academy_created_from_tenant()` starts with:
  - `temp_domain = ensure_temporary_domain(tenant)`

This makes the flow idempotent and self-healing if earlier steps missed a domain row.

---

## 5) URL Construction for Success Screen (`academy_created.html`)

`_render_academy_created_from_tenant()` prepares:

- `tenant_base_url`
- `tenant_register_url`
- `tenant_login_url`
- `tenant_courses_url`
- `tenant_dashboard_url`
- `tenant_domain_settings_url`

It first tries `get_tenant_public_home_url(request, tenant)`, which prefers:

1. verified primary domain
2. verified temporary domain
3. `tenant.custom_domain`
4. generated temporary domain from slug/base domain

### Fallback behavior

If no valid host is available, it falls back to platform URLs with tenant querystring:

- `/?tenant=<slug>`
- `/register/?tenant=<slug>`
- etc.

`academy_created.html` shows a fallback warning when `using_fallback_urls=True`.

---

## 6) Runtime Tenant Resolution (How Subdomain Becomes Context)

`TenantMiddleware` resolves the active tenant on each request:

1. If host is a platform host, it allows dev override with `?tenant=<slug>`.
2. Otherwise, it checks verified `TenantDomain.domain == host`.
3. Then checks `Tenant.custom_domain == host`.
4. Finally, it falls back to first subdomain label as slug (e.g. `acme` from `acme.example.com`).

Resolved tenant is attached as:

- `request.tenant`

This is what makes tenant-specific pages and data work when users open the generated subdomain.

---

## 7) Data Model Involved

- `Tenant.slug` (unique): canonical tenant identifier used for subdomain generation.
- `TenantDomain.domain` (unique): host mapping table for temporary and custom domains.
- `TenantDomain.is_temporary`: marks system-generated subdomain.
- `TenantDomain.is_primary` + `is_verified`: preferred for public URL generation and routing.

---

## 8) Operational Requirements

For automatic subdomains to work in production:

1. `PLATFORM_BASE_DOMAIN` must be set (for example, `myplatform.com`).
2. DNS/wildcard routing should point `*.PLATFORM_BASE_DOMAIN` to the app.
3. `PLATFORM_HOSTS` should list non-tenant platform hosts (landing/admin entry hosts).

If #1 is not set, onboarding still works but uses fallback querystring URLs instead of clean subdomains.

---

## 9) End-to-End Sequence (Short Form)

1. User submits `start_academy.html`.
2. Server slugifies `academy_name` and ensures unique `tenant.slug`.
3. Tenant is created (pending/inactive until activation path completes).
4. Activation path calls `ensure_temporary_domain(tenant)`.
5. Temporary domain record `<slug>.<base-domain>` is created/normalized in `TenantDomain`.
6. Success page `academy_created.html` receives tenant URLs derived from that domain.
7. Subsequent requests to that host are resolved by `TenantMiddleware` into `request.tenant`.

---

## 10) Current Design Choice Summary

- Subdomain creation is automatic, deterministic, and server-owned.
- User experience is simplified (no manual domain entry during onboarding).
- Domain creation is idempotent (safe repeated calls).
- The system degrades gracefully to querystring tenant routing when domain config is unavailable.
