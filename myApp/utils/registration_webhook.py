"""Outbound Katalyst registration webhook (per-tenant, fire-and-forget)."""
from __future__ import annotations

import logging

import requests
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT = 8


def get_registration_webhook_url(tenant) -> str:
    if tenant is None:
        return ''
    from myApp.models import TenantConfig
    url = (
        TenantConfig.objects
        .filter(tenant_id=tenant.pk)
        .values_list('registration_webhook', flat=True)
        .first()
    )
    return (url or '').strip()


def build_registration_payload(tenant, user, source: str) -> dict:
    return {
        'event': 'user.registered',
        'username': getattr(user, 'username', '') or '',
        'email': getattr(user, 'email', '') or '',
        'user_id': getattr(user, 'id', 0) or 0,
        'tenant_slug': getattr(tenant, 'slug', '') or '',
        'tenant_name': getattr(tenant, 'name', '') or '',
        'source': source,
        'registered_at': timezone.now().isoformat(),
    }


def _post_webhook(url: str, payload: dict) -> tuple[bool, str]:
    try:
        response = requests.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=WEBHOOK_TIMEOUT,
        )
        if response.status_code >= 400:
            snippet = (response.text or '')[:300]
            return False, f'Webhook returned HTTP {response.status_code}: {snippet}'
        return True, ''
    except Exception as exc:
        return False, str(exc)[:300]


def notify_registration_webhook(tenant, user, source: str = 'free_signup') -> bool:
    """POST registration data to the tenant webhook. Never raises."""
    url = get_registration_webhook_url(tenant)
    if not url:
        return False
    payload = build_registration_payload(tenant, user, source)
    ok, error = _post_webhook(url, payload)
    if not ok:
        logger.warning(
            'Registration webhook failed for tenant %s user %s: %s',
            getattr(tenant, 'slug', '?'),
            getattr(user, 'username', '?'),
            error,
        )
    return ok


def schedule_registration_webhook(tenant, user, source: str = 'free_signup') -> None:
    """Run the webhook after the surrounding transaction commits."""
    tenant_id = getattr(tenant, 'pk', None)
    user_id = getattr(user, 'pk', None)
    if not tenant_id or not user_id:
        return

    def _send():
        from django.contrib.auth.models import User
        from myApp.models import Tenant

        t = Tenant.objects.filter(pk=tenant_id).first()
        u = User.objects.filter(pk=user_id).first()
        if t is None or u is None:
            return
        notify_registration_webhook(t, u, source)

    transaction.on_commit(_send)


def send_test_registration_webhook(tenant) -> tuple[bool, str]:
    """POST a synthetic payload so admins can verify the Katalyst URL."""
    url = get_registration_webhook_url(tenant)
    if not url:
        return False, 'No registration webhook URL is set.'
    payload = {
        'event': 'user.registered',
        'username': 'test-user',
        'email': 'test@example.com',
        'user_id': 0,
        'tenant_slug': getattr(tenant, 'slug', '') or '',
        'tenant_name': getattr(tenant, 'name', '') or '',
        'source': 'test',
        'registered_at': timezone.now().isoformat(),
    }
    ok, error = _post_webhook(url, payload)
    if ok:
        return True, 'Test payload sent.'
    return False, error or 'Webhook request failed.'
