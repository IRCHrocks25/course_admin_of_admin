# Multi-Tenant + Admin-of-Admins Playbook

How this CourseForge platform was built, why it works this way, and how to reuse the same architecture for a **new product that is not courses**.

This is the document to copy from when you stand up another SaaS with:

- one **platform owner** (admin of admins / superadmin)
- many **customer accounts** (tenants)
- each tenant having its own **minor admins**
- each tenant having its own **end users** (members / customers / students)
- optional **white-label domains** (`acme.yourplatform.com` and `learn.acme.com`)

---

## 0) How to use this file

Read it in three layers:

1. **The idea** — sections 1–3. Why we did not use `django-tenants`, separate databases, or a `user.tenant` FK.
2. **How this repo actually works** — sections 4–14. Concrete models, middleware, login, dashboards, onboarding.
3. **How to rebuild it for a different product** — sections 15–17. Swap “Course” for whatever your new domain object is (projects, properties, clinics, stores, etc.).

Course-specific features (lessons, quizzes, Vimeo, Accredible, GHL, coupons) are **tenant-owned content**, not the tenancy system. You can throw them away and keep the tenancy core.

---

## 1) What we actually built

CourseForge is a **Django 5.1 monolith**:

| Piece | What it is |
|---|---|
| Project | `myProject/` (settings, urls, wsgi) |
| Domain app | `myApp/` (everything else) |
| Auth | Stock `django.contrib.auth.models.User` — **global**, not per-tenant |
| Tenancy library | **None.** Custom shared-database / shared-schema |
| Isolation | `tenant_id` FK on almost every domain table + host-based middleware |
| Admin of admins | `User.is_superuser` + `/superadmin/*` |
| Minor admins | `TenantMembership(role='tenant_admin')` + `User.is_staff` + `/dashboard/*` |
| End users | `TenantMembership(role='student')` + `/courses`, `/my-dashboard`, `/community` |

There is **no** Organization / School / Company / Academy model. The account boundary is simply `Tenant`. In this product a tenant is an “academy”. In your next product it is whatever you sell: a clinic, a brokerage, a store, a workspace.

### Mental picture

```
PLATFORM  (CourseForge / your new SaaS brand)
│
│  lives on PLATFORM_HOSTS  e.g. courseforge.example.com, localhost
│  owned by Super Admins (is_superuser)
│  sells plans, creates/suspends tenants, sees all analytics
│
├── Tenant A  "Acme Academy"   slug=acme    acme.courseforge.example.com
│   ├── Tenant Admins (minor admins)  → /dashboard
│   ├── Members / students
│   └── Acme's own content, branding, payments, domain
│
├── Tenant B  "Globex"         slug=globex  globex.courseforge.example.com
│   └── completely separate data, even if a course slug is also "intro"
│
└── Tenant C  custom domain    learn.someone.com
```

Same URL tree on every host (`/login`, `/dashboard`, `/`). Behavior changes because middleware sets `request.tenant` from the Host header.

---

## 2) Why this tenancy model (the design decision)

There are three common ways to do multi-tenant SaaS:

| Approach | Isolation | Cost / complexity | What we chose |
|---|---|---|---|
| **Separate database per tenant** | Strongest | Ops nightmare (migrations × N, backups × N) | No |
| **Separate Postgres schema per tenant** (`django-tenants`) | Strong | Needs schema routing, connection switching, harder local DX | No |
| **Shared DB + shared schema + `tenant_id`** | App-enforced | One migration, one backup, simple local SQLite | **Yes** |

We chose shared schema because:

1. This started as a **single-tenant course app**. Phase 1 was “add a Tenant FK and backfill everything into `slug=default`” without changing URLs. Schema-per-tenant would have been a rewrite.
2. Tenants share the same product features. They do not need independent schema evolution.
3. Superadmin must query **across** tenants (analytics, AI spend, notifications). Shared tables make that a normal queryset.
4. Local dev stays one `db.sqlite3` and `acme.lvh.me:8000`.

**The tradeoff you must accept:** isolation is **view-level**. A forgotten `.filter(tenant=tenant)` leaks data. Django `/admin/` sees everything. There is no Postgres RLS. Discipline + tests are the security boundary.

If your next product is healthcare / finance with a compliance requirement for physical isolation, do **not** copy this blindly — use schema-per-tenant or separate DBs. For most B2B SaaS (courses, agencies, CRM-ish tools, white-label portals), this model is the right default.

---

## 3) The three layers of authority

This is the part you will copy almost unchanged.

