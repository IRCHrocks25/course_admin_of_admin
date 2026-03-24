# Stripe Integration Runbook

## What was implemented

- Platform signup billing at `start_academy` with plan selection (`lean`, `baseline`, `growth`).
- Stripe Checkout subscription session before academy activation.
- Stripe webhook endpoint: `/webhooks/stripe/`.
- Idempotent webhook processing via `StripeEventLog`.
- Tenant Stripe Connect onboarding endpoints in dashboard:
  - `/dashboard/payments/stripe/connect/`
  - `/dashboard/payments/stripe/callback/`
- Student bundle checkout endpoint:
  - `POST /bundles/<bundle_id>/checkout/`

## Data model additions

- `Tenant.plan_code`
- `Tenant.billing_status`
- `Tenant.stripe_customer_id`
- `Tenant.stripe_subscription_id`
- `TenantConfig.stripe_connect_account_id`
- `TenantConfig.stripe_connect_onboarding_complete`
- `TenantConfig.stripe_connect_charges_enabled`
- `StripeEventLog` for webhook idempotency

## Required environment variables

Set these in deployment:

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CONNECT_CLIENT_ID`
- `STRIPE_PRICE_ID_LEAN`
- `STRIPE_PRICE_ID_BASELINE`
- `STRIPE_PRICE_ID_GROWTH`

## Operational notes

- New academy signups remain inactive until Stripe webhook confirms checkout completion.
- Existing tenants are not deactivated by migration; `billing_status` defaults to `active`.
- Student bundle checkout requires tenant Stripe Connect with `charges_enabled=true`.
- Duplicate webhook deliveries are ignored using `StripeEventLog.event_id`.

## Verify checklist

1. Run migrations.
2. Configure Stripe env vars.
3. Create Stripe webhook endpoint to `/webhooks/stripe/` with events:
   - `checkout.session.completed`
   - `invoice.payment_failed`
   - `customer.subscription.deleted`
4. Test `start-academy` end-to-end with Stripe test mode.
5. Connect a tenant Stripe account from Domain Settings.
6. Trigger a bundle checkout as student and verify:
   - `BundlePurchase` created
   - Access granted via `grant_bundle_access()`
