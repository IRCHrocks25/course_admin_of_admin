# Design Plan — Per-Tier Membership Course Mapping

Status: **Phase 1 SHIPPED** (Rev 2 design implemented). Rev 2 incorporated the
engineering review: fixes three access bugs (tier delete, `is_enabled` revoke,
`rank__lte` ties), closes the billing-portal plan-switch hole, pulls persistent
Stripe `Price` objects into Phase 1, replaces the overloaded null-tier with an
explicit `access_mode`, and adds the missing downgrade / comp-collision policies.

> **Implementation note (shipped):** Phase 1 is live — `MembershipTier` model,
> `StudentSubscription.access_mode`/`tier`, `Course.grants_membership_tier`,
> tiered access resolution in `membership.py`, persistent Stripe `Price` upsert +
> `price_id → tier` reconciliation in `membership_sync.py`, per-tier checkout,
> dashboard tier CRUD/archival, and student tier cards. Two extra plan flags were
> also shipped alongside: `member_pricing_requires_annual` (annual-only member
> pricing) and `comp_grant_reset` (reset-vs-stack comp grants). **Phase 2**
> (in-app upgrade/proration UX) remains unbuilt. See
> [`membership_system_limitations.md`](./membership_system_limitations.md) for the
> current gap list.

Scope: add multiple membership tiers per tenant, each unlocking a different set of courses, on top of the existing single all-access membership.

---

## 0. Rev 2 changelog (what the review changed)

| Review point | Resolution in this doc |
|---|---|
| `SET_NULL` on tier delete silently grants all-access | **§4.3** tier FK is `PROTECT`; **§4.1** tiers are soft-deleted (`is_archived`), never hard-deleted once they've had a subscription. |
| `is_enabled=False` revokes existing subscribers | **§4.1/§5** split into `is_purchasable` (gates checkout only). Access resolution never checks it — access stops only when the *subscription* stops. |
| `rank__lte` with non-unique rank double-counts | **§4.1** add `unique_together (tenant, rank)`; **§5** cumulative query also honors a lower tier's `includes_all`. |
| Billing-portal plan switch makes `tier` stale | **§6.4** disable plan-switching in the portal config (documented constraint) **and** map `price_id → tier` on `customer.subscription.updated`; stamp `tier_id` in `subscription_data.metadata`. |
| Persistent Stripe Prices are cheap — pull forward | **§6** persistent `Price` objects move to **Phase 1**; only proration/upgrade UX stays Phase 2. Kills the inline `price_data` regime. |
| Null-tier is overloaded | **§4.3** explicit `access_mode` enum (`ALL_ACCESS` / `TIERED`); `tier` non-null only in `TIERED`. |
| Missing downgrade/loss-of-access policy | **§9** new section (progress preserved, certificates stay valid). |
| Comp grant colliding with a paid tier | **§10** new rule — a comp never clobbers or downgrades an active paid tier. |
| Cache hand-wavy | **§13** dropped from Phase 1; it's one indexed join. Revisit only after profiling. |
| `membership_covers_course` builds whole set for one id | **§5** single-course path is an `.exists()` query. |
| `tenant`/`plan` can drift on the tier | **§4.1** drop `plan` FK; derive the plan via `tenant.membership_plan`. |
| M2M not tenant-scoped | **§4.2** `clean()` + admin scoping so cross-tenant rows can't accumulate. |
| Effort too light | **§14** Phase 1 rebudgeted to 4–6 dev-days. |

---

## 1. Problem & goals

Today a tenant has **one** membership: an active `StudentSubscription` unlocks the *whole* catalog (every active, `public`/`members_only`, `included_in_membership=True` course). It's all-or-nothing.

Tenants want **tiers** — e.g. *Starter* (a handful of courses), *Pro* (more), *All-Access* (everything) — each at its own price. A student subscribes to one tier and gets exactly that tier's course set.

**Goals**

1. A tenant can define ≥1 membership tier, each with its own price(s) and course set.
2. A student holds **one** tier at a time; access = that tier's courses.
3. Per-tier Stripe checkout (monthly/yearly).
4. Fully **backwards compatible**: tenants that never create tiers keep today's exact all-access behavior with zero migration/backfill.
5. Reuse the reconciliation, grace, and comp machinery already built.

**Non-goals (separate efforts)**

- Team/seat-based memberships (org buys N seats). Large, deferred.
- Ecosystem perks (community/events) gated by tier. Out of scope.

---

## 2. Naming constraint (important)

`PricingTier` (`models.py:1511`) already exists and is the **platform's SaaS pricing** — what *tenants* pay *us*, driven by the `tier_upgrade` / `setup_fee` flows. It is unrelated to student membership.