```
Django User  (one global table, username+email unique platform-wide)
│
├── is_superuser = True
│     ADMIN OF ADMINS  (platform superadmin)
│     • Does NOT need a TenantMembership
│     • Can log in on any host
│     • /superadmin/*  — create/suspend/archive tenants, pricing, global analytics
│     • Can “impersonate” a tenant via session and use /dashboard as if they were that tenant’s admin
│
├── is_staff = True
│   └── TenantMembership(role='tenant_admin', is_active=True)
│         MINOR ADMIN  (tenant admin / account admin)
│         • Scoped to one or more tenants
│         • /dashboard/*  — only that tenant’s data
│         • Can invite other tenant admins on THEIR tenant
│         • Cannot see other tenants, cannot open /superadmin
│
└── is_staff = False
    └── TenantMembership(role='student', is_active=True)
          END USER  (member / customer / student)
          • Tenant-branded public site + member area
          • Cannot open /dashboard or /superadmin
```

### Why two flags + a membership row (not one “role” field)

| Flag / row | Job |
|---|---|
| `User.is_superuser` | Platform god-mode. Django-native, already used by `/admin/`. |
| `User.is_staff` | Cheap gate for `/dashboard/*` (`staff_member_required`). Means “this person may see *some* tenant admin UI”. |
| `TenantMembership` | **Which** tenant, and **which** role inside it. This is the real authorization. |

`is_staff` alone is not enough — a staff user with no membership on tenant Acme must not manage Acme. Membership alone is not enough for dashboard routing — we reuse Django’s `user_passes_test(is_staff)` so every dashboard view does not re-check role.

When the last `tenant_admin` membership for a user is disabled, we also set `is_staff=False` (unless they still admin another tenant). That keeps the two in sync.

### A user can belong to multiple tenants

```
unique_together = [tenant, user]
```

Same person, one User row, two memberships. Logging into `acme.platform.com` vs `globex.platform.com` uses **host-scoped session cookies** (no `SESSION_COOKIE_DOMAIN`), so the two portals do not share a login.

Username/email are still globally unique. That is a product constraint: two academies cannot both register `bob@gmail.com` as different people. If your next product needs fully isolated identity per tenant, you must either:

- namespace usernames (`bob@acme` internally), or
- switch to email+tenant login and drop global uniqueness,

but that is a bigger auth change. We did not do it.

### Superadmin vs minor admin — who can do what

| Action | Superadmin | Tenant admin |
|---|---|---|
| Create / suspend / archive any tenant | Yes | No |
| Change platform pricing tiers | Yes | No |
| Broadcast notifications to all tenants | Yes | No |
| See cross-tenant analytics | Yes | No |
| Impersonate any tenant’s dashboard | Yes (session switcher) | No |
| Manage their tenant’s content | Yes, after picking a tenant | Yes, only theirs |
| Invite other admins on their tenant | Yes | Yes |
| Log in on a tenant host without membership | Yes | No — denied |
| Django `/admin/` | Yes | If `is_staff` — **dangerous**, not tenant-scoped |

---

## 4) Core data model (the tenancy core)

Copy these four models into any new product. Everything else is domain-specific.

### 4.1 `Tenant` — the account / workspace / customer org

```python
class Tenant(models.Model):
    name = CharField                    # display name
    slug = SlugField(unique=True)       # canonical ID + subdomain label
    custom_domain = CharField(unique, null=True)  # optional primary custom host
    is_active = BooleanField            # False = suspended; middleware ignores it
    is_archived = BooleanField          # soft-delete; also set is_active=False
    plan_code = CharField               # lean / baseline / growth / ...
    billing_status = CharField          # pending | active | past_due | canceled
    stripe_customer_id / stripe_subscription_id
    setup_fee_paid = BooleanField
    referral_code = CharField(unique)   # auto-generated on save
    referred_by = FK('self')            # referral graph
    created_at / updated_at
```

**Operational states you should keep:**

| Flag | Meaning | Effect |
|---|---|---|
| `is_active=False` | Suspended (billing fail, abuse, manual) | Middleware will not resolve this tenant. Portal looks “dead”. Data stays. |
| `is_archived=True` | Soft-deleted | Hidden from default superadmin lists. Also deactivated. Never hard-delete. |
| `billing_status=pending` | Signup started, not paid | Tenant exists so Stripe webhook can activate it. Abandoned checkouts get deleted so the username can be reused. |

`slug` is sacred. It becomes `acme.yourplatform.com`. Generate it server-side from the name (`slugify` + `-1`, `-2` suffix). Never let the customer type an arbitrary subdomain.

### 4.2 `TenantConfig` — OneToOne bag of settings

Keep `Tenant` skinny. Put integrations, feature flags, and branding JSON on `TenantConfig`:

```python
class TenantConfig(models.Model):
    tenant = OneToOneField(Tenant, related_name='config')
    features = JSONField(default=dict)   # branding, brand_profile, custom_pages, flags
    # plus whatever integrations the product needs
```

