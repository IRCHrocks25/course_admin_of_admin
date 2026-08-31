# Courses & Custom Landing Pages

Architecture reference for how courses and custom landing pages work in this Django project. No secrets are included.

**Django:** `5.1.2` (`requirements.txt` / `Django==5.1.2`)  
**Related packages:** `djangorestframework==3.15.2` is listed but **not wired** into `INSTALLED_APPS` or URL routing — there are no DRF serializers/viewsets for courses or landing pages.

---

## 1. Important scope distinction

**Custom landing pages are tenant-scoped, not course-scoped.**

There is no `CourseLandingPage` model and no per-course custom HTML store. Each academy (`Tenant`) has one public landing experience at `/` (on that tenant’s domain). Courses appear on that landing via:

- default template copy / CTAs,
- injected placeholders in custom HTML (`__TENANT_COURSES_LIST__`, etc.),
- or CMS/link targets pointing at `/register/?course=<slug>`, `/courses/<slug>/`, `/login/`, etc.

Course “pages” are separate: `/courses/<slug>/` renders the authenticated course detail / syllabus UI (`course_detail.html`), not a marketing landing CMS.

---

## 2. Project layout

```
course_admin_of_admin/
├── manage.py
├── requirements.txt
├── myProject/                 # Django project package
│   ├── settings.py
│   ├── urls.py                # All URL routes (single urls module)
│   ├── wsgi.py / asgi.py
├── myApp/                     # Main (only) application
│   ├── models.py              # Tenant, Course, Lesson, access, commerce, …
│   ├── views.py               # Public student/tenant surfaces (home, courses, auth, checkout)
│   ├── dashboard_views.py     # Tenant-admin dashboard (branding, CMS, courses CRUD)
│   ├── superadmin_views.py    # Platform superadmin
│   ├── middleware.py          # TenantMiddleware, throttling, etc.
│   ├── context_processors.py  # tenant_branding injection
│   ├── utils/branding.py      # Branding defaults + TenantConfig.features['branding']
│   ├── cms/                   # Annotation-based landing CMS
│   │   ├── storage.py         # Persist template/content on TenantConfig
│   │   ├── parser.py          # Build editable schema from annotated HTML
│   │   ├── renderer.py        # Merge content → HTML
│   │   ├── annotator.py / ai_annotator.py / html_utils.py / templates.py
│   ├── branding_templates/    # Default CMS landing HTML seed
│   ├── templates/
│   │   ├── landing.html + landing/_*.html   # Default tenant landing
│   │   ├── tenant/custom_landing_fragment.html
│   │   ├── course_detail.html
│   │   ├── dashboard/branding_settings.html
│   │   ├── dashboard/cms_landing_editor.html
│   │   └── platform/home.html               # Platform (no-tenant) acquisition page
│   └── static/ …
└── Documents/                 # Internal docs (this file)
```

**Installed Django apps (relevant):** `myApp`, `cloudinary` / `cloudinary_storage`, `django_tasks` / `django_tasks_db`, plus Django contrib. There is no separate “courses” or “landing” app.

---

## 3. Multi-tenant host resolution

`TenantMiddleware` (`myApp/middleware.py`) sets `request.tenant`:

| Host kind | Resolution |
|-----------|------------|
| Platform hosts (`PLATFORM_HOSTS`, e.g. localhost) | `tenant = None`, unless `?tenant=<slug>` for local preview |
| Verified `TenantDomain.domain` | That tenant |
| `Tenant.custom_domain` | That tenant |
| Subdomain first label matching `Tenant.slug` | That tenant |

Landing, register, login, and course URLs are always interpreted in that tenant context.

---

## 4. Course identification

### Primary keys & uniqueness

| Identifier | Role |
|------------|------|
| **`Course.id`** | Integer PK (DB / some internal APIs, e.g. favorite toggle) |
| **`Course.slug`** | Public URL key; unique **per tenant** (`uniq_course_tenant_slug`) |
| **`Course.tenant`** | FK to `Tenant` (academy ownership) |
| UUID | **Not used** on `Course` |

URL pattern: `/courses/<slug:course_slug>/…`

Lookup helper: `course_queryset_for_slug(request, course_slug)` in `myApp/views.py` — filters by `request.tenant` when present so duplicate slugs across academies do not collide.

Lessons: unique on `(tenant, course, slug)` → `/courses/<course_slug>/<lesson_slug>/`.

### Core `Course` fields (summary)

Defined in `myApp/models.py`:

- Identity / catalog: `name`, `slug`, `category`, `display_order`, `course_type`, `status`, `description`, `short_description`, `thumbnail`, `coach_name`
- Commerce / access: `price`, `member_price`, `included_in_membership`, `grants_membership_months`, `grants_membership_tier`, `visibility`, `enrollment_method`, access-duration fields, `prerequisite_courses`
- Other: `creation_blueprint` (CourseForge JSON), timestamps

**Related course models:** `Module`, `Lesson`, `CourseEnrollment`, `CourseAccess`, `CourseResource`, `CourseTranslation`, `FavoriteCourse`, `Exam` / attempts, `Certification`, `Bundle` (M2M courses), coupons, learning paths, etc.