➡ Student membership tiers must use a distinct name: **`MembershipTier`**. Do not overload `PricingTier`, `tier_upgrade`, or the `tier` metadata key used by platform billing. Membership uses `membership_tier_id` in Stripe metadata to avoid any collision with the platform's `tier` key.

---

## 3. Current state (what we build on)

| Piece | Location | Behavior today |
|---|---|---|
| `MembershipPlan` (OneToOne tenant) | `models.py:1813` | `is_enabled`, `name`, `description`, `monthly_price`, `yearly_price`, `past_due_grace_days`. One price pair per tenant. |
| `StudentSubscription` (unique `tenant`+`user`) | `models.py:1842` | One membership row per student per tenant. `status`, `interval`, `is_complimentary`, `current_period_end`, Stripe ids. |
| Coverage set | `utils/membership.py` → `get_membership_course_ids` | Active sub ⇒ **all** active, non-`private`/`hidden`, `included_in_membership=True` courses. |
| Access gates | `utils/access.py` (`has_course_access`, `batch_has_course_access`, `get_user_accessible_courses`) | Delegate to the membership helpers. |
| Checkout | `views.py:create_membership_checkout_session(interval)` | Inline `price_data` from the plan's monthly/yearly price; metadata `flow=membership_checkout`. |
| Activation / lifecycle | `views.py` `_membership_activate_from_checkout`, `_membership_handle_subscription_event`; `utils/membership_sync.py` | Webhooks + `sync_memberships` pull; `expire_memberships` for comps/grace. |
| Comp grants | `utils/membership.py:grant_complimentary_membership` | Course purchase can grant N months of comp; already **guards** against clobbering an active paid sub (`if sub.is_active() and not sub.is_complimentary: return sub`). |
| Member pricing | `Course.member_price` via `effective_course_price` | Any active member ⇒ member price. |

Because access is centralized in the membership helpers, tiering is mostly a change to **which course-id set an active sub resolves to** — the access call sites don't change.

---

## 4. Proposed data model

### 4.1 New model `MembershipTier`

```
MembershipTier
  tenant                   FK Tenant                  # sole owner; plan derived via tenant.membership_plan
  code                     SlugField                  # unique per tenant (e.g. "starter")
  name                     CharField
  description              TextField (blank)
  rank                     PositiveIntegerField       # higher = more inclusive
  monthly_price            Decimal (null)             # blank disables monthly for this tier
  yearly_price             Decimal (null)
  includes_all             BooleanField(default=False)# unlock whole catalog (all-access tier)
  is_purchasable           BooleanField(default=True) # gates NEW checkout only — never access
  is_archived              BooleanField(default=False)# soft-delete; hidden from admin, retained for reporting
  # persistent Stripe Prices (Phase 1) — enables checkout-by-id, upgrades, and price_id→tier repair:
  stripe_product_id        CharField(blank)
  stripe_monthly_price_id  CharField(blank)
  stripe_yearly_price_id   CharField(blank)
  created_at / updated_at

  Meta:
    unique_together = [(tenant, code), (tenant, rank)]   # (tenant, rank) makes rank__lte safe
    ordering = [rank, id]

  def clean():
    # every course in `courses` must belong to `tenant` (no cross-tenant rows)
```

- **`plan` FK dropped.** `MembershipPlan` is OneToOne with `tenant`, so a separate `plan` FK could drift from `tenant`. Derive the plan (for the `tiers_cumulative` flag) via `tenant.membership_plan`.
- **`is_purchasable` vs access.** Toggling a tier off-market (stop new signups) must **not** cut off paying members. `is_purchasable` gates checkout; access resolution ignores it entirely.
- **`is_archived` (soft-delete).** Admins archive tiers instead of deleting. A tier that has ever had a subscription is never hard-deleted (also needed for revenue reporting). Combined with the `PROTECT` FK below, this makes accidental all-access promotion impossible.
- **Stripe Price ids in Phase 1.** Persistent `Price` objects (per interval) let checkout reference a stored price, enable in-place upgrades later, and give us the `price_id → tier` map that repairs state if a customer switches plans in the portal.

### 4.2 Course ↔ tier mapping

Add M2M: `MembershipTier.courses = M2M(Course, blank, related_name="membership_tiers")`.