In this repo: Stripe Connect IDs, own Stripe keys, Vimeo team, chatbot webhook, Accredible issuer, branding JSON.

In your next product: whatever that tenant can configure (API keys, webhook URLs, theme, feature flags). **Do not store secrets in plaintext if you can avoid it** — this repo currently does for own-keys Stripe. Encrypt or use a secret manager in the new system.

Always `get_or_create` config the moment a tenant is created.

### 4.3 `TenantDomain` — how HTTP Host maps to a tenant

```python
class TenantDomain(models.Model):
    tenant = FK(Tenant, related_name='domains')
    domain = CharField(unique=True)     # "acme.platform.com" or "learn.acme.com"
    is_temporary = Boolean              # system subdomain, auto-verified
    is_primary = Boolean                # public home URL
    is_verified = Boolean               # DNS proven
    verification_notes = CharField
    unique_together = [tenant, domain]
```

Two kinds of domain:

1. **Temporary / automatic:** `{slug}.{PLATFORM_BASE_DOMAIN}` created by `ensure_temporary_domain()`. `is_temporary=True`, `is_verified=True`. Customer never types this.
2. **Custom:** tenant or superadmin adds `www.theirbrand.com`. Starts unverified. After DNS check, can be set primary. Primary custom domain is also copied onto `Tenant.custom_domain` as a fast lookup.

### 4.4 `TenantMembership` — the join table that makes multi-tenant users work

```python
class TenantMembership(models.Model):
    tenant = FK(Tenant)
    user = FK(User)
    role = CharField  # 'tenant_admin' | 'student'   (add more if you need)
    is_active = BooleanField
    must_change_password = BooleanField  # force rotate after invite
    unique_together = [tenant, user]
    indexes = [(tenant, role, is_active), (user, is_active)]
```

This is the most important table after `Tenant`.

- Login on a tenant host: “does this user have an active membership here?” Superusers skip this.
- Dashboard: “do they have `role=tenant_admin` on the resolved tenant?”
- Inviting a minor admin = create User (or reuse) + `is_staff=True` + membership `tenant_admin` + `must_change_password=True`.
- Registering an end user on a tenant host = create User + membership `student`.

**Do not put `tenant = FK` on User.** That would make a user belong to only one tenant and break “same person, two academies”.

### 4.5 Everything else gets a `tenant` FK

Rule: if a row is **owned by one customer account**, it has `tenant = ForeignKey(Tenant, on_delete=CASCADE)`.

In this product: Course, Lesson, Coupon, Bundle, ForumPost, Event, CourseAccess, …

In your next product: whatever the nouns are.

Uniqueness that used to be global becomes **tenant-scoped**:

```python
constraints = [
    UniqueConstraint(fields=['tenant', 'slug'], name='uniq_thing_tenant_slug'),
]
```

So Acme and Globex can both have `/products/intro`. Views must always do `Thing.objects.filter(slug=slug, tenant=tenant)`, never `get(slug=slug)`.

**Platform-wide tables** (no tenant FK, or tenant is the *subject* not the owner):

- `User` (global identity)
- `PricingTier` (what you sell to tenants)
- `StripeEventLog` (webhook idempotency)
- `TenantNotification` (one broadcast, many `TenantNotificationDelivery` rows)

---

## 5) How a request finds its tenant

Every request must answer: **“which tenant is this, or is this the platform itself?”**

### 5.1 Host lists in settings

```
PLATFORM_HOSTS=localhost,127.0.0.1,courseforge.example.com
PLATFORM_BASE_DOMAIN=courseforge.example.com
```

- `PLATFORM_HOSTS` → marketing site, `/start-academy/`, `/superadmin/`. `request.tenant` is **None**.
- `PLATFORM_BASE_DOMAIN` → wildcard DNS `*.courseforge.example.com` points at the app. Django also adds `.{PLATFORM_BASE_DOMAIN}` to `ALLOWED_HOSTS` and CSRF origins.
- Locally, DEBUG adds `.lvh.me` so `acme.lvh.me:8000` resolves to 127.0.0.1 without editing `/etc/hosts`.

### 5.2 `TenantMiddleware` (runs on every request)

File: `myApp/middleware.py`

Order of resolution:

```
1. Host in PLATFORM_HOSTS?
      Yes → tenant = None
            unless ?tenant=<slug>  (dev / preview only)
      No  → continue

2. TenantDomain.objects.filter(domain=host, is_verified=True,
                               tenant__is_active=True, tenant__is_archived=False)

3. Tenant.objects.filter(custom_domain=host, is_active=True, is_archived=False)

4. First DNS label as slug:  acme.anything.com  →  Tenant.slug == 'acme'
```

