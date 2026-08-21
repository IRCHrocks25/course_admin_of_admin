# Weekly Wrap — Week of Aug 11, 2026

What shipped this week for CourseForge / Bobby Davidowitz tenant work.

---

## 1) Coupons + QR codes (main deliverable)

Tenant admins can create coupons under **Dashboard → Commerce & Settings → Coupons**.

### What it does
- Create a coupon with name, code, optional discount, destination, max uses, and expiry
- Auto-builds a **shareable public link**: `/c/YOURCODE/`
- **Generate QR** on the edit page → PNG uploaded to **Iceberg** → CDN URL saved on the coupon
- Opening the link stores the coupon in session and redirects to the chosen destination
- Checkout for courses/bundles applies percent or fixed discounts when applicable

### Coupon types
| Type | Behavior |
|------|----------|
| **Percent / fixed discount** | Price off at checkout; use counted on purchase |
| **No discount (tracking only)** | No price change; records which coupon a student used at signup |

### Destinations (where the link sends people)
- Tenant signup page
- Specific course
- Specific bundle
- Custom URL
- Site home

### Student attribution
- Student opens `/c/CODE/` → coupon stashed in session
- On register, coupon is saved on their membership as **signup coupon**
- Visible on:
  - **Students list** — coupon badge next to student info
  - **Student detail** — signup coupon code/name under join date

### Where to use it
1. **Dashboard → Coupons → New Coupon**
2. After create, copy the shareable link
3. Click **Generate QR** (Iceberg must be configured)
4. Share link or QR (flyers, SMS, landing pages, etc.)

### Key files
- `myApp/models.py` — `Coupon` model
- `myApp/utils/coupons.py` — link build, QR PNG, Iceberg upload, session helpers
- `myApp/utils/iceberg.py` — byte upload support for QR images
- `myApp/dashboard_views.py` — coupon CRUD + QR regenerate
- `myApp/views.py` — `coupon_landing`, checkout discount wiring
- Templates: `dashboard/coupons.html`, `add_coupon.html`, `edit_coupon.html`
- Migrations: `0054_coupon`, `0055_coupon_tracking_signup`, `0056_coupon_target_signup`

### Note from testing
QR upload needs a valid Iceberg API token in the running server env. A stale token surfaces as upload failure (401); refreshing `.env` / restarting the process fixed it during local testing.

---

## 2) Lesson floating CTA bubble

Tenant-configurable floating CTA on lesson (and quiz) pages so students can jump out to a booking/contact URL without leaving the course flow.

### Admin controls (Branding settings)
- Enable / disable
- Redirect URL (tenant-controlled)
- Label text
- Style: icon-only, word/pill, or full sentence bar
- Open in new tab

### Behavior
- Shows across lessons for that tenant when enabled
- Config stored in `TenantConfig.features['lesson_cta']`

### Key files
- `myApp/utils/branding.py` — `get_lesson_cta()`
- `myApp/templates/_lesson_cta_bubble.html`
- `myApp/templates/lesson.html`, `lesson_quiz.html`
- `myApp/templates/dashboard/branding_settings.html`
- Commit: `7d893ad` — *added lesson cta bubble*

---

## 3) Bobby Davidowitz landing pages

Static / marketing HTML pages added and polished for Bobby’s funnels (including QR / text CTAs on-page):

- `myApp/templates/htmls/bobby.html`
- `myApp/templates/htmls/bobby-davidowitz-partner-on-a-deal.html`
- `myApp/templates/htmls/bobby-davidowitz-get-in-the-game.html`

Work included aligning deal/game forms to shared CTA patterns (Partner with Bobby / Become an Agent, Sign in / Get started) and button styling upgrades.

---

## 4) Docs (later in the week)

- `Documents/MULTI_TENANT_ADMIN_OF_ADMINS_PLAYBOOK.md` — how the multi-tenant + admin-of-admins model works and how to reuse it for a non-course product (written Thu Aug 13).

---

## Commits this week

| Date | Commit | Summary |
|------|--------|---------|
| Aug 11 | `7d893ad` | Lesson CTA bubble + branding controls |
| Aug 11 | `964ec53` | Coupons, QR/Iceberg, tracking on students, Bobby HTML pages |

---

## Quick “done” checklist

- [x] Coupons CRUD in tenant admin
- [x] Shareable coupon links (`/c/<code>/`)
- [x] QR generation + Iceberg storage
- [x] Tracking-only coupons recorded on student signup
- [x] Discount coupons applied at course/bundle checkout
- [x] Lesson floating CTA configurable per tenant
- [x] Bobby landing page templates updated

---

*Period covered: ~Aug 11–15, 2026 (primary ship day Aug 11).*