- **Tenant scoping.** `MembershipTier.clean()` validates every linked course shares the tier's tenant; the admin course-picker is filtered to the tenant. The read queries also filter `tenant=tier.tenant` defensively, so a bad row can never leak access even if one is created out-of-band.
- **Cumulative option** (`MembershipPlan.tiers_cumulative`, default `True`): a tier's *effective* set = its own `courses` ∪ the `courses` of every **lower-or-equal-rank** tier. So *Pro* automatically includes *Starter*'s courses. If `False`, each tier is independent.
- **`includes_all` short-circuits** to the full catalog set — and in cumulative mode, *any* lower tier with `includes_all` promotes the whole chain to full catalog (see §5).
- `Course.included_in_membership` is retained as a **global eligibility gate**: a course with the flag off is never in any tier's effective set.

### 4.3 `StudentSubscription` changes

```
access_mode  CharField(choices=[('all_access','All-access'), ('tiered','Tiered')],
                       default='all_access')
tier         FK(MembershipTier, null=True, blank=True, on_delete=PROTECT)

CheckConstraint: (access_mode='tiered' AND tier IS NOT NULL)
              OR (access_mode='all_access' AND tier IS NULL)
```

- **`access_mode` disambiguates** the old null-tier, which meant both "legacy all-access" *and* "untargeted comp." Now every row self-documents: `all_access` (legacy plan or all-access comp) vs `tiered` (holds a specific tier). Costs one column, no backfill (default `all_access` = today).
- **`PROTECT`** prevents deleting a tier out from under its subscribers (which under `SET_NULL` would silently promote them to all-access). Deleting is done by archiving instead.
- `unique_together = (tenant, user)` still guarantees **one membership at a time** per student.

---

## 5. Access resolution changes (small, centralized)

All in `utils/membership.py`; call sites in `access.py` unchanged.

```
def _catalog_ids(tenant) -> set:
    # today's all-access set: active, non-private/hidden, included_in_membership
    ...

def _tier_course_qs(tier):
    """Base queryset for a tier's effective courses (no is_purchasable/is_archived gate)."""
    base = (Course.objects
            .filter(tenant=tier.tenant, status='active', included_in_membership=True)
            .exclude(visibility__in=MEMBERSHIP_EXCLUDED_VISIBILITIES))
    plan = getattr(tier.tenant, 'membership_plan', None)
    cumulative = bool(plan and plan.tiers_cumulative)
    if cumulative:
        lower = MembershipTier.objects.filter(tenant=tier.tenant, rank__lte=tier.rank)
        # a lower/equal tier that grants everything promotes the whole chain
        if tier.includes_all or lower.filter(includes_all=True).exists():
            return base  # == whole catalog
        return base.filter(membership_tiers__in=lower)
    if tier.includes_all:
        return base
    return base.filter(membership_tiers=tier)

def tier_course_ids(tier) -> set:
    # NOTE: intentionally does NOT check is_purchasable or is_archived —
    # access must persist for existing subscribers regardless of sale status.
    if tier is None:
        return set()
    return set(_tier_course_qs(tier).values_list('id', flat=True))

def get_membership_course_ids(user, tenant) -> set:
    sub = get_active_subscription(user, tenant)
    if sub is None:
        return set()
    if sub.access_mode == 'all_access':
        return _catalog_ids(tenant)
    return tier_course_ids(sub.tier)

def membership_covers_course(user, course) -> bool:
    sub = get_active_subscription(user, course.tenant)
    if sub is None:
        return False
    if sub.access_mode == 'all_access':
        return course_covered_by_membership(course)
    if sub.tier is None:               # constraint should prevent this
        return False
    # single-id existence check — do NOT build the whole set to test one course
    return _tier_course_qs(sub.tier).filter(id=course.id).exists()
```

- `rank__lte` is now safe because `(tenant, rank)` is unique — no two tiers share a rank, so no double-swallow.
- `is_purchasable`/`is_archived` are deliberately absent from these paths.
- `get_active_subscription`, `past_due_grace_days`, comp/expiry logic are unchanged.

---

## 6. Checkout & Stripe

### 6.1 Persistent Prices on tier save (Phase 1)

When an admin saves a tier's price(s), upsert Stripe objects on the tenant's account (own-keys or Connect via `stripe_account`, mirroring `_resolve_tenant_stripe_mode`):
- ensure a `Product` (per tier) → `stripe_product_id`;
- create/replace `Price` objects for the set intervals → `stripe_monthly_price_id` / `stripe_yearly_price_id` (Stripe Prices are immutable, so a price change means archive-old + create-new and restamp the id).

This removes the inline `price_data` regime entirely — one pricing source of truth, and it yields the `price_id → tier` map used below.

### 6.2 Checkout

