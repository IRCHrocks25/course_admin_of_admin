"""
Student membership helpers.

A tenant can offer an optional recurring membership (see ``MembershipPlan``).
While a student has an active ``StudentSubscription``, they get access to the
tenant's whole catalog (all active, non-private courses) without a per-course
``CourseAccess`` row. Membership is the source of truth so courses added later
are automatically included.
"""
from django.utils import timezone


# Courses with these visibilities are never auto-unlocked by an all-access
# membership. `private` is manual-assignment-only; `hidden` is a direct-link-only
# course kept out of the catalog on purpose (special cohorts, separately-sold
# programmes, pre-launch), so sweeping it into "all-access" would be surprising.
# Admins who genuinely want such a course in the membership can flip its
# visibility to public/members_only. `members_only` (logged-in visible) stays
# included — it's part of the catalog, just gated behind login.
MEMBERSHIP_EXCLUDED_VISIBILITIES = frozenset({'private', 'hidden'})

# Backwards-compatible alias (was a single value before hidden was added).
MEMBERSHIP_EXCLUDED_VISIBILITY = 'private'


def past_due_grace_days(tenant):
    """Days a past-due member keeps access during Stripe dunning (0 if unset)."""
    if tenant is None:
        return 0
    plan = getattr(tenant, 'membership_plan', None)
    if plan is None:
        from ..models import MembershipPlan
        plan = MembershipPlan.objects.filter(tenant=tenant).first()
    return getattr(plan, 'past_due_grace_days', 0) or 0


def get_active_subscription(user, tenant):
    """
    Return the user's access-granting StudentSubscription for the tenant, or None.

    Grants access when status='active' (and not past its period end) or, when the
    plan configures a grace window, status='past_due' still within that window.
    Complimentary memberships have no period end and count as active.
    """
    if not user or not getattr(user, 'is_authenticated', False) or tenant is None:
        return None

    from ..models import StudentSubscription

    sub = StudentSubscription.objects.filter(
        user=user, tenant=tenant, status__in=('active', 'past_due'),
    ).first()
    if sub and sub.is_active(past_due_grace_days=past_due_grace_days(tenant)):
        return sub
    return None


def has_active_membership(user, tenant):
    return get_active_subscription(user, tenant) is not None


def course_covered_by_membership(course):
    """Whether an *all-access* membership would unlock this course (catalog gate)."""
    if course is None:
        return False
    if course.status != 'active':
        return False
    if course.visibility in MEMBERSHIP_EXCLUDED_VISIBILITIES:
        return False
    if not getattr(course, 'included_in_membership', True):
        return False
    return True


def _catalog_qs(tenant):
    """Base queryset of catalog courses eligible for membership (all-access set)."""
    from ..models import Course
    return Course.objects.filter(
        tenant=tenant, status='active', included_in_membership=True,
    ).exclude(
        visibility__in=MEMBERSHIP_EXCLUDED_VISIBILITIES,
    )


def _tier_effective_qs(tier):
    """
    Queryset of a tier's effective courses.

    Intentionally ignores ``is_purchasable`` / ``is_archived`` — access must
    persist for existing subscribers regardless of whether the tier still sells.
    Honors cumulative inclusion (lower-or-equal ranks) and ``includes_all`` on
    the tier *or* any lower-or-equal tier when cumulative.
    """
    from ..models import MembershipTier

    base = _catalog_qs(tier.tenant)
    plan = getattr(tier.tenant, 'membership_plan', None)
    cumulative = bool(plan and plan.tiers_cumulative)

    if cumulative:
        lower = MembershipTier.objects.filter(tenant=tier.tenant, rank__lte=tier.rank)
        if tier.includes_all or lower.filter(includes_all=True).exists():
            return base
        return base.filter(membership_tiers__in=lower).distinct()

    if tier.includes_all:
        return base
    return base.filter(membership_tiers=tier).distinct()


def tier_course_ids(tier):
    """Set of course IDs a tier unlocks (empty for None)."""
    if tier is None:
        return set()
    return set(_tier_effective_qs(tier).values_list('id', flat=True))


def membership_covers_course(user, course):
    """True when the user's active membership unlocks this specific course."""
    if course is None:
        return False
    sub = get_active_subscription(user, course.tenant)
    if sub is None:
        return False
    if sub.access_mode == 'all_access':
        return course_covered_by_membership(course)
    if sub.tier_id is None:
        return False  # constraint should prevent this
    # Single-id existence check — don't build the whole set to test one course.
    return _tier_effective_qs(sub.tier).filter(id=course.id).exists()


def get_membership_course_ids(user, tenant):
    """
    Course IDs unlocked for this user via an active membership (empty if none).
    """
    sub = get_active_subscription(user, tenant)
    if sub is None:
        return set()
    if sub.access_mode == 'all_access':
        return set(_catalog_qs(tenant).values_list('id', flat=True))
    return tier_course_ids(sub.tier)


