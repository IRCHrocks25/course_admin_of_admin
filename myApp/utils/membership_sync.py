"""
Pull-based reconciliation of paid student memberships from Stripe.

Webhooks are the primary path for keeping ``StudentSubscription`` in sync, but
own-keys / Stripe Connect tenants can drift when an event is missed (endpoint
not configured, transient failure, etc.). This module pulls the current
subscription state directly from Stripe on demand — from a scheduled job and
when a member returns from the billing portal — so records self-heal.

Kept separate from ``membership.py`` (which is deliberately Stripe-free) because
everything here needs the Stripe SDK and per-tenant key/account resolution.
"""
import os
from decimal import Decimal

import stripe
from django.db.models import Q
from django.utils import timezone

from .membership import sync_subscription_from_stripe


def _tenant_stripe_context(tenant):
    """
    Resolve how to talk to Stripe for this tenant.

    Returns (ready, request_kwargs, error). ``request_kwargs`` carries
    ``stripe_account`` for Connect tenants so retrieve() hits the connected
    account. Mirrors the own-keys > Connect precedence used elsewhere.
    """
    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(
        config and config.stripe_connect_account_id and config.stripe_connect_charges_enabled
    )

    if use_own_keys:
        stripe.api_key = config.stripe_own_secret_key.strip()
        return True, {}, ''
    if use_connect:
        key = os.getenv('STRIPE_SECRET_KEY', '').strip()
        if not key:
            return False, {}, 'Platform Stripe key not configured.'
        stripe.api_key = key
        return True, {'stripe_account': config.stripe_connect_account_id}, ''
    return False, {}, 'Payments are not configured for this academy.'


def _safe_archive_price(price_id, req_kwargs):
    """Best-effort archive of a now-stale Stripe Price (immutable, can't edit amount)."""
    if not price_id:
        return
    try:
        stripe.Price.modify(price_id, active=False, **req_kwargs)
    except Exception:
        pass


def sync_tier_prices(tier):
    """
    Upsert persistent Stripe Product + Price objects for a membership tier.

    Stores ``stripe_product_id`` and ``stripe_monthly_price_id`` /
    ``stripe_yearly_price_id`` on the tier. Stripe Prices are immutable, so a
    changed amount archives the old price and creates a new one. A cleared price
    archives and forgets the id. Own-keys and Connect tenants both supported.

    Returns (ok: bool, error: str). ok=False leaves the tier saved but without a
    usable price id (checkout will refuse until Stripe is configured).
    """
    if tier is None:
        return False, 'No tier.'

    ready, req_kwargs, err = _tenant_stripe_context(tier.tenant)
    if not ready:
        return False, err

    try:
        if not tier.stripe_product_id:
            product = stripe.Product.create(
                name=f"{tier.tenant.slug} — {tier.name}",
                metadata={'membership_tier_id': str(tier.id)},
                **req_kwargs,
            )
            tier.stripe_product_id = product.id

        for interval, attr, amount in (
            ('month', 'stripe_monthly_price_id', tier.monthly_price),
            ('year', 'stripe_yearly_price_id', tier.yearly_price),
        ):
            current_id = getattr(tier, attr)
            if amount is None or amount <= 0:
                if current_id:
                    _safe_archive_price(current_id, req_kwargs)
                    setattr(tier, attr, '')
                continue

            cents = int((Decimal(str(amount)) * 100).quantize(Decimal('1')))
            reuse = False
            if current_id:
                try:
                    existing = stripe.Price.retrieve(current_id, **req_kwargs)
                    reuse = bool(
                        existing and existing.get('unit_amount') == cents
                        and existing.get('active')
                    )
                except Exception:
                    reuse = False
            if reuse:
                continue

            if current_id:
                _safe_archive_price(current_id, req_kwargs)
            price = stripe.Price.create(
                product=tier.stripe_product_id,
                unit_amount=cents,
                currency='usd',
                recurring={'interval': interval},
                metadata={'membership_tier_id': str(tier.id)},
                **req_kwargs,
            )
            setattr(tier, attr, price.id)

        tier.save(update_fields=[
            'stripe_product_id', 'stripe_monthly_price_id',
            'stripe_yearly_price_id', 'updated_at',
        ])
        return True, ''
    except Exception as exc:
        return False, str(exc)


