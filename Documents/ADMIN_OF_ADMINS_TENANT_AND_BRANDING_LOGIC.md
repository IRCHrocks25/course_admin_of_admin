# Admin-of-Admins, Tenant Creation, and Branding Logic

This document explains how the platform currently handles:

- Super admin control ("admin of admins")
- Tenant creation and activation
- Tenant branding defaults, edits, and runtime usage

It is based on the current implementation in `myApp`.

## 1) Roles and Authority Model

### Super admin (admin of admins)

- Implemented as Django `User.is_superuser`.
- Guard for super admin pages is `superadmin_required` in `myApp/superadmin_views.py`.
- Super admins can:
  - Access `/superadmin/*` views
  - Create/edit/suspend/archive tenants
  - Create tenant admin users
  - Manage tenant domains and Stripe keys
  - Persist a selected tenant context while navigating dashboard pages

### Tenant admin

- Implemented through `TenantMembership` rows with:
  - `role='tenant_admin'`
  - `is_active=True`
- Tenant admins are also `user.is_staff=True` for dashboard access.
- Main tenant-admin dashboard routes are protected by `staff_member_required` in `myApp/dashboard_views.py`.

### Student/member users

- Normal users are scoped to a tenant via `request.tenant` and membership/access records.

## 2) Tenant Resolution and Context

### Request tenant resolution

`TenantMiddleware` in `myApp/middleware.py` resolves `request.tenant` using this order:

1. Platform hosts (from `PLATFORM_HOSTS`): normally no tenant; optional local preview via `?tenant=<slug>`
2. Verified `TenantDomain` match (`domain=host`, verified, active, non-archived tenant)
3. `Tenant.custom_domain` fallback
4. Subdomain slug fallback (`<slug>.<domain>`)

Result: every request gets either a tenant object or `None`.

### Dashboard tenant context

`_get_dashboard_tenant()` in `myApp/dashboard_views.py` determines tenant context for dashboard operations:

- For super admins:
  - Supports `?tenant=<slug>` to select tenant
  - Stores selected tenant in session (`superadmin_tenant_id`)
  - Supports clearing via `?clear_tenant=1` or `?tenant=clear`
- For non-superusers:
  - Falls back to active `TenantMembership(role='tenant_admin')`

This is the key mechanism that lets super admins behave as an "admin of admins" while inspecting tenant-scoped dashboard features safely.

## 3) Tenant Creation Flows

There are two main creation paths.

### A) Super admin manual creation

Handled in `superadmin_tenants()` (`myApp/superadmin_views.py`) when POSTing tenant form data:

1. Validates `name` and `slug`
2. Enforces uniqueness for:
   - `Tenant.slug`
   - `Tenant.custom_domain` (if provided)
3. Creates `Tenant`
4. Ensures companion records:
   - `TenantConfig.objects.get_or_create(tenant=tenant)`
   - `ensure_tenant_branding(tenant)`
   - `ensure_temporary_domain(tenant)`
5. Redirects to tenant detail page

### B) Self-serve signup (`start_academy`)

Handled in `start_academy()` (`myApp/views.py`):

1. Validates onboarding input (academy/admin fields, plan, password, referral, Stripe readiness)
2. Generates unique slug from academy name
3. Creates tenant in a pending state:
   - `is_active=False`
   - `billing_status='pending'`
   - `plan_code=<selected>`
4. Creates `TenantConfig` and seeds:
   - `features['brand_profile']`
   - `features['branding'] = build_default_branding(...)`
5. Creates admin user as inactive (`is_active=False`)
6. Either:
   - Local dev fast path (`_activate_signup_free_local`) -> immediate activation
   - Stripe Checkout path -> activation after successful payment/webhook

### Checkout activation logic

`_activate_signup_from_checkout_session()` finalizes signup:

- Sets tenant:
  - `billing_status='active'`
  - `is_active=True`
  - Stripe customer/subscription ids
- Calls:
  - `ensure_tenant_branding(tenant)`
  - `ensure_temporary_domain(tenant)`
- Activates admin user and grants tenant-admin membership:
  - `user.is_active=True`
  - `user.is_staff=True`
  - `TenantMembership(role='tenant_admin', is_active=True)`

This can run from:

- Stripe webhook (`stripe_webhook`, `checkout.session.completed`)
- Success page fallback (`start_academy_checkout_success`) if webhook is delayed

## 4) Tenant Admin Provisioning (by super admin)

`superadmin_create_tenant_admin()` in `myApp/superadmin_views.py`:

1. Accepts username/email/password
2. Creates new user or reuses existing user
3. Forces `is_staff=True`
4. Creates or updates `TenantMembership` with:
   - `role='tenant_admin'`
   - `is_active=True`
   - `must_change_password=True`

