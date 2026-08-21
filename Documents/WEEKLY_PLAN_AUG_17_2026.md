# Weekly Plan — Week of Aug 17, 2026

How we improve CourseForge this week. Builds on last week’s ship (coupons + QR, lesson CTA bubble, Bobby landings, multi-tenant playbook).

**Theme:** Harden what we shipped → finish GHL sidebar embed → give tenant admins one clear “how is this working?” view.

---

## North star (end of week)

By Friday Aug 21, we want:

1. Coupons production-ready (polish, reporting, fewer “it broke because Iceberg token” moments)
2. GHL sidebar embed usable end-to-end on at least one DEV / pilot tenant
3. One lightweight coupon / funnel insight surface so Bobby (and other tenants) can see which codes convert
4. Uncommitted template polish from last week merged and verified

---

## Priority stack

| P | Workstream | Why this week |
|---|------------|---------------|
| P0 | Coupon polish + ops | Shipped Aug 11; still has local UI diffs + Iceberg token fragility |
| P0 | GHL sidebar embed | Spec + partial work already exist; highest leverage for agency tenants |
| P1 | Coupon / attribution reporting | Coupons are useless without “which code drove signups/sales” |
| P1 | Bobby funnel QA | Landings + QR/coupon paths are live marketing surfaces |
| P2 | Analytics MVP slice | Don’t boil the ocean — one dashboard card, not the full proposal |
| P2 | Docs / wrap | Keep the Aug 11 wrap + this plan as the week’s source of truth |

---

## Day-by-day plan

### Mon Aug 17 — Close the loop on last week

**Focus:** Ship the unfinished coupon + Bobby template polish; reset priorities.

- [ ] Review + merge local diffs:
  - `dashboard/coupons.html`, `add_coupon.html`, `edit_coupon.html`
  - `bobby-davidowitz-get-in-the-game.html`, `bobby-davidowitz-partner-on-a-deal.html`
- [ ] Commit / document `WEEKLY_WRAP_AUG_11_2026.md` + playbook if not already on `main`
- [ ] Smoke-test coupon path on a real tenant host:
  - create → share link → QR generate → open `/c/CODE/` → signup attribution badge
  - discount coupon at course + bundle checkout
- [ ] Confirm Iceberg env token is valid in the env you’ll use this week (local + Railway if applicable)
- [ ] Agree this plan’s P0/P1 order with the team (adjust if a client ask jumps the queue)

**Done when:** last week’s UI polish is committed; coupon happy-path works without a 401 on QR upload.

---

### Tue Aug 18 — Coupons: reporting + admin UX

**Focus:** Make coupons measurable and easier to manage.

- [ ] Coupon list enhancements:
  - show use count / max uses, expiry status, destination type
  - filter or badge for discount vs tracking-only
- [ ] Basic attribution report (tenant-scoped):
  - signups per coupon (from membership signup coupon)
  - purchases / redemptions per coupon (where use is counted)
  - simple table on Coupons page or a “Coupon performance” panel
- [ ] Edge cases:
  - expired / maxed coupons → clear student-facing message
  - regenerate QR after code change (if allowed) or lock code after create
- [ ] Copy QR CDN URL + shareable link actions that are obvious on edit page

**Done when:** a tenant admin can answer “which coupon drove the most signups this week?” without opening the DB.

---

### Wed Aug 19 — GHL sidebar embed (core path)

**Focus:** Follow `Documents/GHL_SIDEBAR_EMBED_PLAN.md` / design; get the happy path working.

Reference: existing GHL commits already cover connect UI, calendar sync, embed handshake diagnostics — finish the Custom Page SSO loop.

- [ ] Confirm DEV marketplace app + HTTPS tunnel prerequisites
- [ ] Implement / harden (as needed per plan):
  - `/ghl/embed` → User Context decrypt → tenant resolve
  - one-time SSO hop to tenant host → dashboard in iframe
  - frame-ancestors / cookie flags for Secure embed
- [ ] Unauthorized / not-connected / error templates that tell the GHL user what to do next
- [ ] Automated tests for decrypt, SSO token issue/consume, webhook signature (at least the ones already outlined in the plan)

**Done when:** opening CourseForge from GHL sidebar lands a connected location admin in their tenant dashboard without a second password prompt.

---

### Thu Aug 20 — GHL harden + Bobby funnel QA

**Focus:** Make embed trustworthy; prove marketing funnels with coupons.

**GHL**
- [ ] Contact webhook verification + basic upsert path (if in scope this week)
- [ ] Impersonation / embed session audit trail visibility for superadmin or tenant admin
- [ ] Document DEV vs prod env vars (Shared Secret, frame ancestors, redirect URIs)

