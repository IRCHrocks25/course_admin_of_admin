"""Coupon helpers: shareable links, QR generation, checkout discount."""
from __future__ import annotations

import io
import logging
import re
import uuid
from decimal import Decimal

import qrcode
from django.urls import reverse

logger = logging.getLogger(__name__)


def normalize_coupon_code(raw: str) -> str:
    code = re.sub(r'[^A-Za-z0-9_-]+', '', (raw or '').strip().upper())
    return code[:50]


def build_coupon_public_url(request, coupon) -> str:
    """Absolute public URL for a coupon landing page."""
    path = reverse('coupon_landing', kwargs={'code': coupon.code})
    return request.build_absolute_uri(path)


def generate_coupon_qr_png_bytes(link: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def upload_coupon_qr_to_iceberg(coupon, link: str) -> str:
    """
    Generate a QR PNG for `link`, upload to Iceberg, return public URL (or '').
    Replaces any previous Iceberg QR for this coupon.
    """
    from myApp.utils import iceberg

    if not iceberg.is_configured():
        logger.warning('Iceberg not configured; cannot store coupon QR for %s', coupon.id)
        return ''

    if coupon.qr_code_url:
        old_key = iceberg.key_from_url(coupon.qr_code_url)
        if old_key:
            iceberg.delete(old_key)

    tenant_id = coupon.tenant_id or 0
    key = f'coupons/tenant_{tenant_id}/coupon_{coupon.id}/{uuid.uuid4().hex}.png'
    data = generate_coupon_qr_png_bytes(link)
    return iceberg.upload_bytes(data, key, 'image/png')


def session_coupon_id(request) -> int | None:
    raw = request.session.get('active_coupon_id')
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def get_session_coupon(request, tenant=None):
    from myApp.models import Coupon

    coupon_id = session_coupon_id(request)
    if not coupon_id:
        return None
    qs = Coupon.objects.filter(id=coupon_id)
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    coupon = qs.first()
    if not coupon or not coupon.is_currently_valid():
        request.session.pop('active_coupon_id', None)
        return None
    return coupon


def coupon_applies_to_course(coupon, course) -> bool:
    if coupon is None or course is None:
        return False
    if coupon.target_type == coupon.TARGET_COURSE:
        return coupon.course_id == course.id
    if coupon.target_type in (coupon.TARGET_SITE, coupon.TARGET_CUSTOM, coupon.TARGET_SIGNUP):
        return True
    return False


def coupon_applies_to_bundle(coupon, bundle) -> bool:
    if coupon is None or bundle is None:
        return False
    if coupon.target_type == coupon.TARGET_BUNDLE:
        return coupon.bundle_id == bundle.id
    if coupon.target_type in (coupon.TARGET_SITE, coupon.TARGET_CUSTOM, coupon.TARGET_SIGNUP):
        return True
    return False


def discounted_amount_cents(price, coupon) -> int:
    """Convert price + coupon into Stripe cents."""
    amount = Decimal(str(price or 0))
    if coupon is not None and not coupon.is_tracking_only():
        amount = coupon.apply_discount(amount)
    cents = int((amount * 100).quantize(Decimal('1')))
    return max(cents, 0)


def attach_signup_coupon(request, membership):
    """
    If the browser session has a valid coupon, store it on the student membership.
    Tracking-only coupons count as a use at signup and clear the session.
    Discount coupons stay in session so checkout can still apply the price off.
    """
    from django.db.models import F
    from myApp.models import Coupon

    coupon = get_session_coupon(request, membership.tenant)
    if coupon is None:
        return None

    membership.signup_coupon = coupon
    membership.save(update_fields=['signup_coupon', 'updated_at'])
    if coupon.is_tracking_only():
        Coupon.objects.filter(id=coupon.id).update(uses_count=F('uses_count') + 1)
        request.session.pop('active_coupon_id', None)
    return coupon