Access truth source: **`CourseAccess`** (“access is a thing, not a side effect”). `CourseEnrollment` remains for legacy/progress/exam helpers.

---

## 5. How landing pages are stored & associated

Association is **Tenant → TenantConfig.features['custom_pages']**, not Course → landing.

```
Tenant
  └── TenantConfig (OneToOne)
        └── features (JSONField)
              ├── branding          # copy, logos, accents (utils/branding.py)
              └── custom_pages
                    ├── landing_mode          # 'default' | 'cms' | 'custom'
                    ├── landing_html          # raw HTML when mode=custom
                    ├── landing_cms_template_html
                    ├── landing_cms_content   # { section: { field: value } }
                    ├── landing_cms_published # bool
                    ├── signup_mode / signup_html
                    └── login_mode / login_html
```

Persistence helpers: `myApp/cms/storage.py` (`get_landing_cms_template_html`, `save_landing_cms_content`, `set_landing_cms_published`, …).

### Three landing modes

| Mode | Storage | Public render |
|------|---------|---------------|
| **default** | Branding JSON + Django templates | `landing.html` (+ `landing/_*.html` partials) |
| **custom** | `custom_pages['landing_html']` | `_render_tenant_custom_html()` — full HTML document or fragment |
| **cms** | Template HTML + content JSON + publish flag | `_render_tenant_cms_landing()` → merge via `cms/renderer.render_site` |

CMS unpublished drafts: only visible to authenticated **staff** on `/` (preview). Guests see fallback until published.

### Custom HTML placeholders (runtime)

In `_render_tenant_custom_html()`:

- `__TENANT_LOGO_URL__`, `__TENANT_BRAND_NAME__`
- `__TENANT_COURSE_COUNT__`, `__TENANT_COURSES_LIST__` (links to `/courses/<slug>/`)

CTA rewrite script maps ambiguous buttons/links toward `/register/`, `/login/`, `/courses/` when `data-action` / button text matches enroll/login/courses.

Login/signup can independently use custom HTML (`login_mode` / `signup_mode`).

---

## 6. Admin UI (landing management)

**Route:** `/dashboard/branding-settings/` → `dashboard_branding_settings`  
**Template:** `dashboard/branding_settings.html`  
**Auth:** Staff dashboard (`login_required` + `is_staff`); tenant context via `_get_dashboard_tenant`.

**Landing tab:**

- Mode selector: platform template / Visual CMS / custom HTML
- Custom: file upload or paste; requires `<style>` or stylesheet `<link>`; optional clear
- CMS: link to **Open Visual Editor**

**Visual CMS editor:**

| Path | Name | Purpose |
|------|------|---------|
| `/dashboard/branding-settings/landing-cms/` | `dashboard_landing_cms_editor` | Editor UI (`cms_landing_editor.html`) |
| `…/landing-cms/save/` | `dashboard_landing_cms_save` | Persist content JSON |
| `…/landing-cms/preview/` | `dashboard_landing_cms_preview` | Iframe preview |
| `…/landing-cms/publish/` | `dashboard_landing_cms_publish` | Flip `landing_cms_published` |
| `…/landing-cms/upload-image/` | … | Image upload |
| `…/landing-cms/import-html/` | … | Import/annotate HTML as CMS template |
| `…/landing-cms/reset-template/` | … | Reset to default template |
| `…/landing-cms/annotate-element/` / `remove-annotation/` | … | Click-to-annotate fields |

Frontend for the CMS is **server-rendered HTML + inline JS** in `cms_landing_editor.html` (iframe preview + `postMessage` bridge from `cms/renderer.py`). There is no separate React/Vue SPA for landing pages.

> Screenshots: open Branding Settings → **Landing Page** tab, and/or **Open Visual Editor**, while logged in as a tenant admin. This doc does not embed live UI captures.

---

## 7. What happens when someone visits the landing URL

### Entry: `GET /` → `views.home`

```
request.tenant is None?
  → platform/home.html (creator acquisition)

else:
  landing_mode == cms and (published OR staff)?
    → render CMS HTML (HttpResponse full doc)
  landing_mode == custom and landing_html?
    → render custom HTML (+ CTA/CSRF helpers)
  else
    → landing.html with tenant branding + course_count
```

### From landing → registration / login / catalog / course

Typical paths (also driven by custom HTML links):

```
Landing (/)
  ├─ CTA “Sign up” / enroll language  → /register/  (optional ?plan= / ?course=<slug> / ?next=)
  ├─ CTA “Log in”                     → /login/
  ├─ CTA “Courses” / curriculum       → /courses/   (guest catalog or hub)
  └─ Course list placeholder links    → /courses/<slug>/  (requires login → redirect to login)
```

**Registration intent** (`_registration_intent` / `_post_auth_redirect` in `views.py`):

- `?plan=month|year|…` → after auth, courses hub with `?start_membership=…` (membership checkout)
- `?course=<slug>` → after auth, `course_detail` for that slug (if it exists on the tenant)
- `?next=` → allowed same-host redirect

Payment-first membership signup: account held in `PendingRegistration` until Stripe success (`/register/complete/`).