Then: `request.tenant = tenant` (object or `None`).

**Why platform hosts are empty:** the SaaS marketing page and superadmin console must not accidentally look like Acme’s academy. Superadmin then *opts in* to a tenant via the switcher.

**Why archived/inactive tenants are excluded:** suspending a customer instantly takes their subdomain offline without deleting data.

### 5.3 Second resolver (dashboard + AJAX)

Middleware only looks at the Host. On `localhost`, `request.tenant` is usually None even when the superadmin is “inside” Acme.

So views and the template context processor use a longer chain (`myApp/utils/tenancy.py` → `resolve_request_tenant`, and `_get_dashboard_tenant` in `dashboard_views.py`):

```
1. request.tenant                  (host)
2. If superuser:
      clear signals → session pop, return None     (Global Superadmin View)
      session['superadmin_tenant_id']              (impersonation)
      ?tenant=<slug>  (legacy GET; canonical path is POST /dashboard/set-tenant/)
3. Else:
      user's first active tenant_admin membership
      else first any active membership
```

This is what lets the admin of admins browse `/dashboard/courses` on localhost as if they were Acme, without logging into `acme.lvh.me`.

Canonical switcher: **POST `/dashboard/set-tenant/`** writes the session and redirects (PRG) so `?tenant=` does not linger in the URL and fight the chrome.

### 5.4 Context processor

`myApp/context_processors.py` → `tenant_context` injects into every template:

- `tenant`, `tenant_branding`, `effective_theme_mode`
- `tenant_site_url` (best public URL)
- `dashboard_available_tenants` (superadmin switcher list)
- `dashboard_impersonating`
- `pending_notification`

Templates stay tenant-aware without each view passing branding.

---

## 6) Authentication and “which tenant am I in?”

### 6.1 Login (`login_view`)

```
POST /login/ on acme.platform.com
  1. Middleware already set request.tenant = Acme
  2. authenticate(username, password) against the GLOBAL User table
  3. If tenant is set AND user is not superuser:
        require TenantMembership(tenant=Acme, user=user, is_active=True)
        else: "This account does not have access to this tenant portal."
  4. login() → session cookie for THIS host only
  5. If any membership has must_change_password → /force-password-change/
  6. Redirect:
        superuser → /superadmin/
        is_staff  → /dashboard/
        else      → member home (here: /courses/)
```

Superusers skip the membership check so they can enter any academy’s host for support.

### 6.2 Register

`/register/` **requires** `request.tenant`. On the platform host with no tenant, send people to `/start-academy/` (create a new account) instead of creating a floating user with no home.

New member: `User` + `TenantMembership(role='student')` on that tenant.

### 6.3 Sessions

- Default Django sessions. **No `SESSION_COOKIE_DOMAIN`.**
- Cookie is host-scoped: login on platform host ≠ login on `acme.platform.com`.
- Superadmin impersonation lives in `session['superadmin_tenant_id']`.
- Invited admins: `must_change_password` + `ForcePasswordChangeMiddleware` blocks the rest of the app until they rotate.

### 6.4 After login, tenant is NOT stored on the user

Re-resolved every request from host → session impersonation → membership. That is deliberate: the same User hitting two hosts is two different tenant contexts.

---

## 7) Superadmin console (admin of admins)

Prefix: `/superadmin/*`  
Guard: `superadmin_required` = `user_passes_test(is_superuser)`  
File: `myApp/superadmin_views.py`  
Templates: `myApp/templates/superadmin/`

### What it exists to do

This is **not** a second copy of the tenant dashboard. It is the control plane for the SaaS itself.

| Screen | Responsibility |
|---|---|
| Home | Counts: tenants, active, unpaid setup fees, plus rolled-up product metrics |
| Tenants list | Create tenant, bulk archive/restore |
| Tenant detail | Edit name/slug/domain/color, list admins, add domain, set Stripe keys, create a tenant admin |
| Suspend / activate | Flip `is_active` |
| Archive / restore | Soft-delete |
| Analytics | Per-tenant and global (in this app: courses, AI spend) |
| Pricing | `PricingTier` CRUD + Stripe price sync |
| Notifications | Broadcast modal/email to tenant admins |

### Creating a tenant by hand (superadmin)

```
POST /superadmin/tenants/
  validate name + slug unique
  Tenant.objects.create(...)
  TenantConfig.objects.get_or_create(tenant)
  ensure_tenant_branding(tenant)
  ensure_temporary_domain(tenant)   → acme.PLATFORM_BASE_DOMAIN
  redirect to tenant detail
```

Then `superadmin_create_tenant_admin`:

```
create or reuse User
user.is_staff = True
TenantMembership(role='tenant_admin', must_change_password=True)
```

No Stripe. Superadmin can gift a live tenant.

### Impersonation (the “admin of admins” trick)

From `/superadmin` or the dashboard chrome, pick a tenant. That POSTs `/dashboard/set-tenant/` and stores `superadmin_tenant_id`. Every subsequent `/dashboard/*` query is filtered to that tenant. Clearing returns “Global Superadmin View” (`request.tenant` stays None, dashboard may refuse tenant-scoped pages).

This is how one human supports 200 customers without 200 passwords.

---

## 8) Tenant admin console (minor admins)

Prefix: `/dashboard/*`  
Guard: `staff_member_required` (`is_staff`) **plus** `_get_dashboard_tenant()`  
File: `myApp/dashboard_views.py`  
Templates: `myApp/templates/dashboard/`

### Pattern every dashboard view follows

```python
@staff_member_required
def dashboard_something(request):
    tenant = _get_dashboard_tenant(request)
    if not request.user.is_superuser and tenant is None:
        messages.error(...)
        return redirect('somewhere_safe')

    qs = Thing.objects.all()
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    obj = get_object_or_404(Thing, slug=slug, tenant=tenant)
    ...
```

Never `Thing.objects.get(slug=slug)` — slugs collide across tenants.

### Minor admins inviting other minor admins

`/dashboard/tenant-admins/` — only if `_user_can_manage_tenant_admins` (superuser **or** active `tenant_admin` on this tenant).

- Create user or reuse existing username
- Temp password (generated if blank), email it
- `must_change_password=True`
- **Cannot disable the last remaining admin** on that tenant
- Disabling last `tenant_admin` membership across all tenants also clears `is_staff`

That is the whole “admin of admins, but each shop has its own managers” loop:

```
Superadmin creates Tenant + first tenant_admin
    → that person logs into THEIR subdomain
    → they add more tenant_admins
    → those people never see /superadmin
```

---

## 9) Two ways a tenant is born

### A) Self-serve (platform marketing → `/start-academy/`)

Only allowed when `request.tenant` is None (blocked on a tenant host — you are already inside an academy).

```
1. Form: org name, first admin user, plan, optional referral code
2. slugify(name), suffix -1/-2 until unique
3. Create Tenant(is_active=False, billing_status='pending', plan_code=...)
4. Create TenantConfig, seed branding JSON
5. Create User(is_active=False, not staff yet)  — placeholder until paid
6. Stripe Checkout (metadata: tenant_id, admin_user_id, plan_code)
   OR local DEBUG free path
7. On payment (webhook, or success-page fallback):
      tenant.is_active=True, billing_status='active', store Stripe ids
      ensure_tenant_branding, ensure_temporary_domain
      user.is_active=True, is_staff=True
      TenantMembership(role='tenant_admin')
8. Show “your academy is live at acme.platform.com”
9. Abandoned unpaid: checkout.session.expired deletes pending tenant + placeholder user
```

**Why pending + inactive first:** so a half-finished signup cannot occupy a live subdomain, but the webhook still has a row to activate.

### B) Superadmin manual

Covered in section 7. Immediate live tenant, no payment.

### After birth, always

1. `TenantConfig` exists  
2. Branding JSON exists  
3. Temporary domain exists and is verified  
4. At least one `tenant_admin` membership exists (self-serve after payment; manual after superadmin invites)

---

## 10) Domains and white-label

### Temporary subdomain

```
ensure_temporary_domain(tenant)
  domain = f"{tenant.slug}.{PLATFORM_BASE_DOMAIN}"
  get_or_create TenantDomain(is_temporary=True, is_verified=True, is_primary=True)
  unless a verified custom primary already exists
```

Requires wildcard DNS: `*.PLATFORM_BASE_DOMAIN → your app`.

### Custom domain

```
add domain (unverified)
customer points CNAME/A to the platform
verify (superadmin or tenant dashboard)
set primary → also write Tenant.custom_domain
temporary subdomain remains as fallback unless you choose otherwise
```

### Public URL helper

`get_tenant_public_home_url(request, tenant)`:

- Local request → `http://{slug}.lvh.me:{port}/` (never production URLs from DB)
- Else verified primary → verified temporary → `Tenant.custom_domain` → generated temporary
- HTTPS for real domains, HTTP-friendly for local

### CSRF / hosts

`ALLOWED_HOSTS` includes `.{PLATFORM_BASE_DOMAIN}` and `.lvh.me`.  
`CSRF_TRUSTED_ORIGINS` includes `https://*.{PLATFORM_BASE_DOMAIN}`.

Without the wildcard, the first tenant subdomain will 400 / CSRF-fail.

---

