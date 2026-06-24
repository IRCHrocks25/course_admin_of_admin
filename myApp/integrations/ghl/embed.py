"""Resolve which CourseForge user a GHL sidebar visitor logs in as, and write
the audit row. Policy: email-match an active tenant admin, else owner fallback."""
from __future__ import annotations

from typing import Optional, Tuple

from myApp.models import TenantMembership
from myApp.models_ghl import GhlEmbedSession
from .user_context import GhlUserContext


def _tenant_owner(tenant):
    """Primary admin = earliest active tenant_admin membership."""
    membership = (
        TenantMembership.objects.filter(tenant=tenant, role="tenant_admin", is_active=True)
        .order_by("id")
        .select_related("user")
        .first()
    )
    return membership.user if membership else None


def resolve_user(tenant, ctx: GhlUserContext) -> Tuple[Optional[object], bool]:
    """Return (user, impersonated_owner)."""
    if ctx.email:
        membership = (
            TenantMembership.objects.filter(
                tenant=tenant, is_active=True, user__email__iexact=ctx.email
            )
            .select_related("user")
            .first()
        )
        if membership:
            return membership.user, False
    return _tenant_owner(tenant), True


def record_session(*, tenant, connection, ctx: GhlUserContext, user, impersonated, request) -> GhlEmbedSession:
    return GhlEmbedSession.objects.create(
        tenant=tenant,
        connection=connection,
        ghl_location_id=ctx.location_id,
        ghl_user_id=ctx.user_id,
        ghl_email=ctx.email,
        ghl_user_name=ctx.user_name,
        ghl_role=ctx.role,
        ghl_user_type=ctx.user_type or ctx.type,
        resolved_user=user,
        impersonated_owner=impersonated,
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
    )
