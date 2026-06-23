"""GHL integration views.

Phase 0 surface:
  * ``ghl_settings``   — admin scaffold: connection status + connect/disconnect.
  * ``ghl_connect``    — start OAuth: build signed state, redirect to GHL.
  * ``ghl_callback``   — ONE central redirect URI for all tenants. Validates the
                         signed state (also our CSRF defense), resolves the
                         tenant from it, exchanges the code, stores creds, then
                         302s back to the tenant's own domain.
  * ``ghl_disconnect`` — revoke locally + flip the feature flag off.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .integrations.ghl import config, oauth, state
from .models import GHLConnection
from .utils.domains import get_tenant_public_home_url
from .utils.tenancy import resolve_request_tenant

logger = logging.getLogger("myApp.ghl")


# ─── Gating helpers ───

def _admin_tenant(request):
    """Return the tenant this user may administer, or None.

    Superusers operate on the impersonated tenant; otherwise the user must hold
    an active ``tenant_admin`` membership on the resolved tenant.
    """
    tenant = resolve_request_tenant(request)
    if tenant is None:
        return None
    user = request.user
    if user.is_superuser:
        return tenant
    from .models import TenantMembership
    is_admin = TenantMembership.objects.filter(
        tenant=tenant, user=user, role="tenant_admin", is_active=True
    ).exists()
    return tenant if is_admin else None


def _settings_redirect(request, tenant, status):
    """Absolute URL back to the tenant's own GHL settings page."""
    base = (get_tenant_public_home_url(request, tenant) or "/").rstrip("/")
    return redirect(f"{base}{reverse('ghl_settings')}?ghl={status}")


# ─── Views ───

@login_required
def ghl_settings(request):
    tenant = _admin_tenant(request)
    if tenant is None:
        messages.error(request, "You don't have access to integration settings.")
        return redirect("dashboard_home")

    connection = GHLConnection.objects.filter(tenant=tenant).first()
    ctx = {
        "tenant": tenant,
        "connection": connection,
        "ghl_configured": config.is_configured(),
        "ghl_status": request.GET.get("ghl", ""),
        "scopes": config.scopes().split(),
    }
    return render(request, "dashboard/ghl_settings.html", ctx)


@login_required
@require_http_methods(["POST"])
def ghl_connect(request):
    tenant = _admin_tenant(request)
    if tenant is None:
        messages.error(request, "You don't have access to connect GHL.")
        return redirect("dashboard_home")

    if not config.is_configured():
        messages.error(request, "GHL is not configured on this server. Contact support.")
        return redirect("ghl_settings")

    signed_state = state.encode(tenant.id)
    return redirect(oauth.build_authorize_url(signed_state))


@require_http_methods(["GET"])
def ghl_callback(request):
    """Central OAuth callback shared by every tenant.

    Tenant identity comes from the signed ``state`` (NOT the host), which is also
    our CSRF guard. We never trust the host here.
    """
    error = request.GET.get("error")
    raw_state = request.GET.get("state", "")
    code = request.GET.get("code", "")

    # Resolve tenant from state first so we can redirect failures somewhere sane.
    try:
        payload = state.decode(raw_state)
    except signing.BadSignature:
        logger.warning("GHL callback: bad/expired state")
        return redirect("dashboard_home")

    from .models import Tenant
    tenant = Tenant.objects.filter(id=payload.get("t")).first()
    if tenant is None:
        logger.warning("GHL callback: state references unknown tenant %s", payload.get("t"))
        return redirect("dashboard_home")

    if error or not code:
        logger.info("GHL callback: provider returned error=%s (tenant %s)", error, tenant.slug)
        return _settings_redirect(request, tenant, "error")

    # Exchange the code for tokens.
    try:
        token_payload = oauth.exchange_code(code)
    except oauth.GHLOAuthError as exc:
        logger.error("GHL callback: code exchange failed for %s: %s", tenant.slug, exc)
        return _settings_redirect(request, tenant, "error")

    location_id = token_payload.get("locationId")
    company_id = token_payload.get("companyId", "")

    # We target a Sub-account install, so locationId should be present. An
    # agency-only token (companyId, no locationId) can't be auto-bound to a
    # location here; surface it rather than silently storing a half-connection.
    if not location_id:
        logger.error("GHL callback: token had no locationId for %s (companyId=%s)",
                     tenant.slug, company_id)
        return _settings_redirect(request, tenant, "needs_location")

    connection, _ = GHLConnection.objects.get_or_create(
        tenant=tenant,
        defaults={"ghl_location_id": location_id},
    )
    connection.ghl_location_id = location_id
    connection.ghl_company_id = company_id
    connection.connected_at = timezone.now()
    connection.apply_token_payload(token_payload)
    connection.save()

    # Connecting == enabling. No global on-switch.
    if not tenant.ghl_enabled:
        tenant.ghl_enabled = True
        tenant.save(update_fields=["ghl_enabled", "updated_at"])

    logger.info("GHL connected for tenant %s location %s", tenant.slug, location_id)
    return _settings_redirect(request, tenant, "connected")


@login_required
@require_http_methods(["POST"])
def ghl_disconnect(request):
    tenant = _admin_tenant(request)
    if tenant is None:
        messages.error(request, "You don't have access to disconnect GHL.")
        return redirect("dashboard_home")

    GHLConnection.objects.filter(tenant=tenant).delete()
    if tenant.ghl_enabled:
        tenant.ghl_enabled = False
        tenant.save(update_fields=["ghl_enabled", "updated_at"])
    messages.success(request, "GoHighLevel disconnected.")
    return redirect("ghl_settings")