`create_membership_checkout_session(request, tier_code, interval)`:
- resolve `MembershipTier` by `(tenant, code)`; require `is_purchasable` and not `is_archived`;
- `line_items=[{price: <stored price id>, quantity: 1}]` (no inline price_data);
- `metadata.flow='membership_checkout'`, `metadata.membership_tier_id=<id>`;
- **also** set `subscription_data.metadata.membership_tier_id=<id>` so the *subscription itself* is self-describing for later repair;
- block duplicate active membership as today (via `get_active_subscription`).

URL: `membership/checkout/<tier_code>/<interval>/`. Keep the old `membership/checkout/<interval>/` route resolving to the tenant's single purchasable tier (or legacy all-access) so existing links don't break.

### 6.3 Activation

`_membership_activate_from_checkout` reads `membership_tier_id` → sets `subscription.access_mode='tiered'`, `subscription.tier=<tier>`. All-access/legacy checkouts set `access_mode='all_access'`, `tier=None`.

### 6.4 Billing portal — close the plan-switch hole

Two layers (belt-and-suspenders):
1. **Config constraint:** create the Customer Portal configuration with **subscription plan-switching disabled** (members can update payment method / cancel, not swap price). Documented as a hard constraint so nobody re-enables it without also wiring the map below.
2. **Repair on drift anyway:** in `_membership_handle_subscription_event` (and the `sync_memberships` pull), on `customer.subscription.updated` read the subscription item's `price.id`, look up `MembershipTier` by `stripe_*_price_id`, and if it differs from our stored `tier`, update `tier`/`access_mode`. This self-heals even if switching is ever enabled or a price is changed directly in Stripe.

### 6.5 Upgrades / downgrades (Phase 2)

The persistent Prices and `price_id → tier` map already exist from Phase 1, so Phase 2 is *only* the in-place change + proration UX: `stripe.Subscription.modify(items=[{id, price}], proration_behavior=...)`, then set `tier`/`access_mode`. Until then, tier change = cancel + re-subscribe.

### 6.6 Reconciliation impact

`sync_memberships` / webhooks continue to sync `status`/`current_period_end`; they now *additionally* reconcile `tier` from the subscription's price id (§6.4). `expire_memberships` and the `past_due` grace remain tier-agnostic.

---

## 7. Admin / dashboard UX

- **Membership page** (`dashboard/membership.html`): tier list with add/edit/**archive**/reorder (rank), per-tier prices, `is_purchasable`, `includes_all`, and the plan-level `tiers_cumulative` toggle. The existing single-plan fields become the "one purchasable tier" case.
- **Course assignment**: a courses × tiers checkbox matrix (or per-tier "courses in this tier"), tenant-scoped. Show the *effective* (cumulative) set read-only so admins see what Pro really unlocks.
- **Comp-grant warning:** when a tenant first creates a tier, warn that any `Course.grants_membership_months` still grants **all-access** by default, and offer a "point existing grants at a tier" follow-up (§10).
- **Course detail form** (`dashboard/course_detail.html`): show which tiers include this course (read-only badge) beside the existing `included_in_membership` toggle + the hidden/private warning already shipped.

## 8. Student-facing UX

- **Pricing/landing**: tier cards (name, price, "N courses", bullets), monthly/yearly buttons → `startMembershipCheckout(tierCode, interval)`.
- **Learning hub banner** (`learning_hub.html`): current tier + "Upgrade" CTA when a higher tier exists; manage via billing portal.
- **Course detail**: if locked and a tier would unlock it, CTA "Included in <Tier> — subscribe".

## 9. Downgrade / loss-of-access policy (product decision)

When a student moves Pro→Starter, lapses, or a tier stops covering a course:

| Artifact | Policy (recommended) |
|---|---|
| **Course content** | Locked, not deleted. Shows a "resubscribe to continue" state. |
| **Enrollment + progress** | **Preserved.** We never delete `CourseAccess`/progress on access loss; if they regain the tier, progress is intact. Access denial only hides content. |
| **Issued certificates** | **Remain valid.** Certification is a completed event; revoking it retroactively is user-hostile and legally awkward. |

This falls out of the design for free (access resolution just narrows the id-set; nothing cascades to progress), but it must be confirmed as product intent because it surfaces in week one.

## 10. Complimentary grants with tiers

- **Target tier:** add optional `Course.grants_membership_tier` FK. Null ⇒ grant **all-access** (`access_mode='all_access'`, `tier=None`) exactly like today. Set ⇒ grant that tier (`access_mode='tiered'`).
- **Collision rule (must-hold):** a comp grant must **never clobber or downgrade an active paid tier**. `grant_complimentary_membership` already returns early when the holder has an active non-comp sub; keep that guard and extend it so an all-access comp never overwrites a `tiered` paid row. Because `(tenant, user)` is one row, the guard is the single point that enforces "paid beats comp."

