# Membership System — Limitations & Known Gaps

This documents what the tenant **membership** feature does **not** do yet, plus edge cases and operational caveats. It reflects the system as currently implemented, **including the tiered-membership update and the two plan flags (`member_pricing_requires_annual`, `comp_grant_reset`)**:

- Models: `MembershipPlan` (with `tiers_cumulative`, `member_pricing_requires_annual`, `comp_grant_reset`, `past_due_grace_days`), `MembershipTier`, `StudentSubscription` (with `access_mode`, `tier`), and course fields `included_in_membership`, `member_price`, `grants_membership_months`, `grants_membership_tier` in [`myApp/models.py`](../myApp/models.py)
- Logic: [`myApp/utils/membership.py`](../myApp/utils/membership.py), [`myApp/utils/membership_sync.py`](../myApp/utils/membership_sync.py), [`myApp/utils/access.py`](../myApp/utils/access.py)
- Flows: checkout / success / webhooks in [`myApp/views.py`](../myApp/views.py)
- Admin: [`dashboard/membership.html`](../myApp/templates/dashboard/membership.html), course form in [`dashboard/course_detail.html`](../myApp/templates/dashboard/course_detail.html)

---

## 1. Plan structure

| Limitation | Detail |
|---|---|
| ~~**Single tier per tenant**~~ | **Resolved.** `MembershipPlan` is still one-to-one with a tenant, but a tenant can now define multiple named `MembershipTier` rows (e.g. Starter/Pro/All-Access), each with its own monthly/yearly price, Stripe product/price, and course set. `tiers_cumulative` controls whether a higher tier also unlocks lower-tier courses. Subscriptions carry `access_mode` (`all_access` legacy/comp vs `tiered`) and an optional `tier`. |
| **No team / organization memberships** | There is no seat-based / multi-user membership. Every `StudentSubscription` is one row per user (`unique_together = tenant, user`). Team 5 / Team 10 / Org 25 / Enterprise style plans are **not supported** and cannot be seeded. |
| **No trials** | No free-trial period. Checkout starts a paying subscription immediately. |
| **No setup/joining fee** | Only recurring price; no one-time onboarding fee for membership. |
| **No one-time "lifetime" all-access** | Membership is recurring only. A pay-once lifetime pass is not implemented (bundles remain the only one-time multi-course purchase). |

## 2. Pricing & payments

| Limitation | Detail |
|---|---|
| **USD only** | Currency is hard-coded to `usd` in checkout, matching the rest of the platform. No multi-currency. |
| **No coupons on membership** | Coupons apply to courses/bundles/signup only. There is no `Coupon.TARGET_MEMBERSHIP`, so membership checkout cannot be discounted with a coupon code. |
| **No proration / plan switching in-app** | Switching monthly ↔ yearly, or changing price, is only possible via the Stripe Customer Portal. The app does not drive upgrades/downgrades or prorate. |
| **No tax / VAT handling** | Stripe Tax is not configured; prices are charged as-is. |
| **Price changes are not retroactive** | Editing `monthly_price` / `yearly_price` only affects **new** checkouts. Existing subscribers keep their Stripe price until they resubscribe. |

## 3. Access logic

| Limitation | Detail |
|---|---|
| **Membership grants course access only** | "Ecosystem" perks (community/forum, events, masterclasses) are **not gated by membership** — any registered student can already reach those. Membership currently equals catalog course access, nothing more. |
| **Included scope is coarse (all-access mode)** | For `access_mode='all_access'` subs (legacy + complimentary), membership unlocks all `status=active`, non-`private`, non-`hidden`, `included_in_membership=True` courses for the tenant. Per-tier course mapping now exists for `access_mode='tiered'` subs via `MembershipTier.courses` (plus `includes_all` and cumulative rollup), but the global include flag is still the only lever for the all-access path. |
| ~~**`hidden` courses are included**~~ | **Resolved.** The membership course set now excludes both `private` and `hidden` (`MEMBERSHIP_EXCLUDED_VISIBILITIES`). Membership covers only catalog-discoverable courses (`public` / `members_only`); direct-link-only (`hidden`) and manual-only (`private`) courses are never auto-unlocked, and the dashboard course form warns when the include flag can't apply. |
| ~~**No expiry/grace policy config**~~ | **Partially resolved.** `MembershipPlan.past_due_grace_days` (set in the membership dashboard) keeps a member's access for N days after a failed renewal while Stripe retries dunning, instead of cutting off the instant status becomes `past_due`. `is_active(past_due_grace_days=...)` enforces it and access checks read the plan setting. Default is 0 (immediate cut-off) so existing behavior is unchanged until configured. There is still no grace for `active`-past-`current_period_end`. |

## 4. Complimentary memberships

