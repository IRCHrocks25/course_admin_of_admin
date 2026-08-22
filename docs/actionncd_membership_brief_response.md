# Re: ActioNCD Academy™ — Membership, Programme & Pricing Brief

**A response to your CRM / Landing-Page Implementation Brief**
Prepared by: Platform / Engineering
Status: implementation response — nothing on your live academy has been changed by this document.

---

## 1. Short version

Thank you — this is an unusually clear brief, and the commercial model is coherent. Most of it maps cleanly onto what the platform can now do after the tiered-membership update we just shipped — and the two behavioural rules that were most specific to your model (**annual-only member pricing** and **complimentary reset-to-12-months**) are **now implemented and already switched on for your academy**. There is **one thing left to confirm** (where the ecosystem benefits live), and a clear **split between what the learning platform handles and what the CRM (GoHighLevel) owns**. This memo lays all of that out so nothing gets lost.

The single most important point to align on up front:

> **Your membership is an *ecosystem* membership, not a course subscription.** The platform's membership engine was originally built as "membership unlocks courses." We can absolutely run your model on it, but we need to treat the eight capability programmes as **separate paid products** (they already are in your data) and treat membership as **status + selected learning sessions + ecosystem benefits**, where the ecosystem benefits (Community of Practice, Masterclasses, Faculty Office Hours, Resource Library, networking) are delivered and gated in the **CRM**, not by the course-access engine.

Everything below follows from that.

---

## 2. What the platform already does (after the update)

These are live capabilities today:

| Your brief | Platform support |
|---|---|
| Monthly ($20) and Annual ($200) membership | ✅ A membership tier carries both a monthly and yearly price; students pick interval at checkout. Stripe subscription + billing portal already wired. |
| Complimentary 12-month membership on programme purchase | ✅ Each programme can grant N months of complimentary membership on purchase (`grants_membership_months = 12`). Already configured on your five existing programmes. |
| Comp membership begins at enrolment date | ✅ The grant starts from the purchase and runs 12 months. |
| Not charged $20/$200 during the complimentary year | ✅ A complimentary membership is a first-class state; the student is not billed while it's active. |
| Academy Member Price on programmes | ✅ Each programme has a standard price and a member price; members are charged the member price automatically. |
| "Includes 12 months complimentary membership" on programme pages | ✅ Already displayed on the course/programme page. |
| Membership status lifecycle (active / past-due / expired / cancelled) | ✅ Tracked, with a scheduled job that expires lapsed complimentary memberships and a Stripe pull-reconciliation for paid ones. |
| Past-due grace window | ✅ Configurable per academy (keeps access during a failed-renewal retry instead of cutting off instantly). |
| Named tiers + which courses each unlocks | ✅ The new tier system (this is the "update"). |
| Annual-only member pricing (monthly members don't unlock the programme discount) | ✅ Now implemented as a per-academy setting and **switched on for you** — annual + complimentary members get member pricing; monthly members get ecosystem benefits only. |
| Complimentary membership **resets** to 12 months from the latest qualifying purchase (not stacked) | ✅ Now implemented as a per-academy setting and **switched on for you** — matches your NCD Compass → NCD Guardian example exactly. |

**What we seeded for you as part of the update:** one **All-Access Membership** tier at $20/mo · $200/yr that mirrors your current membership, and we pointed all five existing programmes' complimentary grants at that named tier. See §7 for why we recommend *renaming/reframing* this rather than leaving it as "All-Access."

---

## 3. Status of your three model-specific rules

Two of these were genuine product choices; we've now **built both as per-academy settings and enabled them on your tenant** to match the brief. The third is a confirmation, not a build.

### A — Monthly vs Annual member-pricing (your §4) — ✅ Shipped & enabled

Your rule: **Annual** members and **programme-complimentary** members get Academy Member Pricing on programmes; **Monthly** members do **not** (to stop "pay $20 → grab a $100 discount → cancel").

- **Done:** member-price eligibility is now **interval-aware**. Annual + complimentary = eligible; monthly = ecosystem benefits only.
- **State:** the "annual-only member pricing" setting is **switched on** for your academy. It's a toggle, so you can change it later if you decide monthly members should get the discount after all.

### B — Complimentary stacking vs reset (your §12) — ✅ Shipped & enabled

Your rule: each new qualifying programme purchase **resets** the complimentary membership to **12 months from the latest purchase** (not stack multiple years).

- **Done:** the grant now **resets to (latest purchase date + 12 months)** instead of stacking, matching your NCD Compass → NCD Guardian example exactly.
- **State:** the "reset" setting is **switched on** for your academy (also a toggle).

### C — Where the ecosystem benefits live — needs your confirmation

Community of Practice, Executive Masterclasses, Faculty Office Hours, Resource Library, professional profile/transcript, member-only comms — the platform's course-access engine does **not** gate these. They are delivered/tracked in the **CRM (GHL)** and your community/masterclass tooling, gated by **membership status/tag**.

- **Confirm:** you're happy for those benefits to be driven by CRM membership tags (the platform emits the membership-active / expired signals; GHL grants/removes the benefit access and comms).

---

## 4. Platform (LMS) vs CRM (GoHighLevel) — who owns what

This split keeps the build clean and avoids duplicating logic.

| Capability | Owner | Notes |
|---|---|---|
| Membership checkout & billing ($20/$200) | **Platform** | Stripe subscription, member/annual, billing portal. |
| Programme checkout (standard & member price) | **Platform** | Separate paid products; member price auto-applied. |
| Complimentary 12-month grant on programme purchase | **Platform** | Emits the membership-active state. |
| Membership status, start/expiry dates, expiry job | **Platform** | Source of truth for *access*. |
| CRM tags (`academy-member-monthly`, `academy-member-annual`, `academy-member-programme`) | **CRM** | Set from the membership signals the platform emits (GHL integration already exists on this academy). |
| CRM custom fields (§11: Membership Type/Status/Source/Expiry, Member-Pricing-Eligible, Complimentary=Yes, etc.) | **CRM** | Populated by workflow from the same signals. |
| Renewal reminder sequence (60/30/14/3 days, expiry) (§13) | **CRM** | These are email/workflow automations — GHL, not the LMS. Platform provides the expiry date the sequence keys off. |
| Onboarding / welcome / capability-assessment routing (§14) | **CRM** | Workflow orchestration. Platform grants access; GHL runs the journey. |
| Ecosystem benefits (community, masterclasses, office hours, library) | **CRM + external tools** | Gated by membership tag/status, not by course access. |
| Team / Organizational / Institutional enquiries (§8, §9) | **CRM (lead form)** | CTA triggers `academy-organizational-lead` + B2B enquiry workflow, **not** checkout. See §6 below. |

**Net:** the platform is the billing + access + status engine; the CRM is the tagging + fields + comms + journey engine. They connect through the membership lifecycle signals.

---

## 5. Programme catalogue — reconciliation needed

Your brief lists **eight** programmes; the academy currently has **five** priced flagships plus some membership learning sessions. To match the brief we need to line these up. Two things stand out:

**a) Prices to correct (minor):** your table lists COMBI / SMILE / ABCD in PHC at **$495**; they're currently **$497**. Small change to match the brief.

**b) Four programmes to add:**

| Programme | Standard | Member |
|---|---|---|
| NCD Guardian™ (Leadership & Systems Thinking) | $595 | $475 |
| NCD Catalyst™ (Policy & Governance) | $595 | $475 |
| NCD INVEST™ (Financing & Resource Mobilization) | $595 | $475 |
| NCD Mastery™ (Integrated Country Capability) | $995 | $795 |

**c) Naming/mapping to confirm:** your "**NCD Compass™ — Foundation & Gateway ($297/$245)**" needs to be matched to the right existing course record (there are two "NCD Compass" items in the catalogue right now — one $297 flagship, one membership learning session). We'll also want to confirm the current **$1 test programme** ("AI-Assisted Public Health Leadership") is a placeholder to remove or repurpose.