**Bobby / marketing**
- [ ] Walk both landing pages end-to-end on mobile + desktop
- [ ] Wire or verify CTAs → coupon links / signup / partner paths
- [ ] Confirm lesson CTA bubble + coupon QR still feel consistent on Bobby tenant branding

**Done when:** one written “pilot checklist” exists for GHL connect → embed → dashboard; Bobby landings don’t have broken CTAs.

---

### Fri Aug 21 — Analytics slice + wrap

**Focus:** Ship a thin insight layer; lock the week.

- [ ] Analytics MVP (pick **one**, not the full proposal):
  - **Option A (recommended):** Coupon performance + new students (7/30 days) on dashboard
  - **Option B:** Course enrollment / completion snapshot for top 5 courses
  - **Option C:** Live activity feed polish (if feedback system gaps are blocking admins)
- [ ] Regression pass:
  - coupons, lesson CTA, GHL connect page, Bobby landings, checkout discount
- [ ] Write `Documents/WEEKLY_WRAP_AUG_17_2026.md` (what shipped, what slipped, what’s next)
- [ ] Park anything unfinished into a short “carryover” list for Aug 24 week

**Done when:** wrap doc exists; at least one new admin insight is live; P0 items are either shipped or explicitly deferred with reason.

---

## Workstream details

### A) Coupons (P0 → P1)

| Item | Outcome |
|------|---------|
| Template polish | Cleaner list/edit UX; consistent labels |
| Ops | Iceberg token checklist in deploy notes |
| Reporting | Signups + redemptions per code |
| Safety | Expired/maxed handling; clear errors on QR fail |

**Key files (from last week):**  
`myApp/models.py` (`Coupon`), `myApp/utils/coupons.py`, `myApp/utils/iceberg.py`, `myApp/dashboard_views.py`, coupon templates, `coupon_landing` in `views.py`.

### B) GHL sidebar embed (P0)

| Item | Outcome |
|------|---------|
| Embed + SSO | Iframe login into correct tenant |
| Errors | Actionable empty/unauthorized states |
| Tests | Decrypt / SSO / frame / webhook unit coverage |
| Docs | Short “how to connect in GHL” for tenant admins |

**Source of truth:** `Documents/GHL_SIDEBAR_EMBED_PLAN.md`, `Documents/GHL_SIDEBAR_EMBED_DESIGN.md`.

### C) Tenant admin insight (P1 / P2)

Keep scope tiny. Prefer metrics that reuse data we already store:

- coupon signup attribution
- new memberships / purchases
- existing live activity feed (don’t rebuild)

Defer from `ANALYTICS_PROPOSAL.md` this week: geo maps, session duration, full engagement heatmaps.

### D) Bobby tenant polish (P1)

Treat as a real customer pilot of coupons + landings + lesson CTA:

- QR / text CTAs on landings → `/c/...` or signup
- Branding + CTA bubble still readable on lesson pages
- No broken partner / get-in-the-game form paths

---

## Explicit non-goals this week

Do **not** start unless a P0 is blocked and the team re-prioritizes:

- Full analytics suite from `ANALYTICS_PROPOSAL.md`
- New payment provider / Stripe rework
- Multi-product tenancy rewrite (playbook is reference, not a build ticket)
- Broad AI course-creator redesign
- Schema-per-tenant / RLS migration

---

## Suggested capacity split

Assuming ~1–2 builders on CourseForge:

| Stream | Share of week |
|--------|----------------|
| Coupons polish + reporting | ~30% |
| GHL embed | ~45% |
| Bobby QA + analytics MVP | ~15% |
| Docs / wrap / deploy hygiene | ~10% |

If only one person: **Mon–Tue coupons**, **Wed–Thu GHL**, **Fri wrap + tiny analytics**. Don’t parallelize GHL + big coupon reporting on the same day.

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Iceberg 401 kills QR demos | Token refresh checklist before any client call; surface clear UI error |
| GHL embed cookies need HTTPS | Always demo via tunnel / prod host, never plain localhost |
| Scope creep on analytics | One card/table max; everything else → next week |
| Client interrupt (Bobby) | Use coupon reporting + landing QA as the “client-facing” win so interrupts still ship value |

---

## Definition of done (week)

- [ ] Coupon UI polish merged
- [ ] Coupon performance visible to tenant admin
- [ ] GHL sidebar → CourseForge dashboard works for a connected location
- [ ] Bobby landings QA’d with coupon/CTA paths
- [ ] Weekly wrap written for Aug 17

---

## Carryover candidates (if time runs out)

1. GHL contact webhook full sync
2. Superadmin cross-tenant coupon / funnel rollup
3. Analytics Option B/C
4. Coupon multi-destination A/B or UTM passthrough
5. Automated Iceberg health check on deploy

---

*Plan drafted for week of Aug 17–21, 2026. Revisit Monday stand-up; adjust P0 if a production incident or client deadline overrides.*