## 11) Isolation rules (copy these into the new codebase as law)

1. **Every tenant-owned query is filtered.** `Model.objects.filter(tenant=tenant)`. `get_object_or_404(..., tenant=tenant)`.
2. **Slugs are unique per tenant, never globally.** UniqueConstraint `(tenant, slug)`.
3. **Login on a tenant host requires membership** (except superuser).
4. **Dashboard requires is_staff + a resolved tenant** for non-superusers.
5. **Superadmin `/superadmin` is is_superuser only.** Tenant admins 403/redirect.
6. **Django `/admin/` is NOT tenant-scoped.** Treat it as a break-glass tool for superadmins only. In a new system, consider disabling it for `is_staff` who are not superusers.
7. **Do not trust `?tenant=` on production tenant hosts.** Middleware only honors it on `PLATFORM_HOSTS`.
8. **Soft-delete tenants** (`is_archived` + `is_active=False`). Never cascade-delete a paying customer’s data from a UI button.
9. **Write a two-tenant test.** Seed Acme + Globex. Tenant A admin must not 200 on tenant B’s object URLs. This repo: `myApp/tests/test_url_sweep.py` + `myApp/tests/base.py`.
10. **Prefer a helper** `_get_dashboard_tenant(request)` / `resolve_request_tenant(request)` over ad-hoc session reads so chrome, views, and AJAX agree.

### What we did *not* do (and you might want)

- Custom Manager that auto-filters by `request.tenant` (easy to forget in management commands / tasks where there is no request).
- Postgres RLS.
- Per-tenant User table.
- Separate URLConfs per tenant.

---

## 12) Billing pattern (optional, but the shape is reusable)

Two layers, do not mix them:

| Layer | Who pays whom | Where it lives |
|---|---|---|
| **Platform SaaS billing** | Tenant pays *you* for the product | `Tenant.plan_code`, `billing_status`, `stripe_customer_id`, `stripe_subscription_id`. Platform Stripe keys. Webhook `/webhooks/stripe/`. |
| **Tenant charges their users** | End users pay the tenant | Stripe Connect (charges on connected account) **or** tenant pastes their own sk/pk (webhook `/webhooks/stripe/tenant/<slug>/`). |

Activation of a self-serve tenant happens in the platform layer. Entitlements for end users (in this app: `CourseAccess`) happen in the tenant layer.

If your new product has no in-app payments, you still want platform billing if you charge monthly per tenant.

---

## 13) Branding / white-label

- Stored in `TenantConfig.features['branding']` (JSON), not a dozen columns.
- `ensure_tenant_branding(tenant)` seeds defaults from name/color.
- Context processor exposes `tenant_branding` on every page.
- Optional `features['custom_pages']` can replace landing/login/signup HTML.
- Theme: tenant default → membership `theme_preference` → session fallback (for superadmins with no membership).

Your new system can keep this exact JSON approach even if the UI is totally different.

---

## 14) How we got here (migration story — useful if you are converting an existing app)

We did **not** rewrite. We phased:

**Phase 1** (`Documents/MULTI_TENANT_MIGRATION_PHASE1.md`, migration `0018_multitenant_phase1.py`)

- Add `Tenant` + `TenantConfig`
- Add nullable `tenant` FK to existing tables
- Backfill every row onto `slug='default'`
- Change global unique slugs to `(tenant, slug)`
- App still behaves as one product; no middleware yet

**Phase 2+**

- `TenantMembership`
- `TenantMiddleware` + `PLATFORM_HOSTS` / `PLATFORM_BASE_DOMAIN`
- `/superadmin` + dashboard tenant switcher
- `TenantDomain` + `ensure_temporary_domain`
- `/start-academy/` + Stripe activation
- Branding JSON, custom domains, suspend/archive

Leftovers you should **not** copy:

- Many `tenant` FKs still `null=True`
- `get_default_tenant()` still papers over nulls
- `CURRENT_SYSTEM_STRUCTURE.md` describes the *pre*-multi-tenant app

For a **greenfield** system: make `tenant` FKs **non-null from day one**. No default tenant. No nullable ownership.

---

## 15) Mapping this onto a new (non-course) product

Replace the nouns. Keep the skeleton.

| This repo (courses) | Generic name | Example new product |
|---|---|---|
| Tenant / academy | Tenant / workspace / account | Clinic, brokerage, store, agency |
| Superadmin `/superadmin` | Platform console | Same |
| Tenant admin `/dashboard` | Account admin console | Same |
| Student / member | End user / client / customer | Patient, buyer, subscriber |
| Course | Primary content/object | Listing, project, program, location |
| CourseAccess | Entitlement | Subscription, seat, ticket |
| Lesson / module | Child objects | Rooms, tasks, SKUs |
| Coupon | Promo | Same idea |
| `/start-academy/` | `/start/` or `/signup-org/` | “Create your clinic” |
| `acme.courseforge…` | `{slug}.{PLATFORM_BASE_DOMAIN}` | `acme.yourproduct.com` |

