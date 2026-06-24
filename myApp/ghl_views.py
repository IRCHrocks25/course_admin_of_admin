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

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import json

from django.http import HttpResponse, JsonResponse

from .integrations.ghl import config, oauth, state
from .integrations.ghl import embed as ghl_embed_helper
from .integrations.ghl import sso, user_context
from .integrations.ghl import webhook as ghl_webhook_mod
from .models import GHLConnection
from .models_ghl import GHLLink
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

    if not location_id and company_id:
        # Agency/Company install: mint a Location-scoped token. With Sub-Account
        # distribution + chooselocation this is a fallback; multi-location agency
        # picker is deferred — we use whatever location the mint resolves.
        try:
            minted = oauth.get_location_token(
                token_payload.get("access_token"), company_id, location_id or ""
            )
        except Exception:
            minted = None
        if minted and minted.get("locationId"):
            token_payload = minted
            location_id = minted.get("locationId")
            company_id = minted.get("companyId", company_id)

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


# ─── Embed + SSO views ───

def _tenant_host(tenant):
    override = getattr(settings, "GHL_EMBED_HOST_OVERRIDE", "").strip()
    base = override or getattr(settings, "PLATFORM_BASE_DOMAIN", "").strip()
    if getattr(tenant, "custom_domain", ""):
        return tenant.custom_domain
    if base:
        return f"{tenant.slug}.{base}"
    return tenant.slug


@csrf_exempt
@xframe_options_exempt
@require_http_methods(["GET"])
def ghl_embed(request):
    blob = request.GET.get("encryptedUserData") or request.GET.get("userData") or ""
    ctx = user_context.decrypt(blob, settings.GHL_SHARED_SECRET_KEY)
    if not ctx or not ctx.location_id or (ctx.type or "").lower() == "agency":
        return render(request, "ghl/embed_unauthorized.html")

    connection = (
        GHLConnection.objects.select_related("tenant")
        .filter(ghl_location_id=ctx.location_id)
        .first()
    )
    if not connection:
        return render(request, "ghl/embed_not_connected.html")

    tenant = connection.tenant
    user, impersonated = ghl_embed_helper.resolve_user(tenant, ctx)
    if user is None:
        return render(request, "ghl/embed_not_connected.html")

    audit = ghl_embed_helper.record_session(
        tenant=tenant, connection=connection, ctx=ctx,
        user=user, impersonated=impersonated, request=request,
    )

    token = sso.issue(user_id=user.id, tenant_id=tenant.id, embed_session_id=audit.id)
    host = _tenant_host(tenant)
    scheme = "http" if getattr(settings, "GHL_EMBED_HOST_OVERRIDE", "") else "https"
    return redirect(f"{scheme}://{host}/ghl/sso?t={token}&next=/dashboard")


@xframe_options_exempt
@require_http_methods(["GET"])
def ghl_sso(request):
    token = request.GET.get("t", "")
    try:
        data = sso.consume(token)
    except sso.SsoError:
        return render(request, "ghl/embed_error.html", status=403)

    if not getattr(request, "tenant", None) or request.tenant.id != data["t"]:
        return render(request, "ghl/embed_error.html", status=403)

    user = get_user_model().objects.filter(id=data["u"]).first()
    if not user:
        return render(request, "ghl/embed_error.html", status=403)

    # AUTHENTICATION_BACKENDS is unset in this project (only ModelBackend active),
    # so no explicit backend= argument is required.
    auth_login(request, user)
    request.session["ghl_embed"] = True
    request.session["ghl_actor"] = {"embed_session_id": data["e"]}

    # Open-redirect guard: only allow local relative paths. url_has_allowed_host_and_scheme
    # with allowed_hosts=None rejects //evil.com, /\evil.com, and scheme:... payloads.
    nxt = request.GET.get("next", "/dashboard")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts=None):
        nxt = "/dashboard"
    return redirect(nxt)


# ─── Webhook receiver ───

@csrf_exempt
@require_http_methods(["POST"])
def ghl_webhook(request):
    raw = request.body  # must read before parsing
    sig = request.headers.get("X-GHL-Signature", "")
    if not ghl_webhook_mod.verify(raw, sig):
        return HttpResponse(status=401)

    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        return HttpResponse(status=400)

    location_id = str(event.get("locationId") or "").strip()
    connection = (
        GHLConnection.objects.select_related("tenant")
        .filter(ghl_location_id=location_id)
        .first()
    )
    if not connection:
        return JsonResponse({"status": "ignored"})

    etype = event.get("type", "")
    tenant = connection.tenant

    if etype in ("ContactCreate", "ContactUpdate"):
        contact_id = str(event.get("id") or event.get("contactId") or "").strip()
        if contact_id:
            GHLLink.objects.update_or_create(
                tenant=tenant, ghl_contact_id=contact_id,
                defaults={"connection": connection, "sync_status": "active"},
            )
        return JsonResponse({"status": "ok"})

    if etype == "ContactDelete":
        contact_id = str(event.get("id") or event.get("contactId") or "").strip()
        GHLLink.objects.filter(tenant=tenant, ghl_contact_id=contact_id).update(sync_status="error")
        return JsonResponse({"status": "ok"})

    return JsonResponse({"status": "ignored"})
