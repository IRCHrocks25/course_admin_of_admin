"""GoHighLevel (GHL) integration models.

Two tables, deliberately split:

  * ``GHLConnection`` — ONE row per tenant. Holds the OAuth credentials and the
    connected sub-account (location). Credentials are the per-tenant secret, so
    encrypted tokens live here and nowhere else.
  * ``GHLLink`` — the contact<->student mapping; MANY rows per tenant (one per
    synced contact). Keeps no credentials. This is where ``last_synced_hash``
    drives echo suppression in later phases.

The original spec described a single "GHLLink" carrying both connection creds
and per-contact mapping. Splitting them is the only structural change: storing
single-use OAuth tokens on every contact row would force every token refresh to
rewrite thousands of rows and multiply the blast radius of a leak. Connection
creds belong on one row; mappings hang off it via FK.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from .integrations.ghl import crypto
from .models import Tenant


class GHLConnection(models.Model):
    """Per-tenant GHL OAuth connection + encrypted credentials."""

    STATUS_CHOICES = [
        ("connected", "Connected"),
        ("error", "Error"),
        ("revoked", "Revoked"),
    ]

    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name="ghl_connection"
    )

    # The connected sub-account. company_id is set for agency installs that need
    # the agency->location token exchange.
    ghl_location_id = models.CharField(max_length=128, unique=True)
    ghl_company_id = models.CharField(max_length=128, blank=True, default="")

    # Encrypted at rest (Fernet). Never expose raw columns; use the accessors.
    access_token_encrypted = models.TextField(blank=True, default="")
    refresh_token_encrypted = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)

    scope = models.TextField(blank=True, default="")
    # Comma-separated GHL calendar ids whose events sync into live Events (the
    # webinar / class-booking calendars). Empty = this tenant syncs no events.
    event_calendar_ids = models.TextField(blank=True, default="")
    sync_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="connected")
    status_detail = models.CharField(max_length=255, blank=True, default="")

    connected_at = models.DateTimeField(default=timezone.now)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "GHL Connection"
        verbose_name_plural = "GHL Connections"
        indexes = [
            models.Index(fields=["sync_status"]),
            models.Index(fields=["token_expires_at"]),
        ]

    def __str__(self):
        return f"GHL[{self.tenant.slug}] {self.ghl_location_id} ({self.sync_status})"

    # ─── Credential accessors ───
    def set_access_token(self, value):
        self.access_token_encrypted = crypto.encrypt(value or "")

    def get_access_token(self):
        return crypto.decrypt(self.access_token_encrypted)

    def set_refresh_token(self, value):
        self.refresh_token_encrypted = crypto.encrypt(value or "")

    def get_refresh_token(self):
        return crypto.decrypt(self.refresh_token_encrypted)

    def apply_token_payload(self, payload: dict):
        """Persist a GHL token response onto this connection.

        Used by both the initial code exchange and every refresh. Rotates the
        refresh token (single-use) and recomputes expiry from ``expires_in``.
        """
        self.set_access_token(payload.get("access_token", ""))
        # GHL returns a NEW refresh_token on refresh; always take it when present.
        if payload.get("refresh_token"):
            self.set_refresh_token(payload["refresh_token"])
        expires_in = payload.get("expires_in")
        if expires_in:
            self.token_expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        if payload.get("scope"):
            self.scope = payload["scope"]
        if payload.get("locationId"):
            self.ghl_location_id = payload["locationId"]
        if payload.get("companyId"):
            self.ghl_company_id = payload["companyId"]
        self.last_refreshed_at = timezone.now()
        self.sync_status = "connected"
        self.status_detail = ""

    def mark_error(self, detail: str):
        self.sync_status = "error"
        self.status_detail = (detail or "")[:255]

    @property
    def is_healthy(self):
        return self.sync_status == "connected" and bool(self.access_token_encrypted)


class GHLLink(models.Model):
    """Maps a GHL contact to a CourseForge student (email is the join key).

    One row per synced contact. ``last_synced_hash`` records what we last wrote
    outbound so inbound webhooks that merely echo our own write can be dropped
    (echo suppression, Phase 3).
    """

    SYNC_STATUS_CHOICES = [
        ("active", "Active"),
        ("error", "Error"),
        ("unmatched", "Unmatched"),
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="ghl_links"
    )
    connection = models.ForeignKey(
        GHLConnection, on_delete=models.CASCADE, related_name="links"
    )
    ghl_contact_id = models.CharField(max_length=128)
    student = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ghl_links", null=True, blank=True
    )

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_synced_hash = models.CharField(max_length=64, blank=True, default="")
    sync_status = models.CharField(max_length=20, choices=SYNC_STATUS_CHOICES, default="active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "GHL Link"
        verbose_name_plural = "GHL Links"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "ghl_contact_id"], name="uniq_ghllink_tenant_contact"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "student"]),
            models.Index(fields=["tenant", "sync_status"]),
        ]

    def __str__(self):
        who = self.student.email if self.student_id else "unmatched"
        return f"GHLLink[{self.tenant.slug}] {self.ghl_contact_id} -> {who}"


class GhlEmbedSession(models.Model):
    """Audit trail for GHL sidebar auto-logins. Captures the real GHL identity
    behind each embed login so owner-fallback impersonations are attributable."""

    tenant = models.ForeignKey("myApp.Tenant", on_delete=models.CASCADE, related_name="ghl_embed_sessions")
    connection = models.ForeignKey("myApp.GHLConnection", on_delete=models.SET_NULL, null=True, blank=True)
    ghl_location_id = models.CharField(max_length=128, blank=True, default="")
    ghl_user_id = models.CharField(max_length=128, blank=True, default="")
    ghl_email = models.CharField(max_length=255, blank=True, default="")
    ghl_user_name = models.CharField(max_length=255, blank=True, default="")
    ghl_role = models.CharField(max_length=64, blank=True, default="")
    ghl_user_type = models.CharField(max_length=64, blank=True, default="")
    resolved_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    impersonated_owner = models.BooleanField(default=False)
    django_session_key = models.CharField(max_length=64, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["ghl_location_id"]),
        ]

    def __str__(self):
        return f"GhlEmbedSession(t={self.tenant_id}, loc={self.ghl_location_id}, owner={self.impersonated_owner})"