### Suggested app layout for a new Django project

```
myProject/
  settings.py          # PLATFORM_HOSTS, PLATFORM_BASE_DOMAIN, middleware order
  urls.py              # same tree on every host
myApp/
  models.py            # Tenant, TenantConfig, TenantDomain, TenantMembership + YOUR nouns
  middleware.py        # TenantMiddleware (+ optional ForcePasswordChange)
  utils/tenancy.py     # resolve_request_tenant, is_clear_tenant_requested
  utils/domains.py     # ensure_temporary_domain, get_tenant_public_home_url
  context_processors.py
  views.py             # public site + auth + onboarding
  dashboard_views.py   # minor admin console
  superadmin_views.py  # admin of admins
  templates/
    platform/          # marketing + start
    dashboard/
    superadmin/
    (your member UI)
```

### Middleware order that matters

```
SessionMiddleware
TenantMiddleware          # needs to run early; sets request.tenant
Common / Locale / CSRF
AuthenticationMiddleware  # user available after this
ForcePasswordChangeMiddleware
```

`TenantMiddleware` does not need the user. Impersonation is applied later in views/context because it needs `request.user` + session.

### URL map to copy

```
/                      platform marketing OR tenant landing   (depends on request.tenant)
/start/                create a tenant (platform host only)
/login/ /logout/ /register/
/dashboard/            minor admin (is_staff + membership)
/dashboard/set-tenant/ superadmin impersonation POST
/dashboard/admins/     invite/disable minor admins
/superadmin/           admin of admins only
/admin/                Django admin — superuser only in a new system
/webhooks/stripe/      platform billing
```

### Minimum views to implement first

1. `TenantMiddleware` + empty home that prints `request.tenant`
2. Superadmin: create tenant + create tenant admin
3. Login with membership check
4. Dashboard home that 403s without tenant and lists only that tenant’s objects
5. `ensure_temporary_domain` + lvh.me locally
6. Start-org flow (even if “free”, skip Stripe until later)
7. Isolation test: two tenants, two admins, cross-URL must fail

Do **not** start with custom domains, Connect, or branding JSON. Those are layer 2.

---

## 16) Concrete request flows (copy these into onboarding docs)

### End user on a tenant host

```
Browser → acme.yourproduct.com/login
  TenantMiddleware: host not in PLATFORM_HOSTS
    TenantDomain or slug "acme" → request.tenant = Acme
  login_view: authenticate + membership required
  session cookie for acme.yourproduct.com
  redirect to member home
  all querysets filter(tenant=Acme)
```

### Minor admin

```
Same login
  user.is_staff and membership.role=tenant_admin
  redirect /dashboard/
  _get_dashboard_tenant() → Acme
  dashboard only shows Acme rows
```

### Admin of admins on the platform host

```
localhost/login  (no tenant)
  is_superuser → /superadmin/
  sees all tenants
  POST /dashboard/set-tenant/ tenant=acme
  session['superadmin_tenant_id'] = acme.id
  /dashboard/ now filtered to Acme
  chrome shows “Tenant View: Acme”
  clear → Global Superadmin View
```

### New customer signs up

```
yourproduct.com/start
  create pending Tenant + inactive admin User
  pay (or free-local)
  activate: is_active, is_staff, membership, temporary domain
  “Go to acme.yourproduct.com/login”
```

---

## 17) Build checklist for the new system

### Data

- [ ] `Tenant` with slug, is_active, is_archived, plan/billing fields as needed
- [ ] `TenantConfig` OneToOne, created in the same transaction as Tenant
- [ ] `TenantDomain` + `ensure_temporary_domain`
- [ ] `TenantMembership` with at least `tenant_admin` and `member`
- [ ] Every domain model has non-null `tenant` FK + `(tenant, slug)` uniqueness
- [ ] No `tenant` FK on `User`

### Request / auth

- [ ] `PLATFORM_HOSTS` and `PLATFORM_BASE_DOMAIN` env vars
- [ ] Wildcard DNS + `ALLOWED_HOSTS` / CSRF for `*.base`
- [ ] `TenantMiddleware` exactly as in this repo (host → domain → custom → slug)
- [ ] Login membership gate (superuser bypass)
- [ ] Host-scoped sessions (do not set `SESSION_COOKIE_DOMAIN` unless you *want* SSO across subdomains)
- [ ] `must_change_password` on invited admins

### Two consoles

