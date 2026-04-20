# Stripe Integration Runbook

This document describes how Stripe currently works in this codebase for:
- Platform signup billing (academy creation)
- Tenant Stripe Connect onboarding
- Student bundle checkout (charged on connected tenant account)
- Webhook-driven activation and idempotency

## 1) Endpoints and Responsibilities

### Platform billing
- `GET/POST /start-academy/` -> create pending tenant/admin + create Stripe Checkout Session
- `GET /start-academy/checkout-success/` -> fallback activation after successful checkout return
- `POST /webhooks/stripe/` -> authoritative Stripe event processing

### Tenant Stripe Connect
- `GET /dashboard/payments/stripe/connect/` -> starts OAuth redirect to Stripe
- `GET /dashboard/payments/stripe/callback/` -> exchanges code, stores connected account state

### Student bundle checkout
- `POST /bundles/<bundle_id>/checkout/` -> creates Stripe Checkout Session against tenant connected account

### Billing self-service
- `GET /dashboard/billing/` -> tenant billing page
- `GET /dashboard/billing/portal/` -> Stripe Billing Portal session for platform subscription customer

## 2) Data Stored

### Tenant
- `plan_code` (`lean|baseline|growth`)
- `billing_status` (`pending|active|past_due|canceled`)
- `stripe_customer_id`
- `stripe_subscription_id`

### TenantConfig
- `stripe_connect_account_id`
- `stripe_connect_onboarding_complete`
- `stripe_connect_charges_enabled`

### StripeEventLog
- Stores Stripe `event_id` + `event_type` for webhook idempotency.

## 3) Flow A: Platform Signup Billing (Start Academy)

### Step-by-step
1. User submits `/start-academy/` with academy/admin info + selected plan.
2. System creates:
   - `Tenant` in `pending` + inactive state
   - pending admin `User` (inactive)
3. System creates Stripe Checkout Session with:
   - mode from `START_ACADEMY_CHECKOUT_MODE` (`subscription` default, can be `payment`)
   - dynamic `price_data` from amount envs
   - server-side idempotency key (`start-academy:<uuid>`)
   - metadata: `tenant_id`, `admin_user_id`, `plan_code`, `signup_checkout_mode`
   - `after_expiration.recovery.enabled = true`
   - extended session expiry
4. User is redirected to Stripe Checkout URL.
5. On completion:
   - Browser return hits `/start-academy/checkout-success/` (fallback activation path)
   - Webhook `checkout.session.completed` activates tenant/admin (primary path)

### Activation behavior
Activation sets:
- `Tenant.is_active = True`
- `Tenant.billing_status = active`
- `Tenant.stripe_customer_id` / `stripe_subscription_id`
- admin user active + staff
- tenant admin membership via `TenantMembership.update_or_create(...)`

### Expired checkout cleanup
Webhook `checkout.session.expired` removes abandoned pending tenant/admin records (non-bundle flow), allowing clean retries.

## 4) Flow B: Tenant Stripe Connect OAuth

### Step-by-step
1. Tenant admin opens `/dashboard/payments/stripe/connect/`.
2. App builds OAuth URL with:
   - `response_type=code`
   - `scope=read_write`
   - `client_id=STRIPE_CONNECT_CLIENT_ID`
   - `state=tenant:<tenant_id>`
   - `redirect_uri=<current-host>/dashboard/payments/stripe/callback/`
3. Stripe returns `code` to callback.
4. App exchanges code (`stripe.OAuth.token`) and retrieves account details.
5. App stores:
   - `stripe_connect_account_id`
   - onboarding/details status
   - `charges_enabled` flag

### Important
- This integration uses **Standard OAuth** flow.
- Redirect URI must be allowed in your Stripe Connect settings.
- If you use multiple hostnames, each callback URI may need to be registered in Stripe.

## 5) Flow C: Student Bundle Checkout (Connected Account Charges)

### Preconditions
- Tenant context resolved
- Bundle is active and priced
- Tenant has connected Stripe account with charges enabled

### Step-by-step
1. Frontend calls `POST /bundles/<bundle_id>/checkout/`.
2. App creates Checkout Session in `payment` mode.
3. Session is created with `stripe_account=<tenant connected account id>`.
4. Metadata includes `flow=bundle_checkout`, `tenant_id`, `bundle_id`, `user_id`.
5. Webhook `checkout.session.completed` with `flow=bundle_checkout`:
   - creates `BundlePurchase` if not already present
   - grants access via `grant_bundle_access(...)`

## 6) Webhook Events Consumed

Endpoint: `POST /webhooks/stripe/`

Currently handled:
- `checkout.session.completed`
  - platform signup activation OR bundle purchase fulfillment (by metadata flow)
- `checkout.session.expired`
  - cleanup for abandoned pending signup attempts
- `invoice.payment_failed`
  - marks tenant `billing_status=past_due`
- `customer.subscription.deleted`
  - marks tenant canceled + inactive

Idempotency:
- Every Stripe event ID is persisted in `StripeEventLog`.
- Duplicate event IDs are ignored safely.

## 7) Environment Variables

### Required
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CONNECT_CLIENT_ID`

### Platform plan pricing (amount in cents)
- `STRIPE_PLAN_AMOUNT_LEAN_USD`
- `STRIPE_PLAN_AMOUNT_BASELINE_USD`
- `STRIPE_PLAN_AMOUNT_GROWTH_USD`

### Behavior toggles
- `START_ACADEMY_CHECKOUT_MODE` -> `subscription` or `payment`
- `ALLOW_LIVE_TEST_PRICING` -> allows very low live amounts for temporary testing

### Other related vars
- `PLATFORM_BASE_DOMAIN` -> used for tenant domain generation/routing
- `STRIPE_CONNECT_REDIRECT_BASE_URL` -> present in env; currently not used by OAuth builder in code

## 8) Local and Production Setup Checklist

1. Configure all required Stripe env vars.
2. Restart app after env updates.
3. Register webhook endpoint in Stripe Dashboard:
   - URL: `/webhooks/stripe/`
   - events listed in section 6
4. Register Stripe Connect callback URL(s):
   - `/dashboard/payments/stripe/callback/` on each active host used for Connect
5. Validate end-to-end:
   - start academy checkout
   - webhook activation
   - connect tenant account
   - student bundle checkout and access grant

## 9) Common Troubleshooting

### "Your order has been updated..."
- Usually stale/expired Checkout session or replayed session URL.
- This code mitigates with server idempotency, no-cache headers, and recovery-enabled sessions.

### Checkout completed but tenant not active yet
- Callback path attempts fallback activation.
- Confirm webhook delivery and signature secret correctness.

### Connect says "Standard OAuth is disabled"
- Enable Standard OAuth in Stripe Connect settings for your integration.

### Bundle checkout says tenant not connected
- Ensure `stripe_connect_account_id` exists and `stripe_connect_charges_enabled=True`.

## 10) Security Notes

- Never expose secret keys in client code.
- Never commit real Stripe secrets to git.
- Keep webhook secret environment-specific.
- Rely on signed webhook verification + event idempotency for fulfillment safety.