| Limitation | Detail |
|---|---|
| ~~**Stale `status` after expiry**~~ | **Resolved.** A complimentary membership (from `grants_membership_months`) has no Stripe subscription and no webhook, so `is_active()` always denied access live once `current_period_end` passed, but the stored `status` used to stay `'active'`. The `expire_memberships` management command (and an opportunistic pass when an admin opens the membership dashboard) now flips lapsed comps to `status='expired'` so reporting is accurate. Schedule it once or twice a day. |
| **Manual comp grants never auto-expire status either** | Admin-granted comps set `current_period_end = None` = indefinite. Revoking is manual. |
| **Comp does not stack onto a paid sub** | If a user already has an **active paid** membership, buying a programme with `grants_membership_months` does **not** extend their paid period (by design — we don't downgrade a paid sub to complimentary). The complimentary months are effectively skipped in that case. |
| **Comp stack-vs-reset is configurable** | `MembershipPlan.comp_grant_reset` controls how a new comp combines with remaining comp time. Off (default) = **extend/stack** N months onto whatever is left. On = **reset** to N months from the latest purchase. Backward-compatible: default is the original stacking behavior. |

## 5. Stripe Connect caveats

| Limitation | Detail |
|---|---|
| **Connect renewals depend on connected-account webhooks** | For Connect tenants, subscription lifecycle events (`invoice.paid`, `customer.subscription.updated/deleted`) only update our records if the connected account's webhooks reach the platform endpoint. If not enabled, renewals/cancellations may not sync automatically. |
| ~~**No periodic Stripe *pull* reconciliation**~~ | **Resolved.** `python manage.py sync_memberships` pulls fresh status + period end from Stripe for every paid, non-comp subscription (own-keys and Connect via `stripe_account`), stamping `last_synced_at`. Members also self-heal on return from the billing portal (`membership_billing_return`). Schedule the command a few times a day. Comps are skipped here — they're handled by `expire_memberships`. |
| **Success-redirect dependency** | Initial activation relies partly on the checkout success redirect (like course/bundle purchases). If the user abandons the redirect and no webhook fires, the subscription may sit `incomplete`. |

## 6. Webhooks & data integrity

| Limitation | Detail |
|---|---|
| **Student vs platform disambiguation by lookup order** | The platform webhook distinguishes student memberships from academy-owner (platform) billing by checking `StudentSubscription` first. This is correct today but assumes IDs don't collide across the two billing layers. |
| **No idempotency beyond `StripeEventLog`** | Duplicate suppression is per-event-id. Out-of-order events (e.g. `deleted` arriving before a late `updated`) are applied in arrival order without sequence checks. |
| **`invoice.paid` period extension is best-effort** | Period end is read from the first invoice line; unusual invoice shapes fall back to leaving the period unchanged. |

## 7. Admin & reporting

| Limitation | Detail |
|---|---|
| **No membership analytics** | No MRR, churn, active-member trend, or conversion reporting. The dashboard shows a plain subscriber list + active count only. |
| **No bulk comp / CSV import** | Complimentary membership is granted one student at a time by username/email. No bulk grant or import. |
| **Enable gate is point-in-time** | Enabling requires Stripe-ready + at least one price at save time. If Stripe is later disconnected, the plan stays "enabled" and student checkouts will fail at the Stripe step rather than being pre-blocked. |
| **Member price / include flag edited per course** | There is no "apply to all courses" bulk action for `included_in_membership`, `member_price`, or `grants_membership_months`. |

## 8. Member pricing edge cases

| Limitation | Detail |
|---|---|
| **Member price needs an active membership at checkout** | `member_price` only applies if the user is an active member **at the moment of course checkout**. A user buying a programme to *get* membership pays full price (they aren't a member yet). |
| **Member-price eligibility can require annual** | `MembershipPlan.member_pricing_requires_annual` gates the discount. Off (default) = any active member gets member pricing. On = only **annual** and **complimentary** members qualify; **monthly** members pay standard price (stops "pay one month, grab the discount, cancel"). Enforced via `member_pricing_eligible()`. Backward-compatible: default preserves the original any-member behavior. |
| **No member price on bundles** | `member_price` is a course-level field. Bundles have a single price with no member discount. |
| **Coupon stacks on member price** | Coupons apply on top of member price. There is no cap preventing a coupon + member price from combining to an unexpectedly low total (aside from the ">$0" guard). |

## 9. Testing & migrations

| Limitation | Detail |
|---|---|
| **No automated tests** | Behavior was verified with ad-hoc rolled-back scripts, not committed unit/integration tests. |
| **Pre-existing migration drift** | An unrelated `lessontranslation.language_code` model/migration drift exists in the repo. It was intentionally excluded from the membership migrations and still needs its own migration by whoever owns that model. |

---

## Suggested next steps (in rough priority)

1. ~~**Comp-membership expiry job**~~ — **Done.** `python manage.py expire_memberships` flips lapsed `StudentSubscription`s (comps immediately, paid after a 72h grace) from `active` → `expired`. The membership dashboard also reconciles the current tenant on load. Schedule the command daily.
2. ~~**Connect reconciliation**~~ — **Done.** `python manage.py sync_memberships` pulls status/period from Stripe for paid subs (own-keys + Connect), and members self-heal on billing-portal return via `membership_billing_return`. Schedule the command a few times a day.
3. ~~**Multiple named tiers**~~ — **Done.** `MembershipTier` (per-tier price, Stripe product/price, course set, `includes_all`, cumulative rollup) with tiered checkout, dashboard CRUD/archival, price-id→tier reconciliation, and student tier cards. Subscriptions carry `access_mode` + `tier`.
4. **Team / organization memberships** — new `TeamMembership` (tenant, owner, tier, seat limit, one Stripe subscription) + `TeamSeat` rows; each occupied seat grants catalog access like an individual membership. Still the largest unbuilt piece.
5. **Membership coupons** — add `Coupon.TARGET_MEMBERSHIP` and pass a Stripe discount into subscription checkout.
6. **Analytics** — MRR / active / churn on the dashboard membership page.
7. **In-app upgrade/proration** — drive tier upgrades with Stripe proration in-app rather than cancel/resubscribe (Phase 2 of the tiers design).