The three current membership-included sessions (AI-Assisted Public Health, Behaviour-Driven Communication, NCD Compass 5Ps) map naturally to your "**Selected Academy learning sessions**" member benefit — keep them as membership content, not as one of the eight paid programmes.

Once you confirm names + which record is which, we can align prices, add the four missing programmes, set each to grant the 12-month complimentary membership, and set member prices — a straightforward data pass.

---

## 6. Not yet built — Team / Organizational / Institutional (your §8 & §9)

This is the one area that is a **genuinely new subsystem**, not a config change:

- **Seat-based team memberships** (Team 5 $900, Team 10 $1,600, Organization 25 $3,500, Enterprise custom) — the platform does **not** currently support one purchaser holding N seats and assigning them. This was deliberately deferred as a separate, larger build.
- **Institutional programme cohorts** (Compass 10 = $2,500, etc.) — sales-led, custom-quoted.

**Recommendation for launch (matches your brief):** these CTAs should **not** go to checkout. Point "Discuss Team Membership" and the institutional cohorts at a **CRM enquiry form** (`academy-organizational-lead` → `WF – Academy B2B Enquiry`). That is fully doable now with zero platform work and matches exactly what you asked for. When there's demand, we can scope the seat-based subsystem as its own project.

---

## 7. One framing recommendation

Your brief is emphatic that the Academy is **"not an all-inclusive course subscription."** The tier we seeded is currently labelled **"All-Access Membership,"** which slightly contradicts that positioning. We recommend:

- Rename the membership so students see **"ActioNCD Academy Membership"** with **Flexible (monthly)** and **Annual** framing — not "All-Access."
- Present the member-facing value as **ecosystem + selected learning sessions**, per your §1 and §15 language, rather than "unlock every course."
- Keep the eight programmes visibly **separate and paid**, each with the "includes 12 months complimentary membership" benefit — which the platform already displays.

This is a 2-minute naming/copy change on our side; flagging it so the product language matches your commercial message.

---

## 8. Landing page & FAQ (your §5, §6, §7, §15, §16, §17)

The conversion hierarchy, the two membership cards, the eight programme cards, the FAQ, and the core commercial message are **marketing-page** work. The platform already surfaces the raw ingredients (tier prices, programme standard/member prices, the "includes 12 months membership" note). The curated landing page itself — the "Choose How You Want to Begin" narrative, the "Most Popular" badge on Annual, the primary/secondary hierarchy leading with NCD Compass — should be built as a **dedicated Academy landing page** (custom page), which we can produce to your §17 hierarchy. It's design/content, not billing logic.

The **Capability Assessment** routing ("Not sure where to start?") is a CRM quiz/workflow that recommends a programme; the platform can gate/grant based on the outcome tag.

---

## 9. Recommended sequence

1. **Confirm §3-C** (ecosystem benefits driven by CRM tags). §3-A (annual-only pricing) and §3-B (comp reset) are already built and enabled — just sanity-check they behave as you expect.
2. **Confirm the programme mapping** in §5 (names, the two Compass records, the $1 test item).
3. Platform data pass: add the four programmes, correct the three prices, rename the membership. *(The pricing/comp logic is already done.)*
4. CRM pass (GHL): tags, custom fields, the renewal sequence, onboarding/journey workflows, and the B2B enquiry form for teams/institutions.
5. Landing page build to the §17 hierarchy.

Step 3 is now just a data/copy pass — the behavioural logic it used to depend on is live. Steps 4–5 are CRM/marketing and run in parallel. The only large, separate effort — if and when you want it — is the seat-based team/organizational subsystem in §6.

---

### Quick status legend for your brief

- **Ready now (config/data):** membership $20/$200, complimentary 12-month grants, programme member pricing, membership status & expiry, past-due grace, programme "includes membership" note, **annual-only member pricing (on)**, **comp reset-to-12-months (on)**.
- **Data/copy pass, pending your OK:** add the four programmes, correct the three prices, membership rename.
- **CRM (GHL) build:** tags, custom fields, renewal reminders, onboarding/journey, B2B enquiry form.
- **New subsystem (future):** team/organizational seats & institutional cohort billing.