Password rotation is then enforced by:

- `ForcePasswordChangeMiddleware` (`myApp/middleware.py`)
- `force_password_change()` view (`myApp/views.py`)

## 5) Domain and Tenant Reachability

### Temporary domain lifecycle

`ensure_temporary_domain()` in `myApp/utils/domains.py`:

- Builds `<tenant_slug>.<PLATFORM_BASE_DOMAIN>`
- Creates/updates one temporary domain record
- Marks temporary domain as verified
- Makes it primary unless a verified custom primary domain exists
- De-prioritizes stale temporary domains

### Custom domain lifecycle

Super admin domain actions in `myApp/superadmin_views.py`:

- Add domain (`superadmin_add_tenant_domain`)
- Verify domain (`superadmin_verify_tenant_domain`)
- Set primary domain (`superadmin_set_primary_tenant_domain`)
  - Also syncs `Tenant.custom_domain` when primary is not temporary

### URL generation for tenant site

`get_tenant_public_home_url()` chooses URL preference:

1. Verified primary domain
2. Verified temporary domain
3. `tenant.custom_domain`
4. Generated temporary domain
5. Local fallback with `?tenant=<slug>` if needed

## 6) Branding Data Model and Defaults

Branding is stored in `TenantConfig.features['branding']` (JSON).

Core helper file: `myApp/utils/branding.py`.

### Default branding generation

`build_default_branding(tenant, profile)` builds copy/theme defaults from:

- Tenant name
- Optional `brand_profile` (teach topic, audience, promised outcome)

Includes:

- Brand labels, hero headline/copy
- Feature section copy
- Login/register/footer strings
- Theme mode and accent colors
- Optional logo/certificate URLs

### Ensure branding exists

`ensure_tenant_branding(tenant)` guarantees `features['branding']` exists.

Used in tenant creation/update flows to avoid missing-branding edge cases.

### Runtime branding retrieval

`get_tenant_branding(tenant)`:

- Loads defaults + stored branding overrides
- Validates and normalizes accent colors
- Derives contrast-safe on-colors (`accent_primary_on`, etc.)
- Falls back to `tenant.logo.url` if JSON logo URL is empty
- Returns platform-level defaults if tenant is `None`

## 7) Branding Management by Tenant Admin

`dashboard_branding_settings()` (`myApp/dashboard_views.py`) is the editor:

- Requires dashboard tenant context (`_get_dashboard_tenant`)
- Calls `ensure_tenant_branding(tenant)` before editing
- Supports updates for:
  - Text/copy fields
  - Theme mode + accent colors (validated hex)
  - Logo URL or uploaded logo file (Cloudinary flow)
  - Certificate template PDF upload
  - Custom HTML modes for landing/signup/login pages
- Persists to:
  - `TenantConfig.features['branding']`
  - `TenantConfig.features['custom_pages']`

## 8) How Branding Is Applied at Runtime

### Global template context

`tenant_context()` in `myApp/context_processors.py` injects:

- `tenant`
- `tenant_branding`
- `effective_theme_mode`
- `tenant_site_url`
- pending tenant notifications
- superadmin tenant picker context

### Effective theme precedence

Theme is resolved as:

1. Tenant branding default (`tenant_branding['theme_mode']`)
2. Per-user override from `TenantMembership.theme_preference` (if set)

### Tenant-specific page rendering

In `myApp/views.py`:

- `home()` renders platform page if no tenant, else tenant landing
- Custom page HTML (`custom_pages`) can override default templates for landing/login/signup

## 9) Login and Tenant Access Safety

`login_view()` enforces tenant membership on tenant-host login:

- If `request.tenant` is set and user is not superuser:
  - user must have active `TenantMembership` for that tenant
  - otherwise login is denied for that portal

Superusers can log in across tenants and access superadmin controls directly.

## 10) Tenant State Model (Operationally)

Main `Tenant` fields used operationally:

- `is_active`: tenant is allowed to operate
- `is_archived`: soft-delete/hide from normal lists
- `billing_status`: pending/active/past_due/canceled
- `plan_code`: current subscription tier code

Super admin actions:

- Suspend/activate toggles `is_active`
- Archive/unarchive toggles `is_archived` and deactivates on archive

This gives clear separation between billing state, access state, and archival state.

## 11) Quick End-to-End Summary

1. Tenant is created (superadmin or self-serve).
2. `TenantConfig` is ensured.
3. Branding defaults are seeded/ensured.
4. Temporary domain is ensured for immediate reachability.
5. Tenant admin membership is created and enforced.
6. Tenant/admin can refine branding and custom pages in dashboard.
7. Middleware + context processor keep tenant and branding scoped on every request.