def sync_subscription_from_stripe(subscription, stripe_sub):
    """
    Update a StudentSubscription from a Stripe subscription object (dict-like).

    Maps Stripe status to our status, refreshes current_period_end, and stamps
    last_synced_at. Caller is responsible for saving related fields if needed.
    """
    status_map = {
        'active': 'active',
        'trialing': 'active',
        'past_due': 'past_due',
        'unpaid': 'past_due',
        'incomplete': 'incomplete',
        'incomplete_expired': 'canceled',
        'canceled': 'canceled',
    }
    stripe_status = stripe_sub.get('status') if stripe_sub else None
    if stripe_status:
        subscription.status = status_map.get(stripe_status, subscription.status)

    period_end = stripe_sub.get('current_period_end') if stripe_sub else None
    if period_end:
        import datetime
        subscription.current_period_end = datetime.datetime.fromtimestamp(
            period_end, tz=datetime.timezone.utc,
        )

    if subscription.status == 'canceled' and not subscription.canceled_at:
        subscription.canceled_at = timezone.now()

    subscription.last_synced_at = timezone.now()
    return subscription


def member_pricing_eligible(user, tenant):
    """
    Whether the user qualifies for member pricing on courses.

    Any active membership qualifies, unless the plan sets
    ``member_pricing_requires_annual`` — then only annual or complimentary
    members qualify (monthly members get ecosystem benefits, not the discount).
    """
    sub = get_active_subscription(user, tenant)
    if sub is None:
        return False

    plan = getattr(tenant, 'membership_plan', None)
    if plan is None:
        from ..models import MembershipPlan
        plan = MembershipPlan.objects.filter(tenant=tenant).first()

    if plan is not None and plan.member_pricing_requires_annual:
        return bool(sub.is_complimentary or sub.interval == 'year')
    return True


def effective_course_price(user, course):
    """
    Price the given user should pay for a course right now.
    Members pay member_price when one is set and they're pricing-eligible.
    Returns a Decimal or None (free / not purchasable).
    """
    if course is None:
        return None
    base = course.price
    member_price = getattr(course, 'member_price', None)
    if member_price is not None and member_pricing_eligible(user, course.tenant):
        return member_price
    return base


def expire_lapsed_subscriptions(tenant=None, now=None, paid_grace_hours=72):
    """
    Flip memberships that are still status='active' but whose period has ended.

    This is the reconciliation safety net for the two cases webhooks can't cover:

    * Complimentary grants have no Stripe subscription, so nothing ever fires to
      end them. Once ``current_period_end`` passes they must be expired here.
    * Paid subscriptions on tenants with their own Stripe keys can drift if a
      renewal webhook is missed. We give those a grace window (``paid_grace_hours``)
      so a slightly-late ``invoice.paid`` can renew them before we expire.

    Rows are moved to status='expired' (distinct from admin/Stripe 'canceled').
    Access checks already deny anything that isn't active-and-in-period, so this
    only makes the stored status honest for reporting and dashboards.

    Returns the number of subscriptions expired.
    """
    import datetime

    from ..models import StudentSubscription

    now = now or timezone.now()
    paid_cutoff = now - datetime.timedelta(hours=max(paid_grace_hours, 0))

    qs = StudentSubscription.objects.filter(
        status='active', current_period_end__isnull=False,
    )
    if tenant is not None:
        qs = qs.filter(tenant=tenant)

    expired = 0
    for sub in qs.iterator():
        is_comp = sub.is_complimentary or not sub.stripe_subscription_id
        cutoff = now if is_comp else paid_cutoff
        if sub.current_period_end <= cutoff:
            sub.status = 'expired'
            if not sub.canceled_at:
                sub.canceled_at = now
            sub.last_synced_at = now
            sub.save(update_fields=['status', 'canceled_at', 'last_synced_at', 'updated_at'])
            expired += 1

    return expired


def grant_complimentary_membership(user, tenant, months, interval='year', tier=None):
    """
    Grant or extend a complimentary membership for `months` months.

    Used when a course purchase includes membership. If the student already has
    an active *paid* membership we leave it alone (a comp never clobbers or
    downgrades a paying member); otherwise we create/extend a complimentary
    subscription. Extends from the later of now or the current period end so
    stacking programme purchases adds time.

    ``tier`` targets a specific MembershipTier (access_mode='tiered'); None grants
    all-access (access_mode='all_access'), preserving legacy behavior.
    """
    if not months or months <= 0 or tenant is None:
        return None

    from ..models import StudentSubscription
    from dateutil.relativedelta import relativedelta

    sub, _ = StudentSubscription.objects.get_or_create(
        tenant=tenant, user=user,
        defaults={'interval': interval, 'status': 'incomplete'},
    )

    # A comp must never downgrade or overwrite an active paid membership.
    if sub.is_active() and not sub.is_complimentary:
        return sub

    now = timezone.now()
    plan = getattr(tenant, 'membership_plan', None)
    if plan is None:
        from ..models import MembershipPlan
        plan = MembershipPlan.objects.filter(tenant=tenant).first()
    reset = bool(plan and plan.comp_grant_reset)
    if reset:
        # Reset: N months from this purchase, regardless of remaining time.
        base = now
    else:
        # Extend/stack: add N months onto whatever time is left.
        base = sub.current_period_end if (sub.current_period_end and sub.current_period_end > now) else now
    sub.current_period_end = base + relativedelta(months=months)
    sub.status = 'active'
    sub.is_complimentary = True
    sub.canceled_at = None
    # Keep access_mode/tier consistent with the check constraint.
    if tier is not None:
        sub.access_mode = 'tiered'
        sub.tier = tier
    else:
        sub.access_mode = 'all_access'
        sub.tier = None
    sub.last_synced_at = now
    sub.save()
    return sub