### Course detail → enroll / checkout / lessons

`GET /courses/<slug>/` → `course_detail` (**`@login_required`**):

| Situation | Outcome |
|-----------|---------|
| Already has `CourseAccess` | Syllabus / continue lesson |
| `enrollment_method == 'open'` + prereqs | Can self-enroll via `POST/GET` `…/enroll/` → grant access + optional first lesson |
| Paid + Stripe ready | `…/checkout/` → Stripe Checkout → `…/checkout-success/` → access granted |
| Invite / cohort / purchase without Stripe | Message + stay on detail / contact admin |

Then: `/courses/<slug>/<lesson_slug>/` (lesson player), quizzes, certificates, student dashboard.

Guest-visible catalog without logging into a specific course: **`/courses/`** can render a guest catalog (`is_guest_view`) when unauthenticated.

---

## 8. Relevant URL map (landing + courses)

### Public

| URL | View | Notes |
|-----|------|-------|
| `/` | `home` | Tenant landing or platform home |
| `/login/`, `/register/`, `/signup/` | auth | Custom HTML modes supported |
| `/courses/` | `courses` | Hub / guest catalog |
| `/courses/<slug>/` | `course_detail` | Login required |
| `/courses/<slug>/enroll/` | `enroll_course` | Login required |
| `/courses/<slug>/checkout/` | `create_course_checkout_session` | Stripe |
| `/courses/<slug>/<lesson_slug>/` | `lesson_detail` | Login required |

### Dashboard (staff)

| URL | View |
|-----|------|
| `/dashboard/courses/` … | Course CRUD / lessons / PDF import |
| `/dashboard/branding-settings/` | Branding + landing modes |
| `/dashboard/branding-settings/landing-cms/…` | CMS editor APIs |

Full route list: `myProject/urls.py`.

---

## 9. Authentication & permissions

| Surface | Gate |
|---------|------|
| Tenant landing `/` | Public |
| Register / login | Public (tenant must be active); login requires active `TenantMembership` on that tenant (non-superuser) |
| Course detail / lessons / enroll | `@login_required` |
| Dashboard branding / CMS / course admin | Staff (`is_staff`); tenant-scoped via dashboard tenant helper; superusers can cross-tenant |
| Superadmin `/superadmin/…` | Superuser |
| CMS unpublished landing preview | Staff only |

Role linkage: `TenantMembership` (`role` e.g. `tenant_admin`, `must_change_password`, theme preference). Force-password middleware can intercept before normal navigation.

---

## 10. APIs another system could consume

**No first-class public Course or Landing REST API** (no serializers module; DRF not in `INSTALLED_APPS`).

What exists today:

| Endpoint pattern | Audience | Notes |
|------------------|----------|-------|
| `/api/courses/<int:course_id>/favorite/` | Logged-in student | Toggle favorite by **integer** course id |
| `/api/lessons/<id>/progress/`, `/complete/` | Logged-in student | Progress tracking |
| `/api/lessons/<id>/chatbot/`, `/train-chatbot/` | Lesson AI coach | Session/auth as implemented |
| `/api/chatbot/` | Webhook-style | Chatbot integration |
| `/api/preferences/language/`, `/api/theme/toggle/` | Session UX | |
| `/dashboard/branding-settings/landing-cms/*` | Staff session + CSRF | JSON-ish editor endpoints, **not** a public CMS API |
| `/dashboard/api/ai-generation-status/<course_id>/` | Staff | CourseForge polling |
| Stripe / GHL webhooks | External systems → this app | Inbound only |

**Implication for an external system:** you cannot currently fetch “landing HTML for course X” or a stable public course catalog API without adding new authenticated endpoints (or scraping HTML). Landing content lives in `TenantConfig.features`; course metadata lives in the `Course` ORM. Prefer new explicit read APIs if another product must consume this data.

---

## 11. Key code entry points

| Concern | Location |
|---------|----------|
| Course model | `myApp/models.py` → `Course` |
| Landing render | `myApp/views.py` → `home`, `_render_tenant_custom_html`, `_render_tenant_cms_landing` |
| Branding read/write | `myApp/utils/branding.py`, `dashboard_branding_settings` |
| CMS store/render | `myApp/cms/storage.py`, `renderer.py`, `parser.py` |
| Access checks | `myApp/utils/access.py` (imported by enroll/detail) |
| URLs | `myProject/urls.py` |
| Default landing template | `myApp/templates/landing.html` |
| Course detail template | `myApp/templates/course_detail.html` |

---

## 12. Related docs in this repo

- `Documents/ADMIN_OF_ADMINS_TENANT_AND_BRANDING_LOGIC.md` — tenant + branding persistence
- `Documents/MULTI_TENANT_ADMIN_OF_ADMINS_PLAYBOOK.md` — multi-tenant playbook
- `Documents/LANDING_PAGE_TEXT_CONTENT.md` — default landing copy notes
- `Documents/COURSE_SYSTEM_COMPLETE_DOCUMENTATION.md` — broader course/LMS behavior

---

*Generated as an architecture snapshot of the codebase. Update this file when landing modes or course URL contracts change.*