def tier_for_price_id(tenant, price_id):
    """Find the tenant's MembershipTier that owns a Stripe price id, or None."""
    if not price_id or tenant is None:
        return None
    from ..models import MembershipTier
    return (
        MembershipTier.objects.filter(tenant=tenant)
        .filter(Q(stripe_monthly_price_id=price_id) | Q(stripe_yearly_price_id=price_id))
        .first()
    )


def _subscription_price_id(stripe_sub):
    """Pull the first line item's price id from a Stripe subscription object."""
    if not stripe_sub:
        return ''
    try:
        items = (stripe_sub.get('items') or {}).get('data') or []
        if items:
            price = items[0].get('price') or {}
            return price.get('id') or ''
    except (AttributeError, KeyError, IndexError, TypeError):
        pass
    return ''


def reconcile_subscription_tier(subscription, stripe_sub):
    """
    Repair a subscription's tier from Stripe when it drifts (e.g. a customer
    switched price in the billing portal, or state was rebuilt).

    Maps the subscription's current price id → MembershipTier and, if it differs
    from what we hold, updates ``tier``/``access_mode``. Falls back to the
    subscription's ``metadata.membership_tier_id``. Never touches a subscription
    we can't positively map (leaves comps / all-access alone).

    Returns True when it changed the tier.
    """
    if subscription is None or stripe_sub is None:
        return False

    tier = tier_for_price_id(subscription.tenant, _subscription_price_id(stripe_sub))
    if tier is None:
        meta = stripe_sub.get('metadata') or {}
        tier_id = meta.get('membership_tier_id')
        if tier_id:
            from ..models import MembershipTier
            tier = MembershipTier.objects.filter(id=tier_id, tenant=subscription.tenant).first()

    if tier is not None and subscription.tier_id != tier.id:
        subscription.tier = tier
        subscription.access_mode = 'tiered'
        return True
    return False


def pull_subscription_from_stripe(subscription):
    """
    Refresh a single StudentSubscription's status/period (and tier) from Stripe.

    No-op (returns changed=False) for complimentary memberships or any sub
    without a Stripe subscription id — there is nothing to pull for those.

    Returns (changed: bool, error: str). ``changed`` is True when the pull
    altered the stored status, current_period_end, or tier.
    """
    if subscription is None:
        return False, 'No subscription.'
    if subscription.is_complimentary or not subscription.stripe_subscription_id:
        return False, ''

    ready, req_kwargs, err = _tenant_stripe_context(subscription.tenant)
    if not ready:
        return False, err

    try:
        stripe_sub = stripe.Subscription.retrieve(
            subscription.stripe_subscription_id, **req_kwargs,
        )
    except Exception as exc:
        return False, str(exc)

    before = (subscription.status, subscription.current_period_end, subscription.tier_id)
    sync_subscription_from_stripe(subscription, stripe_sub)
    reconcile_subscription_tier(subscription, stripe_sub)
    if subscription.status == 'canceled' and not subscription.canceled_at:
        subscription.canceled_at = timezone.now()
    subscription.save()
    after = (subscription.status, subscription.current_period_end, subscription.tier_id)
    return before != after, ''


def sync_paid_subscriptions(tenant=None, statuses=None):
    """
    Pull Stripe state for every paid, non-complimentary subscription.

    Intended for a scheduled job. Skips comps automatically. By default it only
    refreshes subs that could still change (active / past_due / incomplete);
    already-terminal rows (canceled / expired) are left alone.

    Returns a summary dict: {checked, changed, errors}.
    """
    from ..models import StudentSubscription

    if statuses is None:
        statuses = ('active', 'past_due', 'incomplete')

    qs = (
        StudentSubscription.objects
        .filter(is_complimentary=False, status__in=statuses)
        .exclude(stripe_subscription_id='')
        .select_related('tenant', 'tenant__config', 'user')
    )
    if tenant is not None:
        qs = qs.filter(tenant=tenant)

    checked = changed = errors = 0
    error_detail = []
    for sub in qs.iterator():
        checked += 1
        did_change, err = pull_subscription_from_stripe(sub)
        if err:
            errors += 1
            error_detail.append((sub, err))
        elif did_change:
            changed += 1

    return {
        'checked': checked,
        'changed': changed,
        'errors': errors,
        'error_detail': error_detail,
    }