---

## 11. Migration & rollout

**Schema migrations (hand-written to avoid the known `lessontranslation` drift):**
1. `MembershipTier` (+ `courses` M2M, `is_purchasable`, `is_archived`, Stripe id fields, `unique_together` on code and rank).
2. `MembershipPlan.tiers_cumulative` (default `True`).
3. `StudentSubscription.access_mode` (default `all_access`) + `tier` FK (`PROTECT`, null) + the check constraint.
4. `Course.grants_membership_tier` FK (null).

**No data backfill.** `access_mode='all_access'` (default) reproduces today's behavior for every existing subscriber and tenant. Tiers are opt-in.

**Phases**
- **Phase 1 (MVP):** models + access resolution + persistent Stripe Prices + per-tier checkout/activation + portal hardening (§6.4) + dashboard tier CRUD/archival & course assignment + student tier cards. Tier change = cancel/resubscribe.
- **Phase 2:** in-place upgrade/downgrade + proration UX; tier-scoped member pricing; comp-to-specific-tier UX polish.
- **Phase 3:** trials, per-tier annual discounts, per-tier analytics.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Access regression for existing members | `access_mode='all_access'` fast path is byte-for-byte today's behavior; regression tests before touching helpers. |
| Tier deletion promotes subscribers to all-access | `PROTECT` FK + soft-delete (`is_archived`); no hard delete once a tier has subs. |
| Off-market toggle locks out payers | `is_purchasable` gates checkout only; access never reads it. |
| Portal plan-switch makes `tier` stale | Switching disabled in portal config **and** `price_id → tier` repair on `subscription.updated`. |
| Cross-tenant course in a tier | `clean()` + tenant-scoped admin picker + defensive `tenant=` filter in read queries. |
| Collision with platform `PricingTier` | Distinct model + `membership_tier_id` metadata key. |
| Comp overwriting a paid tier | Single guarded path in `grant_complimentary_membership` (§10). |

## 13. On caching (deferred)

The effective course-id set is invalidated by M2M edits, `Course.status`, `visibility`, and `included_in_membership` — a broad surface. It's also just **one indexed join**, computed once per request in the batch path. **No cache in Phase 1.** Add one only if a profile shows it matters, at which point key it on tier + a cheap catalog-version counter bumped on those writes.

## 14. Effort (revised)

- **Phase 1:** **~4–6 dev-days.** Models + migrations + constraints ~1d; access resolution + tests ~1d; persistent Stripe Prices + checkout/activation + portal hardening ~1–1.5d; dashboard tier CRUD/archival + courses×tiers matrix ~1–1.5d; student tier cards ~0.5–1d. Add buffer if the dashboard gets a real design review.
- **Phase 2:** ~2–3 dev-days (proration/upgrade UX is the bulk; Prices/map already exist).

---

## 15. Decisions (recommended defaults — pending your review)

| # | Question | Recommended answer | Notes from review |
|---|---|---|---|
| 1 | Cumulative tiers by default (Pro ⊇ Starter)? | **Yes** — `tiers_cumulative=True`, per-tenant overridable. | Requires `(tenant, rank)` unique so cumulative math is exact. |
| 2 | `member_price` scope in Phase 1 — global or per-tier? | **Global** (any active member), unchanged. Per-tier gating → Phase 2. | Zero regression; refinement, not blocker. |
| 3 | Which tier do comp grants target? | Optional `Course.grants_membership_tier`; **null ⇒ all-access**. | Needs the admin warning + "retarget existing grants" prompt (§7/§10). A $29 course granting the whole catalog after tiers exist is a real footgun. |
| 4 | Tier changes in Phase 1 — cancel/resubscribe or in-place? | Phase 1 **cancel/resubscribe**, **but** persistent Stripe Prices ship in Phase 1 so Phase 2 upgrade is just proration UX. | Revised per review: Prices are cheap (~½ day) and also fix the portal-drift hole, so they're no longer deferred. |
| 5 | Auto-migrate existing single-plan tenants? | **No** — default `access_mode='all_access'`, grandfather existing subs. | Made explicit via `access_mode` rather than an implied null. |
| 6 | Downgrade policy (progress/certs)? | Preserve progress; keep certificates valid; lock content only. | New — see §9; confirm as product intent. |

**Net effect:** all defaults keep Phase 1 additive and backwards-compatible — no data backfill, no change to existing subscribers, no change to the reconciliation/grace/expiry jobs. Persistent Stripe Prices are the one item promoted from Phase 2 into Phase 1 (cheap, and it closes the portal-switch hole).