- [ ] `/superadmin` — `is_superuser` only: tenants CRUD, suspend, archive, create first admin, analytics
- [ ] `/dashboard` — `is_staff` + membership: only that tenant’s data
- [ ] Superadmin tenant switcher via session + POST (not only `?tenant=`)
- [ ] Tenant admins can invite/disable other tenant admins; cannot remove the last one

### Safety

- [ ] Two-tenant fixture + URL sweep test
- [ ] Archive = hide + deactivate, not delete
- [ ] Django admin restricted to superusers
- [ ] Every list/detail/update/delete view reviewed for missing `tenant=` filter

### Later

- [ ] Self-serve checkout + webhook activation
- [ ] Custom domains + verify
- [ ] Branding JSON
- [ ] Platform Stripe vs tenant Stripe
- [ ] Referrals

---

## 18) File map in *this* repo (source of truth)

| File | Why it matters |
|---|---|
| `myApp/models.py` | `Tenant`, `TenantConfig`, `TenantDomain`, `TenantMembership`, all tenant FKs |
| `myApp/middleware.py` | `TenantMiddleware` + password-change + throttles |
| `myApp/utils/tenancy.py` | Shared resolver + clear-impersonation signals |
| `myApp/utils/domains.py` | Temporary/custom domain helpers |
| `myApp/utils/branding.py` | Branding JSON |
| `myApp/context_processors.py` | Templates always know the tenant |
| `myApp/views.py` | Login, register, start-academy, Stripe activation, public tenant site |
| `myApp/dashboard_views.py` | Minor admin UI, `_get_dashboard_tenant`, tenant-admins, set-tenant |
| `myApp/superadmin_views.py` | Admin of admins |
| `myProject/settings.py` | Hosts, middleware order, CSRF |
| `myProject/urls.py` | One URLConf for platform + all tenants |
| `myApp/migrations/0018_multitenant_phase1.py` | How tenancy was grafted onto the old app |
| `myApp/tests/base.py` | Acme / Globex seed |
| `myApp/tests/test_url_sweep.py` | Cross-tenant isolation |

Related shorter docs (detail, not overview):

- `Documents/ADMIN_OF_ADMINS_TENANT_AND_BRANDING_LOGIC.md`
- `Documents/AUTOMATIC_SUBDOMAIN_CREATION_FLOW.md`
- `Documents/MULTI_TENANT_MIGRATION_PHASE1.md`
- `Documents/STRIPE_INTEGRATION_RUNBOOK.md`

---

## 19) Gotchas we learned the hard way

1. **A missed filter is a data leak.** There is no database safety net.
2. **Global usernames.** Two customers cannot both “own” `admin`. Plan for that in UX (or namespace later).
3. **`is_staff` vs role.** Deactivate membership and forget `is_staff` → they still pass `staff_member_required` until the next check. Keep them in sync.
4. **Nullable tenant FKs.** Phase 1 leftover. Greenfield: `null=False`.
5. **Slug collision on custom domains.** Resolution checks verified `TenantDomain` first, then `custom_domain`, then first label. A custom host `acme.other.com` could otherwise steal slug `acme`.
6. **`?tenant=` on platform hosts vs POST switcher.** GET leftover in the URL caused the chrome to say Global while the view still loaded the old tenant. Canonical path is POST `/dashboard/set-tenant/` and strip query params.
7. **AJAX POSTs** do not carry `?tenant=`. Always use `resolve_request_tenant()` so they see the same tenant as the page.
8. **Sessions do not follow you** from `platform.com` to `acme.platform.com`. Superadmin support on a tenant host means logging in again there (or only impersonating from the platform host).
9. **GHL OAuth (and any third-party callback)** is one global URL; put `tenant_id` in signed state, then redirect to the tenant host. Do not try to register N callback URLs.
10. **Abandoned signups.** If you create User+Tenant before payment, delete them on `checkout.session.expired` or usernames get permanently burned.
11. **Local subdomains.** Use `lvh.me`, not `localhost` with fake prefixes. `acme.localhost` is inconsistent across browsers.
12. **Superadmin recovery on slug collision.** `_resolve_dashboard_course` has extra fallbacks because slugs repeat. In a new app, still always require tenant context rather than “pick the newest row”.

---

## 20) One-sentence summary

**One global User table, a Tenant row per customer, a Membership row that says who is a minor admin vs a member, host-based middleware to pick the tenant, a `/superadmin` console for the platform owner, a `/dashboard` console that is always filtered to one tenant, and temporary `{slug}.yourplatform.com` domains so every customer gets a live portal without waiting on DNS.**

Courses, lessons, coupons, GHL, and AI generation are features *inside* a tenant. The tenancy system does not care what you store there — only that every row points at a tenant and every view respects it.
