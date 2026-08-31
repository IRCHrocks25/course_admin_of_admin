from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.html import escape
from django.utils.text import slugify
from datetime import datetime
from io import BytesIO
from pathlib import Path
import importlib.util
import json
import logging
import re
import requests
import uuid
import os
import threading
import stripe
import time
from .models import (
    Course,
    CourseCategory,
    Lesson,
    LessonTranslation,
    Module,
    Tenant,
    TenantConfig,
    TenantMembership,
    UserProgress,
    CourseEnrollment,
    Event,
    EventRegistration,
    Exam,
    ExamAttempt,
    Certification,
    LessonQuiz,
    LessonQuizAttempt,
    CourseAccess,
    Bundle,
    BundlePurchase,
    Coupon,
    StripeEventLog,
    PricingTier,
    MembershipPlan,
    MembershipTier,
    StudentSubscription,
    PendingRegistration,
    TenantNotificationDelivery,
    category_accent_color,
    category_initial,
    sort_category_names,
)
from django.db.models import Avg, Q
from django.db import models
from django.db import transaction
from django.utils import timezone
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from .utils.transcription import transcribe_video
from .utils.access import has_course_access, has_event_access
from .utils.domains import ensure_temporary_domain, get_platform_base_domain, get_tenant_public_home_url
from .utils.branding import ensure_tenant_branding, get_tenant_branding, build_default_branding
from .utils.tenancy import get_default_tenant
from .utils.lesson_audio import generate_lesson_audio_async
from .utils.localization import (
    get_tenant_language_config,
    get_tenant_lesson_languages,
    get_request_language,
    resolve_lesson,
    resolve_lesson_display,
    resolve_quiz_display,
    resolve_quiz_question_display,
    build_lesson_title_map,
    show_language_switcher,
    get_translation_languages_for_tenant,
    get_language_label,
    SUPPORTED_LANGUAGES as LANGUAGE_LABELS,
    set_user_preferred_language,
    normalize_language_code,
)
# Reuse the LLM helpers from dashboard_views so the per-lesson Regenerate button
# uses the same prompts and OpenAI wiring as the course-creation pipeline.
from .dashboard_views import (
    OPENAI_AVAILABLE,
    generate_ai_lesson_metadata,
    generate_ai_lesson_content,
    generate_ai_lesson_image,
    upload_lesson_hero_image,
    delete_lesson_hero_image,
    create_editorjs_content,
    _blueprint_lesson_context_block,
    _parse_generation_settings,
    mark_lesson_chatbot_ready,
    lesson_chatbot_openai_reply,
    READING_LEVEL_CHOICES,
    LENGTH_CHOICES,
    DEPTH_CHOICES,
)
from .utils.prompts import LessonGenerationSettings

# Tenant/admin-protected views should route unauthenticated users to app login.
staff_member_required = user_passes_test(
    lambda u: u.is_authenticated and u.is_staff,
    login_url='login'
)


def course_queryset_for_slug(request, course_slug):
    """
    Courses are unique on (tenant, slug). Student/creator URLs must scope by the
    tenant resolved from the host (or ?tenant= on platform) so duplicate slugs
    across academies do not raise MultipleObjectsReturned.
    """
    qs = Course.objects.filter(slug=course_slug)
    tenant = getattr(request, 'tenant', None)
    if tenant is not None:
        return qs.filter(tenant=tenant)
    n = qs.count()
    if n == 0:
        return qs.none()
    if n == 1:
        return qs
    tenant_slug = (request.GET.get('tenant') or '').strip().lower()
    if tenant_slug:
        return qs.filter(tenant__slug=tenant_slug)
    return qs.none()


def _attach_orphan_lessons_to_first_module(course):
    """Ensure orphan lessons are attached to a real module when possible."""
    first_module = course.modules.order_by('order', 'id').first()
    if not first_module:
        return 0
    orphans = list(course.lessons.filter(module__isnull=True).order_by('order', 'id'))
    if not orphans:
        return 0

    max_order = Lesson.objects.filter(course=course, module=first_module).aggregate(models.Max('order'))['order__max'] or 0
    next_order = max_order + 1
    to_update = []
    for orphan in orphans:
        orphan.module = first_module
        if not orphan.order or orphan.order <= max_order:
            orphan.order = next_order
        next_order = max(next_order, int(orphan.order or 0) + 1)
        to_update.append(orphan)

    if to_update:
        Lesson.objects.bulk_update(to_update, ['module', 'order'])
    return len(to_update)


def _resolve_progress_tenant(request, lesson, course=None):
    """
    Resolve a tenant for lesson progress records.
    Falls back to the default tenant to avoid null tenant_id inserts.
    """
    resolved_course = course or getattr(lesson, 'course', None)
    return (
        getattr(lesson, 'tenant', None)
        or getattr(resolved_course, 'tenant', None)
        or getattr(request, 'tenant', None)
        or get_default_tenant()
    )

PLATFORM_PLANS = {
    'lean': {'name': 'Lean', 'amount_env': 'STRIPE_PLAN_AMOUNT_LEAN_USD', 'default_amount_cents': 2900},
    'baseline': {'name': 'Baseline', 'amount_env': 'STRIPE_PLAN_AMOUNT_BASELINE_USD', 'default_amount_cents': 7900},
    'growth': {'name': 'Growth', 'amount_env': 'STRIPE_PLAN_AMOUNT_GROWTH_USD', 'default_amount_cents': 14900},
}


def _stripe_client_configured():
    key = os.getenv('STRIPE_SECRET_KEY', '').strip()
    if not key:
        return False
    stripe.api_key = key
    return True


def _using_live_stripe_key():
    return os.getenv('STRIPE_SECRET_KEY', '').strip().startswith('sk_live_')


def _env_truthy(name):
    return os.getenv(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_plan_amount_cents(plan_def):
    raw = os.getenv(plan_def['amount_env'], '').strip()
    if raw:
        try:
            return max(50, int(raw))  # Stripe minimum and guardrail
        except ValueError:
            return None
    return int(plan_def.get('default_amount_cents', 0) or 0)


def _get_start_academy_checkout_mode():
    raw = (os.getenv('START_ACADEMY_CHECKOUT_MODE') or 'subscription').strip().lower()
    return 'payment' if raw == 'payment' else 'subscription'


def _start_academy_free_local_enabled():
    """
    Skip Stripe checkout and activate the academy immediately (local dev only).
    Gated by DEBUG, explicit opt-in, and non-live Stripe keys.
    """
    if not getattr(settings, 'DEBUG', False):
        return False
    if not _env_truthy('START_ACADEMY_FREE_LOCAL'):
        return False
    if _using_live_stripe_key():
        return False
    return True


def _activate_signup_free_local(tenant, admin_user):
    """Mirror checkout activation without Stripe (see _activate_signup_from_checkout_session)."""
    tenant.billing_status = 'active'
    tenant.is_active = True
    tenant.stripe_customer_id = ''
    tenant.stripe_subscription_id = ''
    tenant.save(update_fields=['billing_status', 'is_active', 'stripe_customer_id', 'stripe_subscription_id', 'updated_at'])
    ensure_tenant_branding(tenant)
    ensure_temporary_domain(tenant)
    if admin_user:
        admin_user.is_active = True
        admin_user.is_staff = True
        admin_user.save(update_fields=['is_active', 'is_staff'])
        TenantMembership.objects.update_or_create(
            tenant=tenant,
            user=admin_user,
            defaults={'role': 'tenant_admin', 'is_active': True},
        )
    return tenant


def _is_abandoned_signup_user(user):
    """
    Identify placeholder users created during signup before payment completion.
    These can be safely removed to let users retry checkout.
    """
    if not user:
        return False
    if user.is_active or user.is_staff or user.is_superuser:
        return False
    return not TenantMembership.objects.filter(user=user).exists()


def _normalize_referral_code(raw_code):
    return re.sub(r'[^A-Z0-9]', '', (raw_code or '').upper())


def _get_referrer_tenant(raw_code):
    normalized = _normalize_referral_code(raw_code)
    if not normalized:
        return None
    for candidate in Tenant.objects.exclude(referral_code='').only('id', 'referral_code', 'is_active'):
        if _normalize_referral_code(candidate.referral_code) == normalized:
            return candidate
    return None


def _get_tenant_custom_pages(tenant):
    if tenant is None:
        return {}
    try:
        tenant_config = tenant.config
    except TenantConfig.DoesNotExist:
        return {}
    if tenant_config and isinstance(tenant_config.features, dict):
        return tenant_config.features.get('custom_pages') or {}
    return {}


def _normalize_tenant_custom_html_document(custom_html):
    """
    Ensure tenant custom HTML is a full document so inline CSS/JS in <head> is applied.
    Body-only pastes were previously wrapped in a bare fragment with no styles.
    """
    html = (custom_html or '').strip()
    if not html:
        return ''
    lower = html.lower()
    if '<html' in lower:
        return html

    style_blocks = re.findall(r'<style[^>]*>[\s\S]*?</style>', html, flags=re.IGNORECASE)
    link_blocks = re.findall(
        r'<link[^>]*\brel=["\']stylesheet["\'][^>]*>',
        html,
        flags=re.IGNORECASE,
    )
    script_blocks = re.findall(r'<script[^>]*>[\s\S]*?</script>', html, flags=re.IGNORECASE)
    title_match = re.search(r'<title[^>]*>([\s\S]*?)</title>', html, flags=re.IGNORECASE)
    title_html = (
        f'<title>{title_match.group(1).strip()}</title>'
        if title_match
        else '<title>Custom Page</title>'
    )
    head_extras = ''.join(link_blocks + style_blocks)

    body_html = html
    for block in link_blocks + style_blocks + script_blocks:
        body_html = body_html.replace(block, '', 1)
    if title_match:
        body_html = re.sub(r'<title[^>]*>[\s\S]*?</title>', '', body_html, flags=re.IGNORECASE)
    body_html = re.sub(r'<!DOCTYPE[^>]*>', '', body_html, flags=re.IGNORECASE)
    body_html = re.sub(r'<head[^>]*>[\s\S]*?</head>', '', body_html, flags=re.IGNORECASE)

    if '<body' in lower:
        body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', body_html, flags=re.IGNORECASE)
        body_inner = body_match.group(1).strip() if body_match else body_html.strip()
    else:
        body_inner = body_html.strip()

    scripts_html = ''.join(script_blocks)
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        f'{title_html}{head_extras}'
        '</head><body>'
        f'{body_inner}'
        f'{scripts_html}'
        '</body></html>'
    )


def _render_tenant_custom_html(request, tenant, custom_html, *, inject_fallbacks=True):
    custom_html = _normalize_tenant_custom_html_document(custom_html)
    if not custom_html:
        return None
    # Ensure csrftoken cookie exists for custom HTML forms posted back to Django.
    get_token(request)
    branding = get_tenant_branding(tenant) if tenant else {}
    tenant_logo_url = (branding.get('logo_url') or '').strip()
    tenant_brand_name = (branding.get('brand_name') or getattr(tenant, 'name', '') or 'Your Brand').strip()
    if not tenant_logo_url:
        tenant_logo_url = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160' viewBox='0 0 160 160'%3E%3Crect width='160' height='160' rx='24' fill='%23ffffff'/%3E%3Crect x='18' y='18' width='124' height='124' rx='20' fill='%23eef3ff' stroke='%232563eb' stroke-opacity='0.35'/%3E%3Ctext x='80' y='92' text-anchor='middle' font-family='Arial,sans-serif' font-size='30' font-weight='700' fill='%232563eb'%3ELOGO%3C/text%3E%3C/svg%3E"
    custom_html = custom_html.replace('__TENANT_LOGO_URL__', tenant_logo_url)
    custom_html = custom_html.replace('__TENANT_BRAND_NAME__', tenant_brand_name)
    tenant_course_count = 0
    tenant_course_items_html = '<li><a href="/courses/">No active courses yet. Check back soon.</a></li>'
    if tenant is not None:
        active_courses = list(
            Course.objects.filter(tenant=tenant, status='active')
            .exclude(visibility='hidden')
            .only('name', 'slug')
            .order_by('name')[:24]
        )
        tenant_course_count = len(active_courses)
        if active_courses:
            tenant_course_items_html = ''.join(
                (
                    f'<li><a href="/courses/{escape(course.slug)}/">'
                    f'{escape((course.name or "").strip() or "Untitled Course")}</a></li>'
                )
                for course in active_courses
            )
    custom_html = custom_html.replace('__TENANT_COURSE_COUNT__', str(tenant_course_count))
    custom_html = custom_html.replace('__TENANT_COURSES_LIST__', tenant_course_items_html)

    def _normalize_img_src(match):
        src = (match.group(2) or '').strip()
        if '/_next/image?' not in src:
            return match.group(0)
        try:
            parsed = urlparse(src)
            query = parse_qs(parsed.query or '')
            raw_target = (query.get('url') or [''])[0]
            if not raw_target:
                return match.group(0)
            decoded_target = unquote(raw_target)
            if decoded_target.startswith('/'):
                normalized = f"{parsed.scheme}://{parsed.netloc}{decoded_target}"
            else:
                normalized = decoded_target
            return f"{match.group(1)}{normalized}{match.group(3)}"
        except Exception:
            return match.group(0)

    # Make pasted Next.js optimized image URLs portable across domains.
    custom_html = re.sub(r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', _normalize_img_src, custom_html, flags=re.IGNORECASE)
    logo_fallback_js = tenant_logo_url.replace('\\', '\\\\').replace("'", "\\'")

    fallback_style = (
        '<style id="tenant-custom-fallback">'
        '.reveal{opacity:1 !important;transform:none !important;}'
        '#cur,#cur-ring{display:none !important;}'
        'body{cursor:auto !important;}'
        '</style>'
    )
    fallback_script = (
        '<script>'
        "document.addEventListener('DOMContentLoaded',function(){"
        "document.querySelectorAll('.reveal').forEach(function(el){"
        "el.classList.add('in');el.classList.add('visible');"
        "});"
        "function getCookie(name){"
        "var v=document.cookie?document.cookie.split('; '):[];"
        "for(var i=0;i<v.length;i++){var p=v[i].split('=');if(p[0]===name){return decodeURIComponent(p.slice(1).join('='));}}"
        "return '';"
        "}"
        "function ensureCsrfField(form){"
        "var token=getCookie('csrftoken');"
        "if(!token){return;}"
        "var field=form.querySelector('input[name=\"csrfmiddlewaretoken\"]');"
        "if(!field){"
        "field=document.createElement('input');"
        "field.type='hidden';"
        "field.name='csrfmiddlewaretoken';"
        "form.appendChild(field);"
        "}"
        "field.value=token;"
        "}"
        "document.querySelectorAll('form').forEach(function(f){"
        "var m=(f.getAttribute('method')||'get').toLowerCase();"
        "if(m==='post'){"
        "ensureCsrfField(f);"
        "f.addEventListener('submit',function(){ensureCsrfField(f);});"
        "}"
        "if(!(f.getAttribute('action')||'').trim()){f.setAttribute('action',window.location.pathname);}"
        "});"
        f"var logoFallback='{logo_fallback_js}';"
        "document.querySelectorAll('img').forEach(function(img){"
        "img.addEventListener('error',function(){"
        "if(this.dataset.logoFallbackApplied==='1'){return;}"
        "this.dataset.logoFallbackApplied='1';"
        "if(logoFallback){this.src=logoFallback;}"
        "});"
        "});"
        "var routeMap={signup:'/register/',register:'/register/',login:'/login/',signin:'/login/',dashboard:'/courses/',courses:'/courses/'};"
        "function resolveTarget(el){"
        "var explicit=(el.getAttribute('data-link')||'').trim();"
        "if(explicit){return explicit;}"
        "var action=((el.getAttribute('data-action')||'').toLowerCase().replace(/\\s+/g,''));"
        "if(action&&routeMap[action]){return routeMap[action];}"
        "var txt=((el.textContent||'').toLowerCase());"
        "if(txt.includes('enroll')||txt.includes('join now')||txt.includes('create account')||txt.includes('sign up')){return '/register/';}"
        "if(txt.includes('login')||txt.includes('log in')||txt.includes('sign in')){return '/login/';}"
        "if(txt.includes('dashboard')||txt.includes('courses')||txt.includes('curriculum')){return '/courses/';}"
        "return '';"
        "}"
        "document.querySelectorAll('button,a').forEach(function(el){"
        "var tag=(el.tagName||'').toLowerCase();"
        "var btnType=((el.getAttribute('type')||'').toLowerCase());"
        "var inForm=!!(el.closest&&el.closest('form'));"
        "if(tag==='button'&&(inForm||btnType==='submit'||btnType==='reset')){return;}"
        "var href=(el.getAttribute('href')||'').trim();"
        "var isCta=(tag==='button')||(tag==='a'&&(href===''||href==='#'||href.toLowerCase().startsWith('javascript:')));"
        "if(!isCta){return;}"
        "var target=resolveTarget(el);"
        "if(!target){return;}"
        "el.addEventListener('click',function(ev){ev.preventDefault();window.location.href=target;});"
        "});"
        "});"
        '</script>'
    )

    # CMS-rendered pages are served verbatim (matching the editor preview);
    # the fallback style/script exists only for hand-pasted custom HTML.
    if inject_fallbacks:
        lower_html = custom_html.lower()
        if '</head>' in lower_html:
            idx = lower_html.rfind('</head>')
            custom_html = custom_html[:idx] + fallback_style + custom_html[idx:]
        else:
            custom_html = fallback_style + custom_html

        lower_html = custom_html.lower()
        if '</body>' in lower_html:
            idx = lower_html.rfind('</body>')
            custom_html = custom_html[:idx] + fallback_script + custom_html[idx:]
        else:
            custom_html = custom_html + fallback_script

    if '<html' in custom_html.lower():
        return HttpResponse(custom_html)
    return render(request, 'tenant/custom_landing_fragment.html', {
        'tenant': tenant,
        'custom_landing_html': custom_html,
    })


def _render_tenant_cms_landing(request, tenant, custom_pages):
    """Render annotation-based CMS landing page for a tenant."""
    from myApp.cms.parser import build_schema
    from myApp.cms.renderer import merge_with_defaults, render_site
    from myApp.cms.storage import get_landing_cms_content, get_landing_cms_template_html

    try:
        config = tenant.config
    except TenantConfig.DoesNotExist:
        return None

    template_html = get_landing_cms_template_html(config, tenant.id)
    if not template_html:
        from myApp.cms.templates import get_default_landing_cms_template
        from myApp.cms.storage import save_landing_cms_template_html
        template_html = get_default_landing_cms_template(tenant)
        save_landing_cms_template_html(config, tenant.id, template_html)
        config.save(update_fields=['features', 'updated_at'])

    schema = build_schema(template_html)
    merged = merge_with_defaults(get_landing_cms_content(config), schema.get('defaults'))
    branding = get_tenant_branding(tenant)
    html = render_site(
        template_html,
        merged,
        preview=False,
        site_settings={'title': branding.get('brand_name', getattr(tenant, 'name', ''))},
    )
    return _render_tenant_custom_html(request, tenant, html, inject_fallbacks=False)


_CERTIFICATE_GENERATOR_FN = None
_CERTIFICATE_GENERATOR_LOADED = False


def _load_certificate_generator_fn():
    """Load generate_certificate() from myApp/utils.py/certificate_generator.py."""
    global _CERTIFICATE_GENERATOR_FN, _CERTIFICATE_GENERATOR_LOADED
    if _CERTIFICATE_GENERATOR_LOADED:
        return _CERTIFICATE_GENERATOR_FN

    _CERTIFICATE_GENERATOR_LOADED = True
    generator_path = Path(__file__).resolve().parent / 'utils.py' / 'certificate_generator.py'
    if not generator_path.exists():
        return None

    try:
        spec = importlib.util.spec_from_file_location('myapp_certificate_generator', str(generator_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        generator_fn = getattr(module, 'generate_certificate', None)
        if callable(generator_fn):
            _CERTIFICATE_GENERATOR_FN = generator_fn
    except Exception:
        _CERTIFICATE_GENERATOR_FN = None

    return _CERTIFICATE_GENERATOR_FN


def _course_certificate_ready(user, course):
    """True when the learner has finished every lesson and required quiz gates."""
    total_lessons = course.lessons.count()
    if total_lessons <= 0:
        return False
    completed_lessons = UserProgress.objects.filter(
        user=user,
        lesson__course=course,
        completed=True,
    ).count()
    if completed_lessons < total_lessons:
        return False

    required_quiz_ids = list(
        LessonQuiz.objects.filter(
            lesson__course=course,
            is_required=True,
        ).values_list('id', flat=True)
    )
    if required_quiz_ids:
        passed_required = (
            LessonQuizAttempt.objects.filter(
                user=user,
                quiz_id__in=required_quiz_ids,
                passed=True,
            )
            .values('quiz_id')
            .distinct()
            .count()
        )
        if passed_required < len(required_quiz_ids):
            return False

    # A leftover/auto-generated final exam must not block the certificate.
    # Required lesson quizzes are the only extra gate; optional quizzes are ignored.
    return True


def _issue_certificate_if_earned(user, course, request=None):
    """Create/store the course PDF when requirements are met. No-op otherwise."""
    if not _course_certificate_ready(user, course):
        return None
    cert = Certification.objects.filter(user=user, course=course).first()
    return _auto_issue_course_certificate(user=user, course=course, certification=cert, request=request)


def _auto_issue_course_certificate(user, course, certification=None, request=None):
    """
    Generate and persist certificate URL/ID when learner completed requirements.
    """
    generator_fn = _load_certificate_generator_fn()
    if not generator_fn:
        return certification

    cert = certification
    if cert and cert.accredible_certificate_url and cert.accredible_certificate_id:
        return cert

    def _store_pdf_buffer_on_iceberg(pdf_buffer, cert_id):
        if not pdf_buffer:
            return ''
        try:
            from myApp.utils import iceberg
            pdf_buffer.seek(0)
            key = (
                f"certificates/generated/{course.slug}/"
                f"{cert_id}_{uuid.uuid4().hex[:8]}.pdf"
            )
            if not iceberg.is_configured():
                logging.getLogger(__name__).warning(
                    'Certificate PDF not stored: Iceberg is not configured.'
                )
                return ''
            url = iceberg.upload_bytes(pdf_buffer.read(), key, 'application/pdf')
            if not url:
                logging.getLogger(__name__).warning(
                    'Certificate PDF Iceberg upload failed for key %s.', key
                )
            return url or ''
        except Exception:
            logging.getLogger(__name__).exception(
                'Certificate PDF Iceberg store failed for course %s.', getattr(course, 'slug', '')
            )
            return ''

    try:
        result = generator_fn(
            user=user,
            course=course,
            issued_date=timezone.now(),
            upload_to_cloudinary=True,
            request=request,
        )
    except Exception:
        return cert

    # Fallback: generate the PDF buffer and upload it to Iceberg directly.
    # Do not write certificates to local disk — MEDIA_ROOT is ephemeral.
    if not result:
        try:
            local_result = generator_fn(
                user=user,
                course=course,
                issued_date=timezone.now(),
                upload_to_cloudinary=False,
                request=request,
            )
        except Exception:
            local_result = None

        if local_result and local_result.get('pdf_buffer'):
            cert_id = local_result.get('certificate_id') or f"CERT-{course.slug.upper()}-{user.id}"
            iceberg_url = _store_pdf_buffer_on_iceberg(local_result.get('pdf_buffer'), cert_id)
            if iceberg_url:
                result = {
                    'certificate_id': cert_id,
                    'certificate_url': iceberg_url,
                }

    if not result:
        return cert

    if cert is None:
        cert = Certification.objects.filter(
            tenant=course.tenant,
            user=user,
            course=course,
        ).first()
    if cert is None:
        cert = Certification(
            tenant=course.tenant,
            user=user,
            course=course,
        )

    cert.status = 'passed'
    cert.issued_at = cert.issued_at or timezone.now()
    cert.accredible_certificate_id = result.get('certificate_id') or cert.accredible_certificate_id
    cert.accredible_certificate_url = result.get('certificate_url') or cert.accredible_certificate_url
    cert.save()
    return cert


def home(request):
    """
    Platform host shows creator-acquisition landing.
    Tenant hosts show tenant-branded landing.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return render(request, 'platform/home.html', {
            'tenant_count': Tenant.objects.filter(is_active=True).count(),
            'course_count': Course.objects.count(),
            'platform_base_domain': get_platform_base_domain(),
        })

    custom_pages = _get_tenant_custom_pages(tenant)
    if custom_pages.get('landing_mode') == 'cms':
        published = bool(custom_pages.get('landing_cms_published'))
        can_preview = request.user.is_authenticated and getattr(request.user, 'is_staff', False)
        if published or can_preview:
            rendered = _render_tenant_cms_landing(request, tenant, custom_pages)
            if rendered is not None:
                return rendered
    if custom_pages.get('landing_mode') == 'custom' and custom_pages.get('landing_html'):
        rendered = _render_tenant_custom_html(request, tenant, custom_pages.get('landing_html'))
        if rendered is not None:
            return rendered

    return render(request, 'landing.html', {
        'tenant': tenant,
        'course_count': Course.objects.filter(tenant=tenant, status='active').count(),
    })


def railway_cost_calculator_light(request):
    """Render the lightweight Railway/CourseForge cost calculator."""
    return render(request, 'calculator/railway_courseforge_cost_calculator_light.html')


def verify_certificate(request, certificate_id):
    """
    Public certificate verification page for QR scans.
    """
    cert = (
        Certification.objects
        .select_related('user', 'course', 'tenant')
        .filter(
            accredible_certificate_id=certificate_id,
            status='passed',
        )
        .first()
    )

    return render(request, 'verify_certificate.html', {
        'certificate_id': certificate_id,
        'certificate': cert,
        'is_valid': bool(cert),
    })


def _pdf_bytes_from_url(url):
    if not url:
        return b''
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 200 and response.content[:4] == b'%PDF':
            return response.content
    except Exception:
        logging.getLogger(__name__).exception('Could not fetch certificate PDF from storage.')
    return b''


@login_required
def download_course_certificate(request, course_slug):
    """Stream a real PDF download with a .pdf filename (avoids broken CDN saves)."""
    course = get_object_or_404(course_queryset_for_slug(request, course_slug))
    if not _course_certificate_ready(request.user, course):
        messages.info(request, 'Finish the course to download your certificate.')
        return redirect('student_dashboard')

    cert = _issue_certificate_if_earned(request.user, course, request=request)
    pdf_bytes = b''
    generator_fn = _load_certificate_generator_fn()
    if generator_fn:
        try:
            result = generator_fn(
                user=request.user,
                course=course,
                issued_date=timezone.now(),
                upload_to_cloudinary=False,
                request=request,
            )
        except Exception:
            logging.getLogger(__name__).exception('Fresh certificate PDF generation failed.')
            result = None
        if result and result.get('pdf_buffer'):
            buf = result['pdf_buffer']
            try:
                buf.seek(0)
            except Exception:
                pass
            pdf_bytes = buf.read()

    if not pdf_bytes or pdf_bytes[:4] != b'%PDF':
        pdf_bytes = _pdf_bytes_from_url((cert.accredible_certificate_url if cert else '') or '')

    if not pdf_bytes or pdf_bytes[:4] != b'%PDF':
        messages.error(request, 'The certificate PDF could not be generated. Please try again.')
        return redirect('student_course_progress', course_slug=course.slug)

    buffer = BytesIO(pdf_bytes)
    response = FileResponse(
        buffer,
        as_attachment=True,
        filename='certificate.pdf',
        content_type='application/pdf',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@never_cache
def start_academy(request):
    """
    SaaS onboarding entrypoint:
    Creates tenant + tenant admin account.
    """
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dashboard_home')
        return redirect('courses')

    if getattr(request, 'tenant', None) is not None:
        messages.info(request, 'You are already on a tenant portal. Please sign in or register here.')
        return redirect('login')

    preset_referral_code = (request.GET.get('ref') or request.GET.get('code') or '').strip()

    if request.method == 'POST':
        academy_name = (request.POST.get('academy_name') or '').strip()
        admin_username = (request.POST.get('admin_username') or '').strip()
        admin_email = (request.POST.get('admin_email') or '').strip().lower()
        teach_topic = (request.POST.get('teach_topic') or '').strip()
        target_audience = (request.POST.get('target_audience') or '').strip()
        outcome_promise = (request.POST.get('outcome_promise') or '').strip()
        selected_plan = (request.POST.get('selected_plan') or 'baseline').strip().lower()
        referral_code = (request.POST.get('referral_code') or '').strip()
        password = request.POST.get('password') or ''
        confirm_password = request.POST.get('confirm_password') or ''
        # Always generate server-side idempotency for each POST attempt.
        # Client-provided keys can be stale when pages are restored from cache.
        idempotency_key = f"start-academy:{uuid.uuid4()}"
        free_local = _start_academy_free_local_enabled()
        template_ctx = {
            'platform_base_domain': get_platform_base_domain(),
            'selected_plan': selected_plan,
            'idempotency_key': str(uuid.uuid4()),
            'start_academy_free_local': free_local,
            'referral_code': referral_code,
        }

        referred_by_tenant = None
        if referral_code:
            referred_by_tenant = _get_referrer_tenant(referral_code)
            if referred_by_tenant is None:
                messages.error(request, 'Referral code not found. Please check the code and try again.')
                return render(request, 'platform/start_academy.html', template_ctx)
            if not referred_by_tenant.is_active:
                messages.error(request, 'That referral code belongs to an inactive academy and cannot be used.')
                return render(request, 'platform/start_academy.html', template_ctx)

        if not academy_name or not admin_username or not password:
            messages.error(request, 'Academy name, admin username, and password are required.')
            return render(request, 'platform/start_academy.html', template_ctx)
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'platform/start_academy.html', template_ctx)
        if selected_plan not in PLATFORM_PLANS:
            messages.error(request, 'Please choose a valid plan.')
            return render(request, 'platform/start_academy.html', template_ctx)
        if not free_local and not _stripe_client_configured():
            messages.error(request, 'Payments are not configured yet. Please contact support.')
            return render(request, 'platform/start_academy.html', template_ctx)

        # Slug is intentionally auto-generated for simpler onboarding UX.
        base_slug = slugify(academy_name)
        if not base_slug:
            messages.error(request, 'Please provide a valid academy name/slug.')
            return render(request, 'platform/start_academy.html', template_ctx)

        tenant_slug = base_slug
        counter = 1
        while Tenant.objects.filter(slug=tenant_slug).exists():
            tenant_slug = f"{base_slug}-{counter}"
            counter += 1

        existing_username_user = User.objects.filter(username=admin_username).first()
        existing_email_user = User.objects.filter(email=admin_email).first() if admin_email else None

        # Retry-safe behavior: remove abandoned placeholder users from unpaid attempts.
        users_to_cleanup = []
        for candidate in [existing_username_user, existing_email_user]:
            if candidate and candidate not in users_to_cleanup and _is_abandoned_signup_user(candidate):
                users_to_cleanup.append(candidate)
        for stale_user in users_to_cleanup:
            stale_user.delete()

        if User.objects.filter(username=admin_username).exists():
            messages.error(request, 'That admin username already exists.')
            return render(request, 'platform/start_academy.html', template_ctx)
        if admin_email and User.objects.filter(email=admin_email).exists():
            messages.error(request, 'That admin email is already in use.')
            return render(request, 'platform/start_academy.html', template_ctx)

        plan_def = PLATFORM_PLANS[selected_plan]
        plan_amount_cents = _get_plan_amount_cents(plan_def)
        if not free_local:
            if not plan_amount_cents:
                messages.error(request, f'{plan_def["name"]} amount is not configured correctly.')
                return render(request, 'platform/start_academy.html', template_ctx)
            if _using_live_stripe_key() and plan_amount_cents <= 50 and not _env_truthy('ALLOW_LIVE_TEST_PRICING'):
                messages.error(
                    request,
                    f'{plan_def["name"]} is set to a test-level amount in live mode. '
                    'Please update STRIPE_PLAN_AMOUNT_* values before checkout, '
                    'or set ALLOW_LIVE_TEST_PRICING=true temporarily.'
                )
                return render(request, 'platform/start_academy.html', template_ctx)

        tenant = Tenant.objects.create(
            name=academy_name,
            slug=tenant_slug,
            is_active=False,
            plan_code=selected_plan,
            billing_status='pending',
            referred_by=referred_by_tenant,
            referral_recorded_at=timezone.now() if referred_by_tenant else None,
        )
        config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
        features = config.features or {}
        profile = {
            'teach_topic': teach_topic,
            'target_audience': target_audience,
            'outcome_promise': outcome_promise,
        }
        features['brand_profile'] = profile
        features['branding'] = build_default_branding(tenant, profile=profile)
        config.features = features
        config.save(update_fields=['features', 'updated_at'])

        admin_user = User.objects.create_user(
            username=admin_username,
            email=admin_email,
            password=password
        )
        admin_user.is_active = False
        admin_user.save(update_fields=['is_active'])

        if free_local:
            _activate_signup_free_local(tenant, admin_user)
            admin_user.refresh_from_db()
            login(request, admin_user)
            return _render_academy_created_from_tenant(request, tenant)

        success_url = f"{request.scheme}://{request.get_host()}/start-academy/checkout-success/?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{request.scheme}://{request.get_host()}/start-academy/"
        checkout_mode = _get_start_academy_checkout_mode()
        price_data = {
            'currency': 'usd',
            'unit_amount': plan_amount_cents,
            'product_data': {'name': f'CourseForge {plan_def["name"]} Plan'},
        }
        if checkout_mode == 'subscription':
            price_data['recurring'] = {'interval': 'month'}
        try:
            session = stripe.checkout.Session.create(
                mode=checkout_mode,
                idempotency_key=idempotency_key,
                payment_method_types=['card'],
                # Keep the checkout session valid long enough for real users
                # to complete payment without hitting premature expiry.
                expires_at=int(time.time()) + (23 * 60 * 60),
                line_items=[{
                    'price_data': price_data,
                    'quantity': 1,
                }],
                success_url=success_url,
                cancel_url=cancel_url,
                after_expiration={
                    'recovery': {
                        'enabled': True,
                    }
                },
                customer_email=admin_email or None,
                metadata={
                    'tenant_id': str(tenant.id),
                    'admin_user_id': str(admin_user.id),
                    'plan_code': selected_plan,
                    'signup_checkout_mode': checkout_mode,
                    'referral_code': referred_by_tenant.referral_code if referred_by_tenant else '',
                    'referred_by_tenant_id': str(referred_by_tenant.id) if referred_by_tenant else '',
                }
            )
            response = redirect(session.url, permanent=False)
            # Prevent browser/proxy from caching the redirect to a specific Checkout Session URL.
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            return response
        except Exception as exc:
            tenant.delete()
            admin_user.delete()
            messages.error(request, f'Unable to create checkout session: {str(exc)}')
            return render(request, 'platform/start_academy.html', template_ctx)

    return render(request, 'platform/start_academy.html', {
        'platform_base_domain': get_platform_base_domain(),
        'selected_plan': 'baseline',
        'idempotency_key': str(uuid.uuid4()),
        'start_academy_free_local': _start_academy_free_local_enabled(),
        'referral_code': preset_referral_code,
    })


def _render_academy_created_from_tenant(request, tenant):
    temp_domain = ensure_temporary_domain(tenant)
    tenant_host = temp_domain.domain if temp_domain else ''
    using_fallback_urls = not bool(tenant_host)
    tenant_base_url = (get_tenant_public_home_url(request, tenant) or '').rstrip('/')
    if tenant_base_url and '?' not in tenant_base_url:
        tenant_register_url = f"{tenant_base_url}/register/"
        tenant_login_url = f"{tenant_base_url}/login/"
        tenant_courses_url = f"{tenant_base_url}/courses/"
        tenant_dashboard_url = f"{tenant_base_url}/dashboard/"
        tenant_domain_settings_url = f"{tenant_base_url}/dashboard/domains/"
    else:
        base = f"{request.scheme}://{request.get_host()}"
        tenant_qs = urlencode({'tenant': tenant.slug})
        tenant_base_url = f"{base}/?{tenant_qs}"
        tenant_register_url = f"{base}/register/?{tenant_qs}"
        tenant_login_url = f"{base}/login/?{tenant_qs}"
        tenant_courses_url = f"{base}/courses/?{tenant_qs}"
        tenant_dashboard_url = f"{base}/dashboard/?{tenant_qs}"
        tenant_domain_settings_url = f"{base}/dashboard/domains/?{tenant_qs}"

    request.session['highlight_course_creation_wizard'] = True
    request.session.modified = True
    first_course_create_url = f"{tenant_dashboard_url.rstrip('/')}/courses/add/?onboarding=1"
    referral_signup_url = f"{request.scheme}://{request.get_host()}/start-academy/?ref={tenant.referral_code}"

    return render(request, 'platform/academy_created.html', {
        'tenant': tenant,
        'tenant_host': tenant_host,
        'tenant_base_url': tenant_base_url,
        'tenant_register_url': tenant_register_url,
        'tenant_login_url': tenant_login_url,
        'tenant_courses_url': tenant_courses_url,
        'tenant_dashboard_url': tenant_dashboard_url,
        'tenant_domain_settings_url': tenant_domain_settings_url,
        'using_fallback_urls': using_fallback_urls,
        'platform_base_domain': get_platform_base_domain(),
        'first_course_create_url': first_course_create_url,
        'referral_signup_url': referral_signup_url,
    })


def _activate_signup_from_checkout_session(session):
    """
    Activate tenant + admin user for a successful start-academy checkout.
    Returns the activated tenant, or None when session is not eligible.
    """
    mode = session.get('mode')
    payment_status = session.get('payment_status')
    metadata = session.get('metadata') or {}
    if metadata.get('flow') == 'bundle_checkout':
        return None
    if mode not in ('subscription', 'payment'):
        return None
    if payment_status not in ('paid', 'no_payment_required'):
        return None

    tenant_id = metadata.get('tenant_id')
    tenant = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None
    if not tenant:
        return None

    admin_user = User.objects.filter(id=metadata.get('admin_user_id')).first()
    subscription_id = session.get('subscription') or ''
    customer_id = session.get('customer') or ''

    tenant.billing_status = 'active'
    tenant.is_active = True
    tenant.stripe_customer_id = customer_id
    tenant.stripe_subscription_id = subscription_id
    tenant.save(update_fields=['billing_status', 'is_active', 'stripe_customer_id', 'stripe_subscription_id', 'updated_at'])
    ensure_tenant_branding(tenant)
    ensure_temporary_domain(tenant)

    if admin_user:
        admin_user.is_active = True
        admin_user.is_staff = True
        admin_user.save(update_fields=['is_active', 'is_staff'])
        TenantMembership.objects.update_or_create(
            tenant=tenant,
            user=admin_user,
            defaults={'role': 'tenant_admin', 'is_active': True}
        )

    return tenant


@never_cache
def start_academy_checkout_success(request):
    if not _stripe_client_configured():
        messages.error(request, 'Stripe is not configured.')
        return redirect('start_academy')
    session_id = (request.GET.get('session_id') or '').strip()
    if not session_id:
        messages.error(request, 'Missing checkout session.')
        return redirect('start_academy')
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as exc:
        messages.error(request, f'Unable to verify checkout: {str(exc)}')
        return redirect('start_academy')

    tenant_id = (session.metadata or {}).get('tenant_id')
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant:
        messages.error(request, 'Unable to find your academy signup.')
        return redirect('start_academy')

    # Fallback activation for cases where webhook delivery is delayed.
    if not tenant.is_active and tenant.billing_status != 'active':
        activated_tenant = _activate_signup_from_checkout_session(session)
        if activated_tenant:
            tenant = activated_tenant

    if tenant.is_active and tenant.billing_status == 'active':
        admin_membership = TenantMembership.objects.filter(tenant=tenant, role='tenant_admin', is_active=True).select_related('user').first()
        if admin_membership and admin_membership.user.is_active:
            login(request, admin_membership.user)
        return _render_academy_created_from_tenant(request, tenant)

    messages.info(request, 'Payment received. We are finalizing your academy setup. Refresh in a few seconds.')
    return redirect('start_academy')


def _membership_activate_from_checkout(session):
    """
    Upsert a StudentSubscription from a completed membership checkout session.
    Idempotent: safe to call from both the success redirect and the webhook.
    Returns True when a membership was processed.
    """
    metadata = session.get('metadata') or {}
    if metadata.get('flow') != 'membership_checkout':
        return False

    tenant = Tenant.objects.filter(id=metadata.get('tenant_id')).first()
    user = User.objects.filter(id=metadata.get('user_id')).first()
    if not tenant or not user:
        return True  # our flow, but nothing to attach to

    interval = metadata.get('interval') or 'month'
    if interval not in ('month', 'year'):
        interval = 'month'

    subscription, _ = StudentSubscription.objects.get_or_create(
        tenant=tenant, user=user, defaults={'interval': interval},
    )
    subscription.interval = interval
    subscription.status = 'active'
    subscription.is_complimentary = False
    subscription.canceled_at = None

    # Tiered vs all-access, from the checkout metadata.
    tier_id = metadata.get('membership_tier_id')
    tier = MembershipTier.objects.filter(id=tier_id, tenant=tenant).first() if tier_id else None
    if tier is not None:
        subscription.access_mode = 'tiered'
        subscription.tier = tier
    else:
        subscription.access_mode = 'all_access'
        subscription.tier = None

    sub_id = session.get('subscription')
    if isinstance(sub_id, dict):
        sub_id = sub_id.get('id', '')
    if sub_id:
        subscription.stripe_subscription_id = str(sub_id)
    if session.get('customer'):
        subscription.stripe_customer_id = str(session.get('customer'))
    subscription.last_synced_at = timezone.now()
    subscription.save()
    return True


def _membership_handle_subscription_event(event_type, obj):
    """
    Handle student-membership lifecycle events (subscription + invoice).
    Returns True when the event matched a StudentSubscription and was handled,
    so the caller can skip platform-billing fallback logic.
    """
    from .utils.membership import sync_subscription_from_stripe

    subscription = None
    stripe_sub = None

    if event_type in ('customer.subscription.updated', 'customer.subscription.deleted'):
        stripe_sub = obj
        sub_id = obj.get('id')
        if sub_id:
            subscription = StudentSubscription.objects.filter(stripe_subscription_id=sub_id).first()
    elif event_type in ('invoice.paid', 'invoice.payment_failed'):
        sub_id = obj.get('subscription')
        customer_id = obj.get('customer')
        if sub_id:
            subscription = StudentSubscription.objects.filter(stripe_subscription_id=sub_id).first()
        if subscription is None and customer_id:
            subscription = StudentSubscription.objects.filter(stripe_customer_id=customer_id).first()

    if subscription is None:
        return False

    if event_type == 'customer.subscription.deleted':
        subscription.status = 'canceled'
        subscription.canceled_at = timezone.now()
        subscription.last_synced_at = timezone.now()
        subscription.save()
        return True

    if event_type == 'invoice.payment_failed':
        subscription.status = 'past_due'
        subscription.last_synced_at = timezone.now()
        subscription.save()
        return True

    if event_type == 'invoice.paid':
        subscription.status = 'active'
        # Extend period end from the invoice line period, if present.
        try:
            line = (obj.get('lines') or {}).get('data') or []
            period_end = line[0]['period']['end'] if line else None
        except (KeyError, IndexError, TypeError):
            period_end = None
        if period_end:
            import datetime
            subscription.current_period_end = datetime.datetime.fromtimestamp(
                period_end, tz=datetime.timezone.utc,
            )
        subscription.last_synced_at = timezone.now()
        subscription.save()
        return True

    # customer.subscription.updated
    sync_subscription_from_stripe(subscription, stripe_sub)
    # Repair tier if the customer switched price (e.g. via the billing portal).
    from .utils.membership_sync import reconcile_subscription_tier
    reconcile_subscription_tier(subscription, stripe_sub)
    subscription.save()
    return True


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    secret = os.getenv('STRIPE_WEBHOOK_SECRET', '').strip()
    if not _stripe_client_configured() or not secret:
        return HttpResponse(status=500)

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception:
        return HttpResponse(status=400)

    event_id = event.get('id')
    event_type = event.get('type', '')
    if not event_id:
        return HttpResponse(status=200)
    if StripeEventLog.objects.filter(event_id=event_id).exists():
        return HttpResponse(status=200)

    with transaction.atomic():
        StripeEventLog.objects.create(event_id=event_id, event_type=event_type)

        if event_type == 'checkout.session.completed':
            session = event['data']['object']
            mode = session.get('mode')
            metadata = session.get('metadata') or {}
            payment_flow = metadata.get('flow')
            tenant_id = metadata.get('tenant_id')
            tenant = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None

            if payment_flow == 'tier_upgrade' and tenant:
                _activate_tier_upgrade(session)

            elif payment_flow == 'setup_fee' and tenant:
                _activate_setup_fee_payment(session)

            elif payment_flow == 'membership_checkout':
                _membership_activate_from_checkout(session)

            elif payment_flow == 'membership_registration':
                _activate_membership_registration(session)

            elif mode in ('subscription', 'payment') and tenant and payment_flow != 'bundle_checkout':
                _activate_signup_from_checkout_session(session)

            if payment_flow == 'bundle_checkout':
                user = User.objects.filter(id=metadata.get('user_id')).first()
                bundle = Bundle.objects.filter(id=metadata.get('bundle_id')).first()
                if tenant and user and bundle:
                    purchase_id = session.get('payment_intent') or session.get('id')
                    if not BundlePurchase.objects.filter(tenant=tenant, bundle=bundle, user=user, purchase_id=purchase_id).exists():
                        bundle_purchase = BundlePurchase.objects.create(
                            tenant=tenant,
                            user=user,
                            bundle=bundle,
                            purchase_id=purchase_id,
                            notes='Auto-created from Stripe checkout',
                        )
                        from .utils.access import grant_bundle_access
                        grant_bundle_access(user, bundle_purchase)

        elif event_type == 'checkout.session.expired':
            session = event['data']['object']
            metadata = session.get('metadata') or {}
            payment_flow = metadata.get('flow')
            if payment_flow == 'membership_registration':
                pending_id = metadata.get('pending_registration_id')
                if pending_id:
                    PendingRegistration.objects.filter(
                        id=pending_id, consumed=False,
                    ).delete()
            elif payment_flow != 'bundle_checkout':
                tenant_id = metadata.get('tenant_id')
                admin_user_id = metadata.get('admin_user_id')
                tenant = Tenant.objects.filter(
                    id=tenant_id,
                    billing_status='pending',
                    is_active=False,
                ).first() if tenant_id else None
                admin_user = User.objects.filter(
                    id=admin_user_id,
                    is_active=False,
                    is_staff=False,
                ).first() if admin_user_id else None

                # Clean up abandoned pending signups so retries can reuse the same username/email.
                if tenant and not tenant.stripe_customer_id and not tenant.stripe_subscription_id:
                    tenant.delete()
                if admin_user and not TenantMembership.objects.filter(user=admin_user).exists():
                    admin_user.delete()

        elif event_type in (
            'customer.subscription.updated', 'customer.subscription.deleted',
            'invoice.paid', 'invoice.payment_failed',
        ):
            obj = event['data']['object']
            # Student memberships take precedence; only fall through to platform
            # (academy-owner) billing when no StudentSubscription matches.
            handled = _membership_handle_subscription_event(event_type, obj)
            if not handled and event_type in ('customer.subscription.deleted', 'invoice.payment_failed'):
                customer_id = obj.get('customer')
                if customer_id:
                    tenant = Tenant.objects.filter(stripe_customer_id=customer_id).first()
                    if tenant:
                        tenant.billing_status = 'canceled' if event_type == 'customer.subscription.deleted' else 'past_due'
                        if event_type == 'customer.subscription.deleted':
                            tenant.is_active = False
                            tenant.save(update_fields=['billing_status', 'is_active', 'updated_at'])
                        else:
                            tenant.save(update_fields=['billing_status', 'updated_at'])

    return HttpResponse(status=200)


@csrf_exempt
@require_http_methods(["POST"])
def stripe_tenant_webhook(request, tenant_slug):
    """
    Per-tenant Stripe webhook for tenants using own-keys mode.
    Tenants register: https://<platform>/webhooks/stripe/tenant/<slug>/
    in their own Stripe dashboard and paste the resulting whsec_ here.
    """
    from myApp.models import TenantConfig as TC, Tenant as TenantModel
    try:
        tenant = TenantModel.objects.get(slug=tenant_slug, is_active=True)
        config = TC.objects.get(tenant=tenant)
    except (TenantModel.DoesNotExist, TC.DoesNotExist):
        return HttpResponse(status=404)

    secret_key = config.stripe_own_secret_key.strip()
    webhook_secret = config.stripe_own_webhook_secret.strip()
    if not secret_key or not webhook_secret:
        return HttpResponse(status=500)

    stripe.api_key = secret_key
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        return HttpResponse(status=400)

    event_id = event.get('id')
    event_type = event.get('type', '')
    if not event_id:
        return HttpResponse(status=200)
    if StripeEventLog.objects.filter(event_id=event_id).exists():
        return HttpResponse(status=200)

    with transaction.atomic():
        StripeEventLog.objects.create(event_id=event_id, event_type=event_type)

        if event_type == 'checkout.session.completed':
            session = event['data']['object']
            metadata = session.get('metadata') or {}
            if metadata.get('flow') == 'membership_checkout':
                _membership_activate_from_checkout(session)
            elif metadata.get('flow') == 'membership_registration':
                _activate_membership_registration(session)
            elif metadata.get('flow') == 'bundle_checkout':
                bundle_id = metadata.get('bundle_id')
                user_id = metadata.get('user_id')
                if bundle_id and user_id:
                    try:
                        from myApp.models import Bundle, BundlePurchase, CourseAccess
                        bundle = Bundle.objects.get(id=bundle_id, tenant=tenant)
                        user = User.objects.get(id=user_id)
                        BundlePurchase.objects.get_or_create(
                            bundle=bundle, user=user,
                            defaults={'stripe_payment_intent': session.get('payment_intent', '')}
                        )
                        for course in bundle.courses.all():
                            CourseAccess.objects.get_or_create(user=user, course=course)
                    except Exception:
                        pass

        elif event_type in (
            'customer.subscription.updated', 'customer.subscription.deleted',
            'invoice.paid', 'invoice.payment_failed',
        ):
            _membership_handle_subscription_event(event_type, event['data']['object'])

    return HttpResponse(status=200)


def coupon_landing(request, code):
    """
    Public coupon link: validate code, stash it in session, redirect to destination.
    QR codes and shareable links point here.
    """
    from .utils.coupons import normalize_coupon_code

    tenant = getattr(request, 'tenant', None)
    normalized = normalize_coupon_code(code)
    if not normalized:
        messages.error(request, 'Invalid coupon link.')
        return redirect('home')

    qs = Coupon.objects.filter(code__iexact=normalized)
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    coupon = qs.first()

    if coupon is None:
        messages.error(request, 'This coupon was not found.')
        return redirect('home')

    if not coupon.is_currently_valid():
        messages.error(request, 'This coupon is no longer valid.')
        return redirect('home')

    request.session['active_coupon_id'] = coupon.id
    if coupon.is_tracking_only():
        messages.success(
            request,
            f'Coupon {coupon.code} saved. Create an account to record this invite on your student profile.',
        )
    else:
        messages.success(request, f'Coupon {coupon.code} applied!')

    if coupon.target_type == Coupon.TARGET_SIGNUP:
        return redirect('register')
    if coupon.target_type == Coupon.TARGET_COURSE and coupon.course_id:
        return redirect('course_detail', course_slug=coupon.course.slug)
    if coupon.target_type == Coupon.TARGET_BUNDLE and coupon.bundle_id:
        # Bundles don't have a public detail page; send users to courses catalog.
        return redirect('courses')
    if coupon.target_type == Coupon.TARGET_CUSTOM and coupon.custom_url:
        return redirect(coupon.custom_url)
    return redirect('register')


@login_required
@require_http_methods(["POST"])
def create_bundle_checkout_session(request, bundle_id):
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return JsonResponse({'success': False, 'error': 'Tenant context missing.'}, status=400)
    bundle = get_object_or_404(Bundle, id=bundle_id, tenant=tenant, is_active=True)
    if not bundle.price:
        return JsonResponse({'success': False, 'error': 'Bundle price is not configured.'}, status=400)
    config = getattr(tenant, 'config', None)

    # Determine which Stripe mode to use: own keys > Connect > error
    use_own_keys = bool(config and config.stripe_own_secret_key and config.stripe_own_publishable_key)
    use_connect = bool(config and config.stripe_connect_account_id and config.stripe_connect_charges_enabled)

    if not use_own_keys and not use_connect:
        return JsonResponse({'success': False, 'error': 'Tenant Stripe account is not configured for charges.'}, status=400)

    if use_own_keys:
        stripe.api_key = config.stripe_own_secret_key.strip()
    else:
        if not _stripe_client_configured():
            return JsonResponse({'success': False, 'error': 'Stripe is not configured.'}, status=500)

    try:
        from .utils.coupons import (
            get_session_coupon,
            coupon_applies_to_bundle,
            discounted_amount_cents,
        )
        coupon = get_session_coupon(request, tenant)
        if coupon and not coupon_applies_to_bundle(coupon, bundle):
            coupon = None
        amount_cents = discounted_amount_cents(bundle.price, coupon)
        if amount_cents <= 0:
            return JsonResponse({'success': False, 'error': 'Discounted price must be greater than zero.'}, status=400)

        first_course = bundle.courses.first()
        base = f"{request.scheme}://{request.get_host()}"
        # Include session ID so the success handler can verify payment without relying solely on webhooks.
        success_url = f"{base}/bundles/{bundle.id}/checkout-success/?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base}/courses/"

        product_description = bundle.description or 'Course bundle purchase'
        if coupon:
            product_description = f'{product_description} (coupon {coupon.code})'

        session_kwargs = dict(
            mode='payment',
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': bundle.name, 'description': product_description},
                    'unit_amount': amount_cents,
                },
                'quantity': 1,
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=f"tenant:{tenant.id}:bundle:{bundle.id}:user:{request.user.id}",
            metadata={
                'flow': 'bundle_checkout',
                'tenant_id': str(tenant.id),
                'bundle_id': str(bundle.id),
                'user_id': str(request.user.id),
                'coupon_id': str(coupon.id) if coupon else '',
                'coupon_code': coupon.code if coupon else '',
            },
        )
        if use_connect:
            session_kwargs['stripe_account'] = config.stripe_connect_account_id

        session = stripe.checkout.Session.create(**session_kwargs)
        return JsonResponse({'success': True, 'checkout_url': session.url})
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


@login_required
def bundle_checkout_success(request, bundle_id):
    """
    Verify a completed bundle purchase on redirect and grant access.
    Works for both Connect and own-keys tenants.
    Webhooks are still processed when available, but this ensures access
    is granted immediately even if the webhook hasn't fired yet.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'Unable to verify payment — no tenant context.')
        return redirect('courses')

    bundle = get_object_or_404(Bundle, id=bundle_id, tenant=tenant, is_active=True)
    session_id = (request.GET.get('session_id') or '').strip()
    if not session_id:
        messages.error(request, 'Missing payment session — contact support if you were charged.')
        return redirect('courses')

    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(config and config.stripe_connect_account_id)

    try:
        if use_own_keys:
            stripe.api_key = config.stripe_own_secret_key.strip()
            session = stripe.checkout.Session.retrieve(session_id)
        elif use_connect:
            _stripe_client_configured()
            session = stripe.checkout.Session.retrieve(
                session_id, stripe_account=config.stripe_connect_account_id
            )
        else:
            _stripe_client_configured()
            session = stripe.checkout.Session.retrieve(session_id)

        if session.get('payment_status') != 'paid':
            messages.warning(request, 'Payment is not confirmed yet. Access will be granted once payment clears.')
            return redirect('courses')

        purchase, created = BundlePurchase.objects.get_or_create(
            bundle=bundle,
            user=request.user,
            defaults={'stripe_payment_intent': session.get('payment_intent', '')}
        )
        for course in bundle.courses.all():
            CourseAccess.objects.get_or_create(user=request.user, course=course)

        coupon_id = (session.get('metadata') or {}).get('coupon_id') or ''
        if coupon_id and created:
            Coupon.objects.filter(id=coupon_id, tenant=tenant).update(uses_count=models.F('uses_count') + 1)
            request.session.pop('active_coupon_id', None)

        first_course = bundle.courses.first()
        if created:
            messages.success(request, f'Payment confirmed! You now have access to {bundle.name}.')
        else:
            messages.info(request, f'You already have access to {bundle.name}.')

        if first_course:
            return redirect('course_detail', course_slug=first_course.slug)
        return redirect('courses')

    except Exception as exc:
        messages.error(request, f'Could not verify payment: {exc}')
        return redirect('courses')


@login_required
@require_http_methods(["POST"])
def create_course_checkout_session(request, course_slug):
    """Stripe checkout for a single paid course (own-keys or Connect)."""
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return JsonResponse({'success': False, 'error': 'Tenant context missing.'}, status=400)

    course = get_object_or_404(Course, slug=course_slug, tenant=tenant, status='active')
    if not course.price:
        return JsonResponse({'success': False, 'error': 'This course is free — no payment needed.'}, status=400)

    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(config and config.stripe_connect_account_id and config.stripe_connect_charges_enabled)

    if not use_own_keys and not use_connect:
        return JsonResponse({'success': False, 'error': 'Payments are not configured for this academy.'}, status=400)

    if use_own_keys:
        stripe.api_key = config.stripe_own_secret_key.strip()
    else:
        if not _stripe_client_configured():
            return JsonResponse({'success': False, 'error': 'Stripe is not configured.'}, status=500)

    try:
        from .utils.coupons import (
            get_session_coupon,
            coupon_applies_to_course,
            discounted_amount_cents,
        )
        coupon = get_session_coupon(request, tenant)
        if coupon and not coupon_applies_to_course(coupon, course):
            coupon = None
        # Active members pay the member price when one is set; coupons stack on top.
        from .utils.membership import effective_course_price
        base_price = effective_course_price(request.user, course)
        is_member_price = base_price != course.price
        amount_cents = discounted_amount_cents(base_price, coupon)
        if amount_cents <= 0:
            return JsonResponse({'success': False, 'error': 'Discounted price must be greater than zero.'}, status=400)

        base = f"{request.scheme}://{request.get_host()}"
        success_url = f"{base}/courses/{course.slug}/checkout-success/?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base}/courses/{course.slug}/"

        product_description = course.short_description or 'Course access'
        if is_member_price:
            product_description = f'{product_description} (member price)'
        if coupon:
            product_description = f'{product_description} (coupon {coupon.code})'

        session_kwargs = dict(
            mode='payment',
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': course.name,
                        'description': product_description,
                    },
                    'unit_amount': amount_cents,
                },
                'quantity': 1,
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=f"tenant:{tenant.id}:course:{course.id}:user:{request.user.id}",
            metadata={
                'flow': 'course_checkout',
                'tenant_id': str(tenant.id),
                'course_id': str(course.id),
                'user_id': str(request.user.id),
                'coupon_id': str(coupon.id) if coupon else '',
                'coupon_code': coupon.code if coupon else '',
            },
        )
        if use_connect:
            session_kwargs['stripe_account'] = config.stripe_connect_account_id

        session = stripe.checkout.Session.create(**session_kwargs)
        return JsonResponse({'success': True, 'checkout_url': session.url})
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


@login_required
def course_checkout_success(request, course_slug):
    """Verify a completed course purchase on redirect and grant access."""
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'Unable to verify payment — no tenant context.')
        return redirect('courses')

    course = get_object_or_404(Course, slug=course_slug, tenant=tenant)
    session_id = (request.GET.get('session_id') or '').strip()
    if not session_id:
        messages.error(request, 'Missing payment session — contact support if you were charged.')
        return redirect('course_detail', course_slug=course_slug)

    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(config and config.stripe_connect_account_id)

    try:
        if use_own_keys:
            stripe.api_key = config.stripe_own_secret_key.strip()
            session = stripe.checkout.Session.retrieve(session_id)
        elif use_connect:
            _stripe_client_configured()
            session = stripe.checkout.Session.retrieve(
                session_id, stripe_account=config.stripe_connect_account_id
            )
        else:
            _stripe_client_configured()
            session = stripe.checkout.Session.retrieve(session_id)

        if session.get('payment_status') != 'paid':
            messages.warning(request, 'Payment is not confirmed yet. Access will be granted once payment clears.')
            return redirect('course_detail', course_slug=course_slug)

        from .utils.access import grant_course_access
        grant_course_access(
            user=request.user,
            course=course,
            access_type='purchase',
            notes=f'Purchased via Stripe session {session_id}',
        )
        _enrollment, enrollment_created = CourseEnrollment.objects.get_or_create(
            user=request.user,
            course=course,
            defaults={'tenant': course.tenant}
        )
        coupon_id = (session.get('metadata') or {}).get('coupon_id') or ''
        if coupon_id and enrollment_created:
            Coupon.objects.filter(id=coupon_id, tenant=tenant).update(uses_count=models.F('uses_count') + 1)
            request.session.pop('active_coupon_id', None)

        # Programme purchases can include complimentary membership.
        membership_note = ''
        if course.grants_membership_months:
            from .utils.membership import grant_complimentary_membership
            granted = grant_complimentary_membership(
                request.user, course.tenant, course.grants_membership_months,
            )
            if granted:
                membership_note = f' Includes {course.grants_membership_months} months of complimentary membership.'
        messages.success(request, f'Payment confirmed! You now have access to {course.name}.{membership_note}')
        return redirect('course_detail', course_slug=course_slug)

    except Exception as exc:
        messages.error(request, f'Could not verify payment: {exc}')
        return redirect('course_detail', course_slug=course_slug)


def _resolve_tenant_stripe_mode(tenant):
    """
    Return (config, use_own_keys, use_connect, error_message).
    Mirrors the own-keys > Connect precedence used by course/bundle checkout.
    """
    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(
        config and config.stripe_connect_account_id and config.stripe_connect_charges_enabled
    )
    # Own-keys takes precedence: a tenant charging on their own Stripe account
    # must NOT also send a Connect `stripe_account` (a stale connect_account_id
    # would otherwise trigger "Only Stripe Connect platforms can work with other
    # accounts"). The two modes are mutually exclusive.
    if use_own_keys:
        use_connect = False
    if not use_own_keys and not use_connect:
        return config, False, False, 'Payments are not configured for this academy.'
    return config, use_own_keys, use_connect, ''


@login_required
@require_http_methods(["POST"])
def create_membership_checkout_session(request, interval, tier_code=None):
    """
    Stripe subscription checkout for a tenant membership.

    ``tier_code`` set  → tiered checkout for that MembershipTier (uses the tier's
                          stored Stripe price when available).
    ``tier_code`` None → legacy all-access checkout via MembershipPlan.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return JsonResponse({'success': False, 'error': 'Tenant context missing.'}, status=400)

    if interval not in ('month', 'year'):
        return JsonResponse({'success': False, 'error': 'Invalid billing interval.'}, status=400)

    # Resolve the offer: a specific tier, or the legacy all-access plan.
    tier = None
    if tier_code:
        tier = MembershipTier.objects.filter(tenant=tenant, code=tier_code).first()
        if not tier or not tier.is_available():
            return JsonResponse({'success': False, 'error': 'That membership tier is not available.'}, status=400)
        price = tier.price_for(interval)
        offer_name = tier.name
        offer_desc = tier.description or f'{tier.name} membership'
    else:
        plan = MembershipPlan.objects.filter(tenant=tenant).first()
        if not plan or not plan.is_purchasable():
            return JsonResponse({'success': False, 'error': 'Membership is not available for this academy.'}, status=400)
        price = plan.monthly_price if interval == 'month' else plan.yearly_price
        offer_name = plan.name
        offer_desc = plan.description or 'All-access membership'

    if not price:
        return JsonResponse({'success': False, 'error': f'No {interval}ly price is configured.'}, status=400)

    # Block duplicate active memberships.
    from .utils.membership import get_active_subscription
    if get_active_subscription(request.user, tenant) is not None:
        return JsonResponse({'success': False, 'error': 'You already have an active membership.'}, status=400)

    config, use_own_keys, use_connect, err = _resolve_tenant_stripe_mode(tenant)
    if err:
        return JsonResponse({'success': False, 'error': err}, status=400)

    if use_own_keys:
        stripe.api_key = config.stripe_own_secret_key.strip()
    else:
        if not _stripe_client_configured():
            return JsonResponse({'success': False, 'error': 'Stripe is not configured.'}, status=500)

    try:
        from decimal import Decimal

        # Prefer the tier's persistent Stripe Price; sync on demand, else fall
        # back to inline price_data so checkout still works pre-sync.
        stripe_price_id = ''
        if tier is not None:
            stripe_price_id = tier.stripe_price_id_for(interval)
            if not stripe_price_id:
                from .utils.membership_sync import sync_tier_prices
                ok, _price_err = sync_tier_prices(tier)
                if ok:
                    tier.refresh_from_db()
                    stripe_price_id = tier.stripe_price_id_for(interval)

        if stripe_price_id:
            line_item = {'price': stripe_price_id, 'quantity': 1}
        else:
            amount_cents = int((Decimal(str(price)) * 100).quantize(Decimal('1')))
            if amount_cents <= 0:
                return JsonResponse({'success': False, 'error': 'Membership price must be greater than zero.'}, status=400)
            line_item = {
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': offer_name, 'description': offer_desc},
                    'unit_amount': amount_cents,
                    'recurring': {'interval': interval},
                },
                'quantity': 1,
            }

        base = f"{request.scheme}://{request.get_host()}"
        success_url = f"{base}/membership/checkout-success/?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base}/courses/"

        metadata = {
            'flow': 'membership_checkout',
            'tenant_id': str(tenant.id),
            'user_id': str(request.user.id),
            'interval': interval,
        }
        if tier is not None:
            metadata['membership_tier_id'] = str(tier.id)
            metadata['membership_tier_code'] = tier.code

        session_kwargs = dict(
            mode='subscription',
            line_items=[line_item],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=f"tenant:{tenant.id}:membership:user:{request.user.id}",
            metadata=metadata,
            # Stamp the subscription itself so it's self-describing for repair.
            subscription_data={'metadata': dict(metadata)},
        )
        if request.user.email:
            session_kwargs['customer_email'] = request.user.email
        if use_connect:
            session_kwargs['stripe_account'] = config.stripe_connect_account_id

        session = stripe.checkout.Session.create(**session_kwargs)
        return JsonResponse({'success': True, 'checkout_url': session.url})
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


@login_required
def membership_checkout_success(request):
    """Verify a completed membership subscription on redirect and activate it."""
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'Unable to verify payment — no tenant context.')
        return redirect('courses')

    session_id = (request.GET.get('session_id') or '').strip()
    if not session_id:
        messages.error(request, 'Missing payment session — contact support if you were charged.')
        return redirect('courses')

    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(config and config.stripe_connect_account_id)

    try:
        retrieve_kwargs = {'expand': ['subscription']}
        if use_own_keys:
            stripe.api_key = config.stripe_own_secret_key.strip()
        elif use_connect:
            _stripe_client_configured()
            retrieve_kwargs['stripe_account'] = config.stripe_connect_account_id
        else:
            _stripe_client_configured()

        session = stripe.checkout.Session.retrieve(session_id, **retrieve_kwargs)

        metadata = session.get('metadata') or {}
        if metadata.get('flow') != 'membership_checkout' or metadata.get('tenant_id') != str(tenant.id):
            messages.error(request, 'This payment session does not match this academy.')
            return redirect('courses')

        # Subscription may be an expanded object or an id.
        stripe_sub = session.get('subscription')
        sub_id, stripe_sub_obj = '', None
        if isinstance(stripe_sub, dict):
            stripe_sub_obj = stripe_sub
            sub_id = stripe_sub.get('id', '')
        elif stripe_sub:
            sub_id = str(stripe_sub)

        paid = session.get('payment_status') == 'paid' or (
            stripe_sub_obj and stripe_sub_obj.get('status') in ('active', 'trialing')
        )
        if not paid:
            messages.warning(request, 'Payment is not confirmed yet. Your membership will activate once payment clears.')
            return redirect('courses')

        interval = metadata.get('interval') or 'month'
        subscription, _ = StudentSubscription.objects.get_or_create(
            tenant=tenant, user=request.user,
            defaults={'interval': interval},
        )
        subscription.interval = interval if interval in ('month', 'year') else subscription.interval
        subscription.status = 'active'
        subscription.stripe_subscription_id = sub_id or subscription.stripe_subscription_id
        subscription.stripe_customer_id = session.get('customer') or subscription.stripe_customer_id
        subscription.is_complimentary = False
        subscription.canceled_at = None

        tier_id = metadata.get('membership_tier_id')
        tier = MembershipTier.objects.filter(id=tier_id, tenant=tenant).first() if tier_id else None
        if tier is not None:
            subscription.access_mode = 'tiered'
            subscription.tier = tier
        else:
            subscription.access_mode = 'all_access'
            subscription.tier = None

        if stripe_sub_obj:
            from .utils.membership import sync_subscription_from_stripe
            sync_subscription_from_stripe(subscription, stripe_sub_obj)
            subscription.status = 'active'
        subscription.save()

        messages.success(request, f'Welcome aboard! Your {tenant.name} membership is now active.')
        return redirect('courses')

    except Exception as exc:
        messages.error(request, f'Could not verify payment: {exc}')
        return redirect('courses')


@login_required
def membership_billing_portal(request):
    """Open a Stripe Customer Portal so a member can manage/cancel their membership."""
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'No tenant context.')
        return redirect('courses')

    subscription = StudentSubscription.objects.filter(tenant=tenant, user=request.user).first()
    if not subscription or not subscription.stripe_customer_id:
        messages.info(request, 'No billing account found for your membership.')
        return redirect('courses')

    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(config and config.stripe_connect_account_id)

    try:
        base = f"{request.scheme}://{request.get_host()}"
        portal_kwargs = dict(
            customer=subscription.stripe_customer_id,
            return_url=f"{base}/membership/billing-return/",
        )
        if use_own_keys:
            stripe.api_key = config.stripe_own_secret_key.strip()
        elif use_connect:
            _stripe_client_configured()
            portal_kwargs['stripe_account'] = config.stripe_connect_account_id
        else:
            _stripe_client_configured()

        portal = stripe.billing_portal.Session.create(**portal_kwargs)
        return redirect(portal.url)
    except Exception as exc:
        messages.error(request, f'Could not open billing portal: {exc}')
        return redirect('courses')


@login_required
def membership_billing_return(request):
    """
    Landing point after a member returns from the Stripe billing portal.

    Pulls the subscription fresh from Stripe so any change made in the portal
    (cancel, payment method fix, plan switch) is reflected immediately instead
    of waiting for a webhook that might lag or be missed for Connect tenants.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return redirect('courses')

    subscription = StudentSubscription.objects.filter(tenant=tenant, user=request.user).first()
    if subscription:
        from .utils.membership_sync import pull_subscription_from_stripe
        changed, err = pull_subscription_from_stripe(subscription)
        if not err and subscription.status == 'canceled':
            messages.info(request, 'Your membership has been canceled.')

    return redirect('courses')


def _membership_cta_context(request, tenant, user):
    """
    Shared context for student-facing membership CTAs.

    Returns:
      membership_offer   dict|None  — the legacy all-access plan (if purchasable)
      membership_active  bool       — user has an access-granting subscription
      membership_tiers   list       — available tier cards (empty if none)
      current_tier_name  str|None   — the member's current tier
      membership_upgrade_available  bool — a higher-rank tier exists to upsell
    """
    empty = {
        'membership_offer': None, 'membership_active': False,
        'membership_tiers': [], 'current_tier_name': None,
        'membership_upgrade_available': False,
    }
    if tenant is None:
        return empty

    plan = getattr(tenant, 'membership_plan', None)
    if plan is None:
        plan = MembershipPlan.objects.filter(tenant=tenant).first()

    config = getattr(tenant, 'config', None)
    stripe_ready = bool(
        config and (
            config.stripe_own_secret_key
            or (config.stripe_connect_account_id and config.stripe_connect_charges_enabled)
        )
    )
    if not stripe_ready:
        return empty

    from .utils.membership import get_active_subscription, tier_course_ids

    sub = get_active_subscription(user, tenant) if user.is_authenticated else None
    membership_active = sub is not None

    available_tiers = [
        t for t in MembershipTier.objects.filter(
            tenant=tenant, is_archived=False, is_purchasable=True,
        ).order_by('rank', 'id')
        if (t.monthly_price or t.yearly_price)
    ]

    tier_cards = []
    for t in available_tiers:
        try:
            course_count = None if t.includes_all else len(tier_course_ids(t))
        except Exception:
            course_count = None
        tier_cards.append({
            'code': t.code,
            'name': t.name,
            'description': t.description,
            'monthly_price': t.monthly_price,
            'yearly_price': t.yearly_price,
            'includes_all': t.includes_all,
            'course_count': course_count,
            'rank': t.rank,
        })

    plan_offer = None
    if plan is not None and plan.is_purchasable():
        plan_offer = {
            'name': plan.name,
            'description': plan.description,
            'monthly_price': plan.monthly_price,
            'yearly_price': plan.yearly_price,
        }

    if plan_offer is None and not tier_cards:
        return empty

    current_tier_name = sub.tier.name if (sub and sub.tier_id) else None
    current_rank = sub.tier.rank if (sub and sub.tier_id) else None
    upgrade_available = bool(
        current_rank is not None and any(t.rank > current_rank for t in available_tiers)
    )

    return {
        'membership_offer': plan_offer,
        'membership_active': membership_active,
        'membership_tiers': tier_cards,
        'current_tier_name': current_tier_name,
        'membership_upgrade_available': upgrade_available,
    }


@ensure_csrf_cookie
def login_view(request):
    """Premium login page"""
    def _default_redirect_for_user(user):
        if user.is_superuser:
            return 'superadmin_home'
        if user.is_staff:
            return 'dashboard_home'
        return 'courses'

    # Allow access to login page even when logged in if ?force=true (for testing)
    force = request.GET.get('force', '').lower() == 'true'
    if request.user.is_authenticated and not force:
        return redirect(_default_redirect_for_user(request.user))

    tenant = getattr(request, 'tenant', None)
    tenant_branding = get_tenant_branding(tenant)
    custom_pages = _get_tenant_custom_pages(tenant)

    def _render_login_page():
        if custom_pages.get('login_mode') == 'custom' and custom_pages.get('login_html'):
            rendered = _render_tenant_custom_html(request, tenant, custom_pages.get('login_html'))
            if rendered is not None:
                return rendered
        return render(request, 'login.html', {'tenant_branding': tenant_branding})

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            if tenant and not user.is_superuser:
                membership = TenantMembership.objects.filter(
                    tenant=tenant,
                    user=user,
                    is_active=True
                ).first()
                if not membership:
                    messages.error(request, 'This account does not have access to this tenant portal.')
                    return _render_login_page()
            login(request, user)
            if TenantMembership.objects.filter(
                user=user,
                is_active=True,
                must_change_password=True
            ).exists():
                requested_next = (request.POST.get('next') or request.GET.get('next') or '').strip()
                if requested_next and url_has_allowed_host_and_scheme(
                    url=requested_next,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    request.session['post_password_change_redirect'] = requested_next
                return redirect('force_password_change')

            default_next = _default_redirect_for_user(user)
            default_next_url = reverse(default_next)
            requested_next = (request.POST.get('next') or request.GET.get('next') or '').strip()

            if requested_next and not url_has_allowed_host_and_scheme(
                url=requested_next,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                requested_next = ''

            # Ignore generic public paths for elevated roles and send them
            # directly to their control panel by default.
            if user.is_superuser and requested_next in {'/', reverse('home'), reverse('courses')}:
                requested_next = ''
            elif user.is_staff and requested_next in {'/', reverse('home'), reverse('courses')}:
                requested_next = ''

            return redirect(requested_next or default_next_url)
        else:
            messages.error(request, 'Invalid username or password.')

    return _render_login_page()


@login_required
@ensure_csrf_cookie
def force_password_change(request):
    """Force users flagged by membership to choose a new password."""
    must_change = TenantMembership.objects.filter(
        user=request.user,
        is_active=True,
        must_change_password=True,
    ).exists()
    if not must_change:
        if request.user.is_superuser:
            return redirect('superadmin_home')
        if request.user.is_staff:
            return redirect('dashboard_home')
        return redirect('courses')

    if request.method == 'POST':
        new_password = request.POST.get('new_password') or ''
        confirm_password = request.POST.get('confirm_password') or ''

        if not new_password:
            messages.error(request, 'New password is required.')
            return render(request, 'force_password_change.html')
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'force_password_change.html')

        try:
            validate_password(new_password, request.user)
        except ValidationError as exc:
            for err in exc.messages:
                messages.error(request, err)
            return render(request, 'force_password_change.html')

        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        TenantMembership.objects.filter(
            user=request.user,
            is_active=True,
            must_change_password=True,
        ).update(
            must_change_password=False,
            updated_at=timezone.now(),
        )
        update_session_auth_hash(request, request.user)

        messages.success(request, 'Password updated successfully.')
        requested_next = (request.session.pop('post_password_change_redirect', '') or '').strip()
        if requested_next and url_has_allowed_host_and_scheme(
            url=requested_next,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(requested_next)
        if request.user.is_superuser:
            return redirect('superadmin_home')
        if request.user.is_staff:
            return redirect('dashboard_home')
        return redirect('courses')

    return render(request, 'force_password_change.html')


def _registration_intent(request):
    """Read a purchase intent (membership plan / programme / next URL) that a
    landing page may pass into registration, from either GET or the carried
    POST hidden fields."""
    return {
        'plan': (request.POST.get('plan') or request.GET.get('plan') or '').strip(),
        'course': (request.POST.get('course') or request.GET.get('course') or '').strip(),
        'next': (request.POST.get('next') or request.GET.get('next') or '').strip(),
    }


def _register_offerings(tenant):
    """Membership + paid programmes to surface on the registration page so a new
    student can see (and pre-select) what they can join. Returns (offer, programs)
    where either may be empty when the tenant sells nothing."""
    if tenant is None:
        return None, []

    plan = MembershipPlan.objects.filter(tenant=tenant).first()
    membership_offer = None
    if plan and plan.is_purchasable():
        membership_offer = {
            'name': plan.name,
            'monthly_price': plan.monthly_price,
            'yearly_price': plan.yearly_price,
        }

    programs = list(
        Course.objects.filter(tenant=tenant, price__isnull=False, price__gt=0)
        .exclude(visibility='hidden')
        .order_by('display_order', 'name')
        .values('name', 'slug', 'price', 'member_price', 'status')
    )
    return membership_offer, programs


def _plan_interval(value):
    """Map a membership plan token from the landing page to a Stripe interval."""
    return {
        'month': 'month', 'monthly': 'month',
        'year': 'year', 'yearly': 'year', 'annual': 'year', 'annually': 'year',
    }.get((value or '').strip().lower())


def _start_membership_registration(request, tenant, username, email, raw_password, interval, tier=None):
    """
    Payment-first signup: hold the account details in a PendingRegistration and
    open a Stripe subscription checkout. The account is only created once payment
    succeeds (via the success redirect or the webhook), so abandoning checkout
    never leaves an unpaid ghost account.
    Returns (checkout_url, error_message); exactly one is truthy.
    """
    from django.contrib.auth.hashers import make_password
    from decimal import Decimal

    config, use_own_keys, use_connect, err = _resolve_tenant_stripe_mode(tenant)
    if err:
        return None, err

    # Resolve the offer price: a tier's Stripe price, or the legacy plan price.
    stripe_price_id = ''
    if tier is not None:
        if not tier.is_available():
            return None, 'That membership tier is not available.'
        amount = tier.price_for(interval)
        offer_name = tier.name
        offer_desc = tier.description or f'{tier.name} membership'
    else:
        plan = MembershipPlan.objects.filter(tenant=tenant).first()
        if not plan or not plan.is_purchasable():
            return None, 'Membership is not available for this academy.'
        amount = plan.monthly_price if interval == 'month' else plan.yearly_price
        offer_name = plan.name
        offer_desc = plan.description or 'All-access membership'

    if use_own_keys:
        stripe.api_key = config.stripe_own_secret_key.strip()
    elif not _stripe_client_configured():
        return None, 'Stripe is not configured.'

    if tier is not None:
        stripe_price_id = tier.stripe_price_id_for(interval)
        if not stripe_price_id:
            from .utils.membership_sync import sync_tier_prices
            ok, _price_err = sync_tier_prices(tier)
            if ok:
                tier.refresh_from_db()
                stripe_price_id = tier.stripe_price_id_for(interval)

    if not stripe_price_id and not amount:
        return None, f'No {interval}ly price is configured.'

    pending = PendingRegistration.objects.create(
        tenant=tenant,
        username=username,
        email=email,
        password=make_password(raw_password),
        interval=interval,
        tier=tier,
    )

    try:
        if stripe_price_id:
            line_item = {'price': stripe_price_id, 'quantity': 1}
        else:
            amount_cents = int((Decimal(str(amount)) * 100).quantize(Decimal('1')))
            if amount_cents <= 0:
                pending.delete()
                return None, 'Membership price must be greater than zero.'
            line_item = {
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': offer_name, 'description': offer_desc},
                    'unit_amount': amount_cents,
                    'recurring': {'interval': interval},
                },
                'quantity': 1,
            }

        base = f"{request.scheme}://{request.get_host()}"
        success_url = f"{base}/register/complete/?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base}/register/?resume=1"

        metadata = {
            'flow': 'membership_registration',
            'tenant_id': str(tenant.id),
            'pending_registration_id': str(pending.id),
            'interval': interval,
        }
        if tier is not None:
            metadata['membership_tier_id'] = str(tier.id)
            metadata['membership_tier_code'] = tier.code

        session_kwargs = dict(
            mode='subscription',
            line_items=[line_item],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=f"tenant:{tenant.id}:membership_registration:{pending.id}",
            metadata=metadata,
            subscription_data={'metadata': dict(metadata)},
        )
        if email:
            session_kwargs['customer_email'] = email
        if use_connect:
            session_kwargs['stripe_account'] = config.stripe_connect_account_id

        session = stripe.checkout.Session.create(**session_kwargs)
        pending.stripe_checkout_session_id = session.id
        pending.save(update_fields=['stripe_checkout_session_id'])
        return session.url, None
    except Exception as exc:
        pending.delete()
        return None, str(exc)


def _activate_membership_registration(session):
    """
    Create the account + active membership from a paid membership-registration
    checkout. Idempotent and safe to call from both the success redirect and the
    webhook (row-locked). Returns the User, or None when nothing was created.
    """
    metadata = session.get('metadata') or {}
    if metadata.get('flow') != 'membership_registration':
        return None
    pending_id = metadata.get('pending_registration_id')
    if not pending_id:
        return None

    with transaction.atomic():
        pending = (
            PendingRegistration.objects.select_for_update()
            .filter(id=pending_id).first()
        )
        if pending is None:
            return None

        tenant = pending.tenant
        existing = User.objects.filter(username=pending.username).first()

        # Already handled (webhook or a prior redirect) → return existing user.
        if pending.consumed or existing is not None:
            if not pending.consumed:
                pending.consumed = True
                pending.save(update_fields=['consumed'])
            return existing

        user = User(username=pending.username, email=pending.email)
        user.password = pending.password  # already hashed by make_password
        user.save()

        TenantMembership.objects.get_or_create(
            tenant=tenant, user=user,
            defaults={'role': 'student', 'is_active': True},
        )

        interval = pending.interval if pending.interval in ('month', 'year') else 'month'
        sub, _ = StudentSubscription.objects.get_or_create(
            tenant=tenant, user=user, defaults={'interval': interval},
        )
        sub.interval = interval
        sub.status = 'active'
        sub.is_complimentary = False
        sub.canceled_at = None
        if pending.tier is not None:
            sub.access_mode = 'tiered'
            sub.tier = pending.tier
        else:
            sub.access_mode = 'all_access'
            sub.tier = None
        sub_id = session.get('subscription')
        if isinstance(sub_id, dict):
            sub_id = sub_id.get('id', '')
        if sub_id:
            sub.stripe_subscription_id = str(sub_id)
        if session.get('customer'):
            sub.stripe_customer_id = str(session.get('customer'))
        sub.last_synced_at = timezone.now()
        sub.save()

        pending.consumed = True
        pending.save(update_fields=['consumed'])
        return user


def _post_auth_redirect(request, tenant):
    """Where to send a user after they authenticate, honoring any registration
    intent so the journey started on the landing page continues (e.g. straight
    into membership checkout, or back to the programme they wanted to buy)."""
    from django.urls import reverse
    from django.utils.http import url_has_allowed_host_and_scheme

    intent = _registration_intent(request)

    interval = _plan_interval(intent['plan'])
    if interval:
        return f"{reverse('courses')}?start_membership={interval}"

    if intent['course'] and tenant is not None:
        if Course.objects.filter(tenant=tenant, slug=intent['course']).exists():
            return reverse('course_detail', args=[intent['course']])

    next_url = intent['next']
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return next_url

    return reverse('courses')


@ensure_csrf_cookie
def register_view(request):
    """
    Tenant-aware self-registration.
    New users are attached to the tenant resolved from the request domain.
    """
    tenant = getattr(request, 'tenant', None)

    if request.user.is_authenticated:
        return redirect(_post_auth_redirect(request, tenant))

    if tenant is None:
        messages.info(request, 'Create your academy first, then students can register on that tenant domain.')
        return redirect('start_academy')
    if tenant and not tenant.is_active:
        messages.error(request, 'This tenant portal is currently inactive.')
        return redirect('login')

    custom_pages = _get_tenant_custom_pages(tenant)

    def _render_register_page():
        if custom_pages.get('signup_mode') == 'custom' and custom_pages.get('signup_html'):
            rendered = _render_tenant_custom_html(request, tenant, custom_pages.get('signup_html'))
            if rendered is not None:
                return rendered
        membership_offer, programs = _register_offerings(tenant)
        # Returning from an abandoned membership checkout: prefill their details
        # and re-select the plan so they can complete payment.
        resume = request.GET.get('resume') == '1'
        prefill = request.session.get('pending_registration_form') or {} if resume else {}
        intent = _registration_intent(request)
        if resume and not intent['plan'] and prefill.get('plan'):
            intent['plan'] = prefill['plan']
        return render(request, 'register.html', {
            'intent': intent,
            'membership_offer': membership_offer,
            'programs': programs,
            'resume': resume,
            'prefill': prefill,
        })

    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip().lower()
        password = request.POST.get('password') or ''
        confirm_password = request.POST.get('confirm_password') or ''

        if not username or not password:
            messages.error(request, 'Username and password are required.')
            return _render_register_page()
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return _render_register_page()
        if User.objects.filter(username=username).exists():
            messages.error(request, 'That username is already in use.')
            return _render_register_page()
        if email and User.objects.filter(email=email).exists():
            messages.error(request, 'That email is already in use.')
            return _render_register_page()

        # Payment-first path: if a membership was selected, don't create the
        # account yet — take payment, then create it on success.
        intent = _registration_intent(request)
        interval = _plan_interval(intent['plan'])
        if interval:
            tier = None
            tier_code = (request.POST.get('tier_code') or '').strip()
            if tier_code:
                tier = MembershipTier.objects.filter(tenant=tenant, code=tier_code).first()
            checkout_url, err = _start_membership_registration(
                request, tenant, username, email, password, interval, tier,
            )
            if checkout_url:
                request.session['pending_registration_form'] = {
                    'username': username, 'email': email, 'plan': intent['plan'],
                }
                return redirect(checkout_url)
            messages.error(request, f'Could not start membership checkout: {err}')
            return _render_register_page()

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )
        membership = TenantMembership.objects.create(
            tenant=tenant,
            user=user,
            role='student',
            is_active=True
        )
        from .utils.coupons import attach_signup_coupon
        used_coupon = attach_signup_coupon(request, membership)
        login(request, user)
        if used_coupon:
            messages.success(
                request,
                f'Welcome to {tenant.name}. Your account has been created with coupon {used_coupon.code}.',
            )
        else:
            messages.success(request, f'Welcome to {tenant.name}. Your account has been created.')
        return redirect(_post_auth_redirect(request, tenant))

    return _render_register_page()


def register_membership_complete(request):
    """
    Stripe success redirect for payment-first membership signups. Verifies the
    payment, creates the account + active membership, and logs the student in.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'Unable to verify payment — no tenant context.')
        return redirect('home')

    session_id = (request.GET.get('session_id') or '').strip()
    if not session_id:
        messages.error(request, 'Missing payment session — contact support if you were charged.')
        return redirect('register')

    config = getattr(tenant, 'config', None)
    use_own_keys = bool(config and config.stripe_own_secret_key)
    use_connect = bool(config and config.stripe_connect_account_id)
    try:
        retrieve_kwargs = {'expand': ['subscription']}
        if use_own_keys:
            stripe.api_key = config.stripe_own_secret_key.strip()
        elif use_connect:
            _stripe_client_configured()
            retrieve_kwargs['stripe_account'] = config.stripe_connect_account_id
        else:
            _stripe_client_configured()
        session = stripe.checkout.Session.retrieve(session_id, **retrieve_kwargs)
    except Exception:
        messages.error(request, 'Could not verify your payment. If you were charged, contact support.')
        return redirect('register')

    metadata = session.get('metadata') or {}
    if metadata.get('flow') != 'membership_registration' or metadata.get('tenant_id') != str(tenant.id):
        messages.error(request, 'This payment session does not match this academy.')
        return redirect('register')

    stripe_sub = session.get('subscription')
    sub_status = stripe_sub.get('status') if isinstance(stripe_sub, dict) else None
    paid = session.get('payment_status') == 'paid' or sub_status in ('active', 'trialing')
    if not paid:
        messages.warning(
            request,
            'Payment is not confirmed yet. Once it clears your account will be created — '
            'try signing in shortly, or contact support if you were charged.',
        )
        return redirect('login')

    user = _activate_membership_registration(session)
    if user is None:
        messages.error(request, 'We could not finish creating your account. Please contact support.')
        return redirect('register')

    request.session.pop('pending_registration_form', None)
    login(request, user)
    messages.success(request, f'Welcome to {tenant.name}! Your membership is now active.')
    return redirect('courses')


def logout_view(request):
    """Logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('login')


def courses(request):
    """
    Unified learning hub: dashboard for logged-in users, catalog for guests.
    Replaces the separate courses + student_dashboard pages.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.info(request, 'Use your tenant portal URL to access courses.')
        return redirect('home')

    if request.user.is_authenticated:
        return _courses_authenticated(request)
    return _courses_guest(request)


def _courses_guest(request):
    """Catalog view for logged-out users"""
    tenant = getattr(request, 'tenant', None)
    search_query = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'custom')
    # Exclude hidden courses — VISIBILITY_CHOICES documents them as
    # "not in catalog, direct link only", so they don't belong in the
    # anonymous browse view. Same exclusion applies in
    # get_courses_by_visibility for authenticated users.
    courses_qs = (
        Course.objects.prefetch_related('lessons')
        .filter(status='active')
        .exclude(visibility='hidden')
    )
    if tenant is not None:
        courses_qs = courses_qs.filter(tenant=tenant)
    if search_query:
        courses_qs = courses_qs.filter(name__icontains=search_query)
    if sort_by == 'name':
        courses_qs = courses_qs.order_by('name', '-created_at')
    else:
        courses_qs = courses_qs.order_by('display_order', 'name', '-created_at')
    courses_list = list(courses_qs)
    courses_data = [{'course': c, 'has_any_progress': False, 'progress_percentage': 0, 'is_favorited': False} for c in courses_list]
    context = {
        'my_courses': [],
        'available_to_unlock': [],
        'courses_data': courses_data,
        'in_progress_courses': [],
        'not_started_courses': [],
        'total_courses': 0,
        'completed_courses': 0,
        'total_lessons_all': 0,
        'completed_lessons_all': 0,
        'overall_progress': 0,
        'filter_favorites': '',
        'sort_by': sort_by,
        'search_query': search_query,
        'guest_catalog': courses_data,
        'is_guest_view': True,
    }
    context.update(_membership_cta_context(request, tenant, request.user))
    return render(request, 'learning_hub.html', context)


def _courses_authenticated(request):
    """Full dashboard for logged-in users - merges dashboard + courses"""
    from .utils.access import get_courses_by_visibility, has_course_access, check_course_prerequisites, batch_has_course_access
    from .models import FavoriteCourse, Bundle
    from django.db.models import Count

    user = request.user
    search_query = request.GET.get('search', '')

    # Dashboard data (access-based)
    tenant = getattr(request, 'tenant', None)

    # Tenant admins should always see/manage their tenant courses without
    # manually granting themselves access for each new course.
    if tenant is not None:
        is_tenant_admin = user.is_superuser or TenantMembership.objects.filter(
            tenant=tenant,
            user=user,
            role='tenant_admin',
            is_active=True
        ).exists()
        if is_tenant_admin:
            for course in Course.objects.filter(status='active', tenant=tenant):
                CourseAccess.objects.get_or_create(
                    tenant=tenant,
                    user=user,
                    course=course,
                    defaults={
                        'access_type': 'manual',
                        'status': 'unlocked',
                        'notes': 'Auto-granted for tenant admin',
                    }
                )

    courses_by_visibility = get_courses_by_visibility(user, tenant=tenant)
    my_courses = list(courses_by_visibility['my_courses'])
    available_to_unlock = list(courses_by_visibility['available_to_unlock'])

    # Legacy enrollments
    enrollments = CourseEnrollment.objects.filter(user=user, course__tenant=tenant).select_related('course')
    if not enrollments.exists() and user.is_staff:
        for course in Course.objects.filter(status='active', tenant=tenant):
            CourseEnrollment.objects.get_or_create(user=user, course=course, defaults={'tenant': course.tenant})
        enrollments = CourseEnrollment.objects.filter(user=user, course__tenant=tenant).select_related('course')

    my_course_ids = [c.id for c in my_courses]
    enrollments_dict = {e.course_id: e for e in CourseEnrollment.objects.filter(user=user, course_id__in=my_course_ids).select_related('course')}

    progress_data = UserProgress.objects.filter(user=user, lesson__course_id__in=my_course_ids).values('lesson__course_id').annotate(
        total_lessons=Count('lesson_id', distinct=True),
        completed_lessons=Count('lesson_id', filter=Q(completed=True), distinct=True),
        has_any_progress=Count('id', filter=Q(completed=True) | Q(video_watch_percentage__gt=0) | Q(status__in=['in_progress', 'completed'])),
        avg_watch=Avg('video_watch_percentage')
    )
    progress_by_course = {item['lesson__course_id']: item for item in progress_data}
    course_lesson_counts = {cid: cnt for cid, cnt in Course.objects.filter(id__in=my_course_ids).annotate(lesson_count=Count('lessons')).values_list('id', 'lesson_count')}

    exams_dict = {e.course_id: e for e in Exam.objects.filter(course_id__in=my_course_ids).select_related('course')}
    exam_attempts_by_exam = {}
    if exams_dict:
        exam_ids = [e.id for e in exams_dict.values()]
        for a in ExamAttempt.objects.filter(user=user, exam_id__in=exam_ids).select_related('exam'):
            exam_attempts_by_exam.setdefault(a.exam_id, []).append(a)
    certifications_dict = {c.course_id: c for c in Certification.objects.filter(user=user, course_id__in=my_course_ids).select_related('course')}
    favorite_course_ids = set(FavoriteCourse.objects.filter(user=user, course_id__in=my_course_ids).values_list('course_id', flat=True))
    access_by_course = batch_has_course_access(user, my_course_ids)

    # Build my_courses_data
    my_courses_data = []
    for course in my_courses:
        has_access, access_record, _ = access_by_course.get(course.id, (False, None, "No access"))
        if not has_access:
            continue
        enrollment = enrollments_dict.get(course.id)
        cid = course.id
        total_lessons = course_lesson_counts.get(cid, 0)
        prog = progress_by_course.get(cid, {})
        completed = prog.get('completed_lessons', 0)
        has_any = prog.get('has_any_progress', 0) > 0
        avg_watch = prog.get('avg_watch', 0) or 0
        pct = int((completed / total_lessons * 100)) if total_lessons > 0 else 0

        exam = exams_dict.get(cid)
        exam_info = {'exists': False}
        if exam:
            attempts = exam_attempts_by_exam.get(exam.id, [])
            latest = sorted(attempts, key=lambda x: x.started_at, reverse=True)[0] if attempts else None
            exam_info = {'exists': True, 'attempts_count': len(attempts), 'max_attempts': exam.max_attempts, 'latest_attempt': latest, 'passed': any(a.passed for a in attempts), 'is_available': enrollment.is_exam_available() if enrollment else False}

        cert = certifications_dict.get(cid)
        if cert:
            cert_status, cert_display = cert.status, cert.get_status_display()
        else:
            cert_status = 'eligible' if pct >= 100 else 'not_eligible'
            cert_display = 'Eligible' if pct >= 100 else 'Not Eligible'

        my_courses_data.append({
            'course': course, 'enrollment': enrollment, 'access_record': access_record,
            'total_lessons': total_lessons, 'completed_lessons': completed, 'progress_percentage': pct,
            'has_any_progress': has_any, 'avg_watch_percentage': round(avg_watch, 1), 'exam_info': exam_info,
            'certification': cert, 'cert_status': cert_status, 'cert_display': cert_display, 'is_favorited': cid in favorite_course_ids,
        })

    # Legacy enrollments not yet in my_courses_data
    existing_ids = {cd['course'].id for cd in my_courses_data}
    for enrollment in enrollments:
        if enrollment.course_id in existing_ids:
            continue
        has_access, access_record, _ = has_course_access(user, enrollment.course)
        if not has_access:
            from .utils.access import grant_course_access
            access_record = grant_course_access(user=user, course=enrollment.course, access_type='purchase', notes="Migrated from legacy enrollment")
        cid = enrollment.course_id
        total_lessons = course_lesson_counts.get(cid, enrollment.course.lessons.count())
        prog = progress_by_course.get(cid, {})
        completed = prog.get('completed_lessons', 0)
        pct = int((completed / total_lessons * 100)) if total_lessons > 0 else 0
        exam = exams_dict.get(cid)
        exam_info = {'exists': False}
        if exam:
            attempts = exam_attempts_by_exam.get(exam.id, [])
            exam_info = {'exists': True, 'attempts_count': len(attempts), 'max_attempts': exam.max_attempts, 'latest_attempt': attempts[0] if attempts else None, 'passed': any(a.passed for a in attempts), 'is_available': enrollment.is_exam_available()}
        cert = certifications_dict.get(cid)
        cert_status = cert.status if cert else ('eligible' if pct >= 100 else 'not_eligible')
        cert_display = cert.get_status_display() if cert else ('Eligible' if pct >= 100 else 'Not Eligible')
        my_courses_data.append({
            'course': enrollment.course, 'enrollment': enrollment, 'access_record': access_record,
            'total_lessons': total_lessons, 'completed_lessons': completed, 'progress_percentage': pct,
            'has_any_progress': prog.get('has_any_progress', 0) > 0, 'avg_watch_percentage': round(prog.get('avg_watch', 0) or 0, 1),
            'exam_info': exam_info, 'certification': cert, 'cert_status': cert_status, 'cert_display': cert_display,
            'is_favorited': cid in favorite_course_ids,
        })

    # Available to unlock
    available_ids = [c.id for c in available_to_unlock]
    bundles_by_course = {}
    if available_ids:
        for b in Bundle.objects.filter(courses__id__in=available_ids, is_active=True).prefetch_related('courses'):
            for c in b.courses.all():
                if c.id in available_ids:
                    bundles_by_course.setdefault(c.id, []).append(b)
    available_courses_data = []
    for c in available_to_unlock:
        prereqs_met, missing_prereqs = check_course_prerequisites(user, c)
        can_self_enroll = c.enrollment_method == 'open' and prereqs_met
        available_courses_data.append({
            'course': c,
            'prereqs_met': prereqs_met,
            'missing_prereqs': missing_prereqs,
            'bundles': bundles_by_course.get(c.id, []),
            'can_self_enroll': can_self_enroll,
        })

    # Filter controls (sorting intentionally removed for this view).
    filter_favorites = (request.GET.get('favorites', '') or '').strip().lower()
    filter_category_raw = (request.GET.get('category', '') or '').strip()
    filter_all = (request.GET.get('all', '') or '').strip().lower() in {'1', 'true', 'yes', 'on'}

    my_courses_data.sort(
        key=lambda x: (
            1 if not (x['course'].category or '').strip() else 0,
            (x['course'].category or '').strip().lower(),
            x['course'].display_order,
            x['course'].name.lower(),
        )
    )

    # Category counts from the unfiltered set (drives the "browse by category" cards/dropdown).
    category_counts = {}
    for item in my_courses_data:
        name = (item['course'].category or '').strip() or 'Uncategorized'
        category_counts[name] = category_counts.get(name, 0) + 1

    category_order_map = CourseCategory.order_map_for_tenant(tenant)
    available_categories = sort_category_names(category_counts.keys(), category_order_map)
    category_thumbnails = CourseCategory.thumbnail_map_for_tenant(tenant)
    category_cards = [
        {
            'name': name,
            'count': category_counts[name],
            'thumbnail_url': category_thumbnails.get(name.strip().lower(), ''),
            'initial': category_initial(name),
            'color': category_accent_color(name),
        }
        for name in available_categories
    ]

    category_lookup = {category.lower(): category for category in available_categories}
    filter_category = category_lookup.get(filter_category_raw.lower(), '') if filter_category_raw else ''

    # Default landing shows category cards when the tenant actually uses categories
    # (more than one distinct category). Otherwise course cards show directly.
    show_category_cards = (
        len(available_categories) > 1
        and not filter_category
        and filter_favorites != 'true'
        and not filter_all
    )

    if filter_category:
        my_courses_data = [
            item for item in my_courses_data
            if (((item['course'].category or '').strip() or 'Uncategorized').lower() == filter_category.lower())
        ]

    if filter_favorites == 'true':
        my_courses_data = [c for c in my_courses_data if c.get('is_favorited', False)]

    # Stats
    total_courses = len(my_courses_data)
    completed_courses = sum(1 for c in my_courses_data if c['progress_percentage'] == 100)
    total_lessons_all = sum(c['total_lessons'] for c in my_courses_data)
    completed_lessons_all = sum(c['completed_lessons'] for c in my_courses_data)
    overall_progress = int((completed_lessons_all / total_lessons_all * 100)) if total_lessons_all > 0 else 0

    # Split for "Continue Learning" vs "Learn More"
    in_progress = [c for c in my_courses_data if c['has_any_progress']]
    not_started = [c for c in my_courses_data if not c['has_any_progress']]

    context = {
        'my_courses': my_courses_data,
        'in_progress_courses': in_progress,
        'not_started_courses': not_started,
        'courses_data': my_courses_data,
        'available_to_unlock': available_courses_data,
        'total_courses': total_courses,
        'completed_courses': completed_courses,
        'total_lessons_all': total_lessons_all,
        'completed_lessons_all': completed_lessons_all,
        'overall_progress': overall_progress,
        'filter_favorites': filter_favorites,
        'sort_by': 'custom',
        'available_categories': available_categories,
        'category_cards': category_cards,
        'show_category_cards': show_category_cards,
        'filter_all': filter_all,
        'filter_category': filter_category,
        'search_query': search_query,
        'guest_catalog': None,
        'is_guest_view': False,
    }
    context.update(_membership_cta_context(request, tenant, user))
    return render(request, 'learning_hub.html', context)


@login_required
def enroll_course(request, course_slug):
    """Enroll in a course (self-enrollment for open-enrollment courses) and redirect to course."""
    course = get_object_or_404(course_queryset_for_slug(request, course_slug))
    user = request.user

    from .utils.access import has_course_access, grant_course_access, check_course_prerequisites

    # Already has access? Go straight to course
    has_access, _, _ = has_course_access(user, course)
    if has_access:
        return redirect('course_detail', course_slug=course_slug)

    # Check if self-enrollment is allowed (open enrollment + prerequisites met)
    prereqs_met, _ = check_course_prerequisites(user, course)
    can_enroll = course.enrollment_method == 'open' and prereqs_met

    if can_enroll:
        grant_course_access(
            user=user,
            course=course,
            access_type='manual',
            notes='Self-enrolled via Start Course',
        )
        CourseEnrollment.objects.get_or_create(
            user=user,
            course=course,
            defaults={'tenant': course.tenant}
        )
        messages.success(request, f'You have been enrolled in {course.name}.')
        first_lesson = course.lessons.order_by('order', 'id').first()
        if first_lesson:
            return redirect('lesson_detail', course_slug=course.slug, lesson_slug=first_lesson.slug)
        return redirect('course_detail', course_slug=course_slug)

    # Cannot self-enroll - show message and go to course detail
    if not prereqs_met:
        messages.info(request, 'Complete the prerequisite course(s) first to unlock this course.')
    elif course.enrollment_method == 'purchase':
        messages.info(request, 'This course requires purchase. View bundles or contact support.')
    else:
        messages.info(request, 'This course requires assignment. Contact your administrator.')
    return redirect('course_detail', course_slug=course_slug)


# ========== PUBLIC EVENTS (standalone live-events module) ==========

def events(request):
    """Public catalog of published events for the current tenant (visible to guests)."""
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.info(request, 'Use your tenant portal URL to access events.')
        return redirect('home')

    search_query = request.GET.get('search', '')
    events_qs = Event.objects.filter(tenant=tenant, status='published')
    if search_query:
        events_qs = events_qs.filter(title__icontains=search_query)
    events_qs = events_qs.order_by('event_date', 'start_time', 'display_order')

    now = timezone.now()
    upcoming, past = [], []
    for event in events_qs:
        (past if event.is_past() else upcoming).append(event)

    return render(request, 'events.html', {
        'upcoming_events': upcoming,
        'past_events': past,
        'total_events': len(upcoming) + len(past),
        'search_query': search_query,
    })


def event_detail(request, event_slug):
    """
    Public event detail. The join link is ONLY placed into context when the
    user is registered (has_event_access) — never exposed otherwise.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.info(request, 'Use your tenant portal URL to access events.')
        return redirect('home')

    event = get_object_or_404(Event, slug=event_slug, tenant=tenant, status='published')
    is_registered, _, _ = has_event_access(request.user, event)

    return render(request, 'event_detail.html', {
        'event': event,
        'is_registered': is_registered,
        # Only expose the join link to registered users.
        'join_link': event.join_link if is_registered else '',
        'registration_count': event.registration_count(),
    })


@login_required
@require_http_methods(["POST"])
def register_event(request, event_slug):
    """Free registration for an event, scoped to the current tenant."""
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.info(request, 'Use your tenant portal URL to register for events.')
        return redirect('home')

    event = get_object_or_404(Event, slug=event_slug, tenant=tenant, status='published')
    EventRegistration.objects.get_or_create(
        tenant=tenant,
        user=request.user,
        event=event,
    )
    messages.success(request, f'You are registered for {event.title}.')
    return redirect('event_detail', event_slug=event.slug)


@login_required
def course_detail(request, course_slug):
    """Course detail page - redirects to first lesson or course overview. Shows enroll option if no access."""
    from django.db.models import Prefetch as _Prefetch
    course = get_object_or_404(
        course_queryset_for_slug(request, course_slug).prefetch_related(
            _Prefetch('modules', queryset=Module.objects.order_by('order', 'id').prefetch_related(
                _Prefetch('lessons', queryset=Lesson.objects.order_by('order', 'id'))
            )),
            _Prefetch('lessons', queryset=Lesson.objects.order_by('order', 'id')),
        )
    )
    user = request.user

    from .utils.access import has_course_access, check_course_prerequisites
    has_access, _, _ = has_course_access(user, course)

    # Build syllabus: modules with their lessons, then orphan (no-module) lessons
    modules_qs = list(course.modules.all())
    ordered_lessons = list(course.lessons.all())
    orphan_lessons = [lesson for lesson in ordered_lessons if lesson.module_id is None]
    syllabus = []
    for mod in modules_qs:
        syllabus.append({'type': 'module', 'obj': mod, 'lessons': list(mod.lessons.all())})
    if orphan_lessons:
        syllabus.append({'type': 'module', 'obj': None, 'lessons': orphan_lessons})
    first_lesson = ordered_lessons[0] if ordered_lessons else None
    continue_lesson = first_lesson
    user_lessons_done = 0
    user_progress_pct = 0
    if has_access and ordered_lessons:
        completed_ids = set(
            UserProgress.objects.filter(
                user=user,
                lesson__course=course,
                completed=True
            ).values_list('lesson_id', flat=True)
        )
        user_lessons_done = len(completed_ids)
        total_lessons = len(ordered_lessons)
        user_progress_pct = int((user_lessons_done / total_lessons) * 100) if total_lessons else 0
        continue_lesson = next((lesson for lesson in ordered_lessons if lesson.id not in completed_ids), first_lesson)

    # No access - show overview with enroll option if applicable
    prereqs_met, missing_prereqs = check_course_prerequisites(user, course)
    can_self_enroll = course.enrollment_method == 'open' and prereqs_met
    from .models import Bundle, TenantConfig as TC
    bundles = list(Bundle.objects.filter(courses=course, is_active=True))

    # Direct course purchase
    config = None
    try:
        config = TC.objects.get(tenant=course.tenant)
    except TC.DoesNotExist:
        pass
    stripe_ready = bool(
        config and (config.stripe_own_secret_key or
                    (config.stripe_connect_account_id and config.stripe_connect_charges_enabled))
    )
    can_purchase = bool(course.price and stripe_ready and prereqs_met)

    from .utils.membership import effective_course_price
    display_price = effective_course_price(user, course)
    member_price_applies = bool(course.member_price is not None and display_price != course.price)

    tenant = getattr(course, 'tenant', None) or getattr(request, 'tenant', None)
    language_config = get_tenant_language_config(tenant)
    active_language = get_request_language(request, tenant)
    lesson_display_titles = build_lesson_title_map(ordered_lessons, active_language)

    context = {
        'course': course,
        'has_access': has_access,
        'can_self_enroll': can_self_enroll,
        'prereqs_met': prereqs_met,
        'missing_prereqs': missing_prereqs,
        'bundles': bundles,
        'can_purchase': can_purchase,
        'stripe_ready': stripe_ready,
        'display_price': display_price,
        'member_price_applies': member_price_applies,
        'syllabus': syllabus,
        'first_lesson': first_lesson,
        'continue_lesson': continue_lesson,
        'user_lessons_done': user_lessons_done,
        'user_progress_pct': user_progress_pct,
        'active_language': active_language,
        'enabled_languages': language_config['enabled'],
        'show_language_switcher': show_language_switcher(tenant, language_config),
        'language_labels': LANGUAGE_LABELS,
        'lesson_display_titles': lesson_display_titles,
    }
    context.update(_membership_cta_context(request, tenant, user))
    return render(request, 'course_detail.html', context)


@login_required
def lesson_detail(request, course_slug, lesson_slug):
    """Lesson detail page with three-column layout"""
    from django.db.models import Prefetch
    course_ref = get_object_or_404(course_queryset_for_slug(request, course_slug))
    _attach_orphan_lessons_to_first_module(course_ref)
    course = get_object_or_404(
        course_queryset_for_slug(request, course_slug).prefetch_related(
            'resources',
            Prefetch('modules', queryset=Module.objects.prefetch_related('lessons').order_by('order', 'id')),
            Prefetch('lessons', queryset=Lesson.objects.select_related('module').prefetch_related('quiz', 'quiz__questions').order_by('order', 'id')),
        ),
    )
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug)

    # Get user progress with optimized queries
    enrollment = CourseEnrollment.objects.filter(
        user=request.user,
        course=course
    ).select_related('course').first()

    # Batch fetch all progress data for this course (single query)
    all_progress = list(UserProgress.objects.filter(
        user=request.user,
        lesson__course=course
    ).values('lesson_id', 'completed', 'video_watch_percentage', 'last_watched_timestamp', 'status'))

    # Compute progress from batch data (no extra query)
    completed_lessons = [p['lesson_id'] for p in all_progress if p['completed']]

    # Get current lesson progress from batch data
    current_lesson_progress_data = next(
        (p for p in all_progress if p['lesson_id'] == lesson.id),
        None
    )

    if current_lesson_progress_data:
        video_watch_percentage = current_lesson_progress_data.get('video_watch_percentage', 0.0) or 0.0
        last_watched_timestamp = current_lesson_progress_data.get('last_watched_timestamp', 0.0) or 0.0
        lesson_status = current_lesson_progress_data.get('status', 'not_started') or 'not_started'
        # Create a mock object for template compatibility
        from types import SimpleNamespace
        current_lesson_progress = SimpleNamespace(
            video_watch_percentage=video_watch_percentage,
            last_watched_timestamp=last_watched_timestamp,
            status=lesson_status
        )
    else:
        video_watch_percentage = 0.0
        last_watched_timestamp = 0.0
        lesson_status = 'not_started'
        current_lesson_progress = None

    # Use prefetched lessons (no extra query)
    all_lessons = list(course.lessons.all())
    total_lessons = len(all_lessons)
    progress_percentage = int((len(completed_lessons) / total_lessons) * 100) if total_lessons > 0 else 0

    # Build lessons_by_module from prefetched data (avoid N+1)
    lessons_by_module = {}
    for l in all_lessons:
        mid = l.module_id or 0
        lessons_by_module.setdefault(mid, []).append(l)
    for mid in lessons_by_module:
        lessons_by_module[mid].sort(key=lambda x: (x.order, x.id))

    all_modules = list(course.modules.all())

    # All lessons are open from the start. Quizzes are optional across every
    # tenant (LessonQuiz.is_required is False), so no lesson is gated behind
    # completing or passing a previous one — every lesson is accessible and
    # nothing is locked.
    accessible_lessons = [l.id for l in all_lessons]
    lesson_locked = False

    # Work out next lesson (using prefetched data)
    next_lesson = None
    has_more_modules = False
    is_last_in_module = False

    if all_lessons and lesson.module_id:
        current_module_lessons_list = lessons_by_module.get(lesson.module_id, [])
        if current_module_lessons_list:
            last_in_module = current_module_lessons_list[-1]
            is_last_in_module = (last_in_module.id == lesson.id)
            if is_last_in_module:
                current_module_idx = next((idx for idx, m in enumerate(all_modules) if m.id == lesson.module_id), None)
                if current_module_idx is not None and current_module_idx + 1 < len(all_modules):
                    next_module = all_modules[current_module_idx + 1]
                    next_module_lessons = lessons_by_module.get(next_module.id, [])
                    if next_module_lessons:
                        next_lesson = next_module_lessons[0]
                        has_more_modules = True
            if not next_lesson:
                for idx, l in enumerate(current_module_lessons_list):
                    if l.id == lesson.id and idx + 1 < len(current_module_lessons_list):
                        next_lesson = current_module_lessons_list[idx + 1]
                        break

    if not next_lesson:
        for idx, l in enumerate(all_lessons):
            if l.id == lesson.id and idx + 1 < len(all_lessons):
                next_lesson = all_lessons[idx + 1]
                if lesson.module_id and next_lesson.module_id and lesson.module_id != next_lesson.module_id:
                    has_more_modules = True
                break

    # Get quiz and quiz attempts for this user (optimized)
    lesson_quiz = None
    try:
        lesson_quiz = lesson.quiz
    except:
        pass

    quiz_attempts = None
    latest_quiz_attempt = None
    quiz_passed = False
    if lesson_quiz:
        quiz_attempts = LessonQuizAttempt.objects.filter(
            user=request.user,
            quiz=lesson_quiz
        ).select_related('quiz', 'user').order_by('-completed_at')
        latest_quiz_attempt = quiz_attempts.first() if quiz_attempts.exists() else None
        quiz_passed = quiz_attempts.filter(passed=True).exists()

    tenant = getattr(course, 'tenant', None) or getattr(request, 'tenant', None)
    language_config = get_tenant_language_config(tenant)
    active_language = get_request_language(request, tenant)
    lesson_display = resolve_lesson(lesson, active_language)
    lesson_display_titles = build_lesson_title_map(all_lessons, active_language)
    quiz_display = resolve_quiz_display(lesson_quiz, active_language) if lesson_quiz else None
    from myApp.utils.lesson_blocks import prepare_lesson_article

    gen_settings = lesson.generation_settings if isinstance(lesson.generation_settings, dict) else {}
    is_pdf_import = gen_settings.get('source') == 'pdf_import'
    lesson_article = prepare_lesson_article(
        lesson_display.content if isinstance(getattr(lesson_display, 'content', None), dict) else None,
        title=getattr(lesson_display, 'title', None) or lesson.title,
    )
    has_lesson_video = bool(
        lesson.google_drive_url or lesson.get_vimeo_embed_url() or lesson.video_url
    )

    course_complete = False
    course_certificate_url = ''
    course_certificate_id = ''
    if total_lessons > 0 and len(completed_lessons) >= total_lessons:
        issued_cert = _issue_certificate_if_earned(request.user, course, request=request)
        course_complete = _course_certificate_ready(request.user, course)
        if issued_cert:
            course_certificate_url = reverse('download_course_certificate', kwargs={'course_slug': course.slug})
            course_certificate_id = issued_cert.accredible_certificate_id or ''

    return render(request, 'lesson.html', {
        'course': course,
        'lesson': lesson,
        'lesson_display': lesson_display,
        'progress_percentage': progress_percentage,
        'completed_lessons': completed_lessons,
        'accessible_lessons': accessible_lessons,
        'enrollment': enrollment,
        'current_lesson_progress': current_lesson_progress,
        'video_watch_percentage': video_watch_percentage,
        'last_watched_timestamp': last_watched_timestamp,
        'lesson_status': lesson_status,
        'next_lesson': next_lesson,
        'has_more_modules': has_more_modules,
        'is_last_in_module': is_last_in_module,
        'lesson_quiz': lesson_quiz,
        'quiz_display': quiz_display,
        'quiz_attempts': quiz_attempts,
        'latest_quiz_attempt': latest_quiz_attempt,
        'quiz_passed': quiz_passed,
        'orphan_lessons': [l for l in all_lessons if not l.module_id],
        'active_language': active_language,
        'enabled_languages': language_config['enabled'],
        'show_language_switcher': show_language_switcher(tenant, language_config),
        'language_labels': LANGUAGE_LABELS,
        'lesson_display_titles': lesson_display_titles,
        'lesson_article': lesson_article,
        'is_pdf_import': is_pdf_import,
        'has_lesson_video': has_lesson_video,
        'course_complete': course_complete,
        'course_certificate_url': course_certificate_url,
        'course_certificate_id': course_certificate_id,
    })


@login_required
def lesson_quiz_view(request, course_slug, lesson_slug):
    """Simple multiple‑choice quiz attached to a lesson (optional)."""
    course = get_object_or_404(course_queryset_for_slug(request, course_slug))
    _attach_orphan_lessons_to_first_module(course)
    lesson = get_object_or_404(Lesson, course=course, slug=lesson_slug)
    progress_tenant = _resolve_progress_tenant(request, lesson, course=course)

    # Require that a quiz exists for this lesson
    try:
        quiz = lesson.quiz
    except LessonQuiz.DoesNotExist:
        messages.info(request, 'No quiz is configured for this lesson yet.')
        return redirect('lesson_detail', course_slug=course_slug, lesson_slug=lesson_slug)

    questions = quiz.questions.all()
    result = None

    # Get next lesson for redirect after passing (use same logic as lesson_detail)
    all_lessons = course.lessons.order_by('order', 'id')
    next_lesson = None

    # Get user's completed lessons to check accessibility
    completed_lessons = list(
        UserProgress.objects.filter(
            tenant=progress_tenant,
            user=request.user,
            lesson__course=course,
            completed=True
        ).values_list('lesson_id', flat=True)
    )

    if all_lessons.exists():
        all_modules = course.modules.all().order_by('order', 'id')

        # Check if current lesson has a module
        if lesson.module and all_modules.exists():
            # Get all lessons in current module, ordered
            current_module_lessons = lesson.module.lessons.filter(course=course).order_by('order', 'id')
            current_module_lessons_list = list(current_module_lessons)

            # Check if this is the last lesson in the current module
            is_last_in_module = False
            if current_module_lessons_list:
                last_lesson_in_module = current_module_lessons_list[-1]
                if last_lesson_in_module.id == lesson.id:
                    is_last_in_module = True

            if is_last_in_module:
                # Find next module's first lesson
                current_module_found = False
                for module in all_modules:
                    if current_module_found:
                        # This is the next module - get its first lesson
                        next_module_lessons = module.lessons.filter(course=course).order_by('order', 'id')
                        if next_module_lessons.exists():
                            next_lesson = next_module_lessons.first()
                            break
                    if module.id == lesson.module.id:
                        current_module_found = True

            # If not last in module, get next lesson in same module
            if not is_last_in_module and not next_lesson:
                for idx, l in enumerate(current_module_lessons_list):
                    if l.id == lesson.id and idx + 1 < len(current_module_lessons_list):
                        next_lesson = current_module_lessons_list[idx + 1]
                        break

        # Fallback: if no module or no next lesson found, use sequential navigation
        if not next_lesson:
            lessons_list = list(all_lessons)
            for idx, l in enumerate(lessons_list):
                if l.id == lesson.id and idx + 1 < len(lessons_list):
                    next_lesson = lessons_list[idx + 1]
                    break

    if request.method == 'POST':
        total = questions.count()
        correct = 0
        for q in questions:
            answer = request.POST.get(f'q_{q.id}')
            if answer and answer == q.correct_option:
                correct += 1

        score = (correct / total * 100) if total > 0 else 0
        passed = score >= quiz.passing_score

        LessonQuizAttempt.objects.create(
            tenant=progress_tenant,
            user=request.user,
            quiz=quiz,
            score=score,
            passed=passed,
        )

        # If quiz is passed and lesson is required, auto-complete the lesson
        if passed and quiz.is_required:
            UserProgress.objects.update_or_create(
                tenant=progress_tenant,
                user=request.user,
                lesson=lesson,
                defaults={
                    'tenant': progress_tenant,
                    'completed': True,
                    'status': 'completed',
                }
            )

        certificate_available = False
        certificate_url = ''
        certificate_id = ''
        if passed:
            cert = _issue_certificate_if_earned(request.user, course, request=request)
            certificate_available = _course_certificate_ready(request.user, course)
            if cert:
                certificate_url = reverse('download_course_certificate', kwargs={'course_slug': course.slug})
                certificate_id = cert.accredible_certificate_id or ''

        result = {
            'score': round(score, 1),
            'passed': passed,
            'correct': correct,
            'total': total,
            'certificate_available': certificate_available,
            'certificate_url': certificate_url,
            'certificate_id': certificate_id,
        }

    tenant = getattr(course, 'tenant', None) or getattr(request, 'tenant', None)
    language_config = get_tenant_language_config(tenant)
    active_language = get_request_language(request, tenant)
    lesson_display = resolve_lesson(lesson, active_language)
    quiz_display = resolve_quiz_display(quiz, active_language)
    resolved_questions = [
        resolve_quiz_question_display(q, active_language) for q in questions
    ]
    all_lessons_list = list(all_lessons)
    lesson_display_titles = build_lesson_title_map(all_lessons_list, active_language)

    return render(request, 'lesson_quiz.html', {
        'course': course,
        'lesson': lesson,
        'lesson_display': lesson_display,
        'quiz': quiz,
        'quiz_display': quiz_display,
        'questions': questions,
        'resolved_questions': resolved_questions,
        'result': result,
        'next_lesson': next_lesson,
        'orphan_lessons': [l for l in all_lessons if not l.module_id],
        'active_language': active_language,
        'enabled_languages': language_config['enabled'],
        'show_language_switcher': show_language_switcher(tenant, language_config),
        'language_labels': LANGUAGE_LABELS,
        'lesson_display_titles': lesson_display_titles,
    })


# ========== CREATOR DASHBOARD VIEWS ==========

@staff_member_required
def creator_dashboard(request):
    """Main creator dashboard"""
    courses = Course.objects.all()
    return render(request, 'creator/dashboard.html', {
        'courses': courses,
    })


@staff_member_required
def course_lessons(request, course_slug):
    """Deprecated creator lessons page — redirect to the cleaner dashboard
    lessons view (dashboard_course_lessons)."""
    response = redirect('dashboard_course_lessons', course_slug=course_slug)
    query_string = request.META.get('QUERY_STRING')
    if query_string:
        response['Location'] += f'?{query_string}'
    return response


@staff_member_required
def add_lesson(request, course_slug):
    """Add new lesson - 3-step flow with video upload and transcription"""
    course = get_object_or_404(course_queryset_for_slug(request, course_slug))

    if request.method == 'POST':
        # Handle form submission
        action = (request.POST.get('action') or 'generate').strip()
        # Prefer the unified video_url field; keep vimeo_url for older form posts.
        video_link = (
            request.POST.get('video_url', '').strip()
            or request.POST.get('vimeo_url', '').strip()
        )
        working_title = request.POST.get('working_title', '').strip()
        rough_notes = request.POST.get('rough_notes', '').strip()
        transcription = request.POST.get('transcription', '').strip()

        if not working_title:
            messages.error(request, 'Please enter a working lesson title.')
            return render(request, 'creator/add_lesson.html', {'course': course})

        video_fields = derive_lesson_video_fields(video_link)

        # Unique slug within this course
        base_slug = generate_slug(working_title) or 'lesson'
        lesson_slug = base_slug
        counter = 1
        while Lesson.objects.filter(course=course, slug=lesson_slug).exists():
            lesson_slug = f'{base_slug}-{counter}'
            counter += 1

        max_order = course.lessons.aggregate(models.Max('order'))['order__max'] or 0

        # Skip AI: save exactly what the user entered and go back to the lesson list.
        if action == 'skip_ai':
            description = rough_notes or working_title
            summary = (rough_notes[:280] if rough_notes else working_title)
            content = {}
            if rough_notes:
                content = {
                    'time': 0,
                    'blocks': [
                        {'id': 'manual1', 'type': 'paragraph', 'data': {'text': rough_notes}},
                    ],
                    'version': '2.28.0',
                }

            lesson = Lesson.objects.create(
                tenant=course.tenant,
                course=course,
                working_title=working_title,
                rough_notes=rough_notes,
                title=working_title,
                slug=lesson_slug,
                description=description,
                order=max_order + 1,
                ai_clean_title=working_title,
                ai_short_summary=summary,
                ai_full_description=description,
                ai_generation_status='approved',
                content=content,
                **video_fields,
            )

            if transcription:
                lesson.transcription = transcription
                lesson.transcription_status = 'completed'
                lesson.save(update_fields=['transcription', 'transcription_status'])

            messages.success(
                request,
                f'Lesson "{working_title}" created without AI. You can edit or reorder it anytime.',
            )
            return redirect('course_lessons', course_slug=course_slug)

        # Create lesson draft (AI generation path)
        lesson = Lesson.objects.create(
            tenant=course.tenant,
            course=course,
            working_title=working_title,
            rough_notes=rough_notes,
            title=working_title,  # Temporary
            slug=lesson_slug,
            description='',  # Will be AI-generated
            order=max_order + 1,
            **video_fields,
        )

        # Handle video file upload and transcription (temporary - not saved)
        if 'video_file' in request.FILES:
            video_file = request.FILES['video_file']
            # Don't save video_file to lesson - only use for transcription
            lesson.transcription_status = 'processing'
            lesson.save()

            # Start transcription in background (video will be deleted after)
            def process_transcription():
                import tempfile
                temp_path = None
                try:
                    # Save to temporary file (not in media folder)
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
                        for chunk in video_file.chunks():
                            temp_file.write(chunk)
                        temp_path = temp_file.name

                    # Transcribe from temporary file
                    result = transcribe_video(temp_path)

                    # Update lesson with transcription
                    lesson.transcription_status = 'completed' if result['success'] else 'failed'
                    lesson.transcription = result.get('transcription', '')
                    lesson.transcription_error = result.get('error', '')
                    lesson.save()
                except Exception as e:
                    lesson.transcription_status = 'failed'
                    lesson.transcription_error = str(e)
                    lesson.save()
                finally:
                    # Always delete temporary video file
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except:
                            pass

            # Run transcription in background thread
            thread = threading.Thread(target=process_transcription)
            thread.daemon = True
            thread.start()
        elif transcription:
            # If transcription was manually edited, save it
            lesson.transcription = transcription
            lesson.transcription_status = 'completed'

        lesson.save()
        return redirect('generate_lesson_ai', course_slug=course_slug, lesson_id=lesson.id)

    return render(request, 'creator/add_lesson.html', {
        'course': course,
    })


def _save_lesson_media_and_content(lesson, request):
    """Save video URLs, workbook, resources, and content blocks from POST."""
    lesson.vimeo_url = request.POST.get('vimeo_url', lesson.vimeo_url) or ''
    lesson.google_drive_url = request.POST.get('google_drive_url', lesson.google_drive_url) or ''
    lesson.video_url = request.POST.get('video_url', lesson.video_url) or ''
    lesson.workbook_url = request.POST.get('workbook_url', lesson.workbook_url) or ''
    lesson.resources_url = request.POST.get('resources_url', lesson.resources_url) or ''
    # Student page section toggles (unchecked checkboxes are absent from POST)
    if 'student_sections_form' in request.POST:
        lesson.show_what_youll_learn = request.POST.get('show_what_youll_learn') == 'on'
        lesson.show_lesson_notes = request.POST.get('show_lesson_notes') == 'on'
    # Vimeo: extract ID, use metadata from Verify button if provided
    if lesson.vimeo_url:
        vimeo_id = extract_vimeo_id(lesson.vimeo_url)
        if vimeo_id:
            lesson.vimeo_id = vimeo_id
    thumb = request.POST.get('vimeo_thumbnail')
    if thumb:
        lesson.vimeo_thumbnail = thumb
    dur = request.POST.get('vimeo_duration_seconds')
    if dur:
        try:
            lesson.vimeo_duration_seconds = int(dur)
        except (ValueError, TypeError):
            pass
    # Parse content blocks
    content_raw = request.POST.get('content_blocks', '')
    if content_raw:
        try:
            content_data = json.loads(content_raw)
            if isinstance(content_data, dict) and 'blocks' in content_data:
                lesson.content = content_data
            elif isinstance(content_data, list):
                lesson.content = {'blocks': content_data}
        except json.JSONDecodeError:
            pass


def _resolve_lesson_generation_settings(request, lesson, course):
    """Resolve LessonGenerationSettings precedence: POST form > lesson stored > course blueprint > defaults."""
    blueprint = course.creation_blueprint if isinstance(course.creation_blueprint, dict) else {}
    course_defaults = blueprint.get('generation_settings') if isinstance(blueprint.get('generation_settings'), dict) else {}
    lesson_stored = lesson.generation_settings if isinstance(lesson.generation_settings, dict) else {}
    if request.method == 'POST' and request.POST.get('gen_reading_level') is not None:
        return LessonGenerationSettings.from_dict(_parse_generation_settings(request.POST, prefix='gen_'))
    base = {**course_defaults, **lesson_stored}
    return LessonGenerationSettings.from_dict(base)


@staff_member_required
def generate_lesson_ai(request, course_slug, lesson_id):
    """Generate AI content for lesson"""
    course = get_object_or_404(course_queryset_for_slug(request, course_slug))
    lesson = get_object_or_404(Lesson, id=lesson_id, course=course)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'generate':
            if not OPENAI_AVAILABLE:
                messages.error(request, 'OpenAI package is not installed on this server.')
            else:
                api_key = os.getenv('OPENAI_API_KEY')
                if not api_key:
                    messages.error(request, 'OPENAI_API_KEY is not configured.')
                else:
                    settings_obj = _resolve_lesson_generation_settings(request, lesson, course)
                    lesson_title = lesson.working_title or lesson.title or 'Lesson'
                    description_parts = []
                    if lesson.rough_notes:
                        description_parts.append(lesson.rough_notes)
                    if lesson.transcription:
                        description_parts.append(f"Lesson transcript:\n{lesson.transcription}")
                    if not description_parts and lesson.description:
                        description_parts.append(lesson.description)
                    lesson_description = '\n\n'.join(description_parts) or 'No source material provided.'

                    blueprint = course.creation_blueprint if isinstance(course.creation_blueprint, dict) else {}
                    blueprint_context = _blueprint_lesson_context_block(blueprint)

                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=api_key)
                        metadata = generate_ai_lesson_metadata(
                            client=client,
                            lesson_title=lesson_title,
                            lesson_description=lesson_description,
                            course_name=course.name,
                            course_type=course.course_type,
                            tenant=course.tenant,
                            course=course,
                            lesson=lesson,
                            blueprint_context=blueprint_context,
                            settings=settings_obj,
                        )
                        content_sections = generate_ai_lesson_content(
                            client=client,
                            lesson_title=lesson_title,
                            lesson_description=lesson_description,
                            course_name=course.name,
                            course_type=course.course_type,
                            tenant=course.tenant,
                            course=course,
                            lesson=lesson,
                            blueprint_context=blueprint_context,
                            settings=settings_obj,
                        )

                        lesson.ai_clean_title = metadata.get('clean_title') or lesson_title
                        lesson.ai_short_summary = metadata.get('short_summary', '')
                        lesson.ai_full_description = metadata.get('full_description', '')
                        lesson.ai_outcomes = metadata.get('outcomes', [])
                        lesson.ai_coach_actions = metadata.get('coach_actions', [])
                        if content_sections:
                            lesson.content = create_editorjs_content(content_sections)
                        lesson.generation_settings = settings_obj.to_dict()
                        lesson.ai_generation_status = 'generated'
                        lesson.save()

                        # Match the bulk pipeline: also generate a hero image
                        # when the settings flag is on. Non-blocking — never raises.
                        if getattr(settings_obj, 'generate_image', True):
                            generate_ai_lesson_image(client, lesson, settings_obj)

                        # Narrate the fresh content in the background.
                        generate_lesson_audio_async(lesson)

                        messages.success(request, 'AI content generated.')
                    except Exception as e:
                        messages.error(request, f'AI generation failed: {e}')

        elif action == 'regenerate_image':
            if not OPENAI_AVAILABLE:
                messages.error(request, 'OpenAI package is not installed on this server.')
            else:
                api_key = os.getenv('OPENAI_API_KEY')
                if not api_key:
                    messages.error(request, 'OPENAI_API_KEY is not configured.')
                else:
                    settings_obj = _resolve_lesson_generation_settings(request, lesson, course)
                    try:
                        from openai import OpenAI
                        client = OpenAI(api_key=api_key)
                        new_url = generate_ai_lesson_image(client, lesson, settings_obj)
                        if new_url:
                            messages.success(request, 'Hero image regenerated.')
                        else:
                            messages.error(request, 'Hero image generation failed. Check server logs and Cloudinary config.')
                    except Exception as e:
                        messages.error(request, f'Hero image generation failed: {e}')

        elif action == 'regenerate_audio':
            if not OPENAI_AVAILABLE:
                messages.error(request, 'OpenAI package is not installed on this server.')
            elif not os.getenv('OPENAI_API_KEY'):
                messages.error(request, 'OPENAI_API_KEY is not configured.')
            else:
                generate_lesson_audio_async(lesson)
                messages.success(request, 'Audio narration is being generated in the background. Refresh in a minute to hear it.')

        elif action == 'upload_image':
            image_file = request.FILES.get('hero_image_file')
            if not image_file:
                messages.error(request, 'Please choose an image file to upload.')
            elif not image_file.content_type.startswith('image/'):
                messages.error(request, 'That file is not an image. Please upload a JPG, PNG, or WEBP.')
            elif image_file.size > 10 * 1024 * 1024:
                messages.error(request, 'Image is too large. Please upload a file under 10 MB.')
            else:
                new_url = upload_lesson_hero_image(lesson, image_file)
                if new_url:
                    messages.success(request, 'Hero image uploaded.')
                else:
                    messages.error(request, 'Hero image upload failed. Check Cloudinary config and try again.')

        elif action == 'delete_image':
            if delete_lesson_hero_image(lesson):
                messages.success(request, 'Hero image removed.')
            else:
                messages.info(request, 'There was no hero image to remove.')

        elif action == 'approve':
            # Save video & links from form (in case not saved via Edit first)
            _save_lesson_media_and_content(lesson, request)
            # Approve and finalize lesson
            lesson.title = lesson.ai_clean_title or lesson.working_title
            lesson.description = lesson.ai_full_description
            lesson.slug = generate_slug(lesson.title)
            lesson.ai_generation_status = 'approved'
            lesson.save()

            return redirect('course_lessons', course_slug=course_slug)

        elif action == 'edit':
            # Update with manual edits
            lesson.ai_clean_title = request.POST.get('clean_title', lesson.ai_clean_title)
            lesson.ai_short_summary = request.POST.get('short_summary', lesson.ai_short_summary)
            lesson.ai_full_description = request.POST.get('full_description', lesson.ai_full_description)

            # Parse outcomes
            outcomes_text = request.POST.get('outcomes', '')
            if outcomes_text:
                lesson.ai_outcomes = [o.strip() for o in outcomes_text.split('\n') if o.strip()]

            # Parse coach actions
            coach_text = request.POST.get('coach_actions', '')
            if coach_text:
                lesson.ai_coach_actions = [a.strip() for a in coach_text.split('\n') if a.strip()]

            _save_lesson_media_and_content(lesson, request)
            lesson.save()

        elif action == 'improve_description':
            current_text = request.POST.get('full_description', lesson.ai_full_description or lesson.description or '')
            lesson.ai_full_description = improve_ai_full_description(lesson, current_text)
            if lesson.ai_generation_status == 'pending':
                lesson.ai_generation_status = 'generated'
            lesson.save(update_fields=['ai_full_description', 'ai_generation_status'])
            messages.success(request, 'Full lesson description improved with AI.')

        elif action == 'generate_translation':
            language_code = normalize_language_code(request.POST.get('translation_language'))
            tenant = course.tenant
            enabled = get_translation_languages_for_tenant(tenant)
            if language_code not in enabled:
                messages.error(request, 'That language is not enabled for this tenant.')
            elif not os.getenv('OPENAI_API_KEY'):
                messages.error(request, 'OPENAI_API_KEY is not configured.')
            else:
                try:
                    from myApp.utils.translation import generate_lesson_translation
                    generate_lesson_translation(lesson, language_code)
                    messages.success(
                        request,
                        f'{get_language_label(language_code)} draft translation generated. Review and publish when ready.',
                    )
                except Exception as e:
                    messages.error(request, f'Translation failed: {e}')

        elif action == 'edit_translation':
            language_code = (request.POST.get('translation_language') or '').strip().lower()
            if not language_code:
                messages.error(request, 'Missing translation language.')
            else:
                translation, _ = LessonTranslation.objects.get_or_create(
                    lesson=lesson,
                    language_code=language_code,
                )
                translation.title = request.POST.get('translation_title', translation.title)
                translation.ai_clean_title = request.POST.get('translation_clean_title', translation.ai_clean_title)
                translation.ai_short_summary = request.POST.get('translation_short_summary', translation.ai_short_summary)
                translation.ai_full_description = request.POST.get('translation_full_description', translation.ai_full_description)
                translation.description = translation.ai_full_description
                outcomes_text = request.POST.get('translation_outcomes', '')
                if outcomes_text:
                    translation.ai_outcomes = [o.strip() for o in outcomes_text.split('\n') if o.strip()]
                coach_text = request.POST.get('translation_coach_actions', '')
                if coach_text:
                    translation.ai_coach_actions = [a.strip() for a in coach_text.split('\n') if a.strip()]
                content_raw = request.POST.get('translation_content_blocks', '')
                if content_raw:
                    try:
                        content_data = json.loads(content_raw)
                        if isinstance(content_data, dict) and 'blocks' in content_data:
                            translation.content = content_data
                        elif isinstance(content_data, list):
                            translation.content = {'blocks': content_data}
                    except json.JSONDecodeError:
                        pass
                translation.status = 'draft'
                translation.save()
                messages.success(request, f'{get_language_label(language_code)} translation saved.')

        elif action == 'approve_translation':
            language_code = normalize_language_code(request.POST.get('translation_language'))
            if not language_code:
                messages.error(request, 'Missing translation language.')
            else:
                translation, _ = LessonTranslation.objects.get_or_create(
                    lesson=lesson,
                    language_code=language_code,
                )
                translation.title = request.POST.get('translation_title', translation.title or translation.ai_clean_title)
                translation.ai_clean_title = request.POST.get('translation_clean_title', translation.ai_clean_title or translation.title)
                translation.ai_short_summary = request.POST.get('translation_short_summary', translation.ai_short_summary)
                translation.ai_full_description = request.POST.get('translation_full_description', translation.ai_full_description)
                translation.description = translation.ai_full_description
                outcomes_text = request.POST.get('translation_outcomes', '')
                if outcomes_text:
                    translation.ai_outcomes = [o.strip() for o in outcomes_text.split('\n') if o.strip()]
                coach_text = request.POST.get('translation_coach_actions', '')
                if coach_text:
                    translation.ai_coach_actions = [a.strip() for a in coach_text.split('\n') if a.strip()]
                content_raw = request.POST.get('translation_content_blocks', '')
                if content_raw:
                    try:
                        content_data = json.loads(content_raw)
                        if isinstance(content_data, dict) and 'blocks' in content_data:
                            translation.content = content_data
                        elif isinstance(content_data, list):
                            translation.content = {'blocks': content_data}
                    except json.JSONDecodeError:
                        pass
                translation.save()
                from myApp.utils.translation import publish_lesson_translation
                publish_lesson_translation(lesson, language_code)
                messages.success(request, f'{get_language_label(language_code)} translation published.')

    # Content for JSON textarea (pass dict for json_script)
    content_data = lesson.content if (lesson.content and isinstance(lesson.content, dict)) else {'blocks': []}
    if 'blocks' not in content_data:
        content_data = {'blocks': []}

    panel_settings = _resolve_lesson_generation_settings(request, lesson, course)

    tenant = course.tenant
    translation_languages = get_translation_languages_for_tenant(tenant)
    active_translation_lang = (request.GET.get('translation_lang') or '').strip().lower()
    if active_translation_lang not in translation_languages:
        active_translation_lang = translation_languages[0] if translation_languages else ''
    lesson_translations = {
        t.language_code: t for t in lesson.translations.all()
    }
    active_translation = lesson_translations.get(active_translation_lang)
    translation_content_data = (
        active_translation.content
        if active_translation and isinstance(active_translation.content, dict)
        else {'blocks': []}
    )
    if 'blocks' not in translation_content_data:
        translation_content_data = {'blocks': []}

    return render(request, 'creator/generate_lesson_ai.html', {
        'course': course,
        'lesson': lesson,
        'content_data': content_data,
        'gen_settings': panel_settings,
        'reading_level_choices': READING_LEVEL_CHOICES,
        'length_choices': LENGTH_CHOICES,
        'depth_choices': DEPTH_CHOICES,
        'translation_languages': translation_languages,
        'active_translation_lang': active_translation_lang,
        'active_translation': active_translation,
        'translation_content_data': translation_content_data,
        'lesson_translations': lesson_translations,
        'language_labels': LANGUAGE_LABELS,
    })


@require_http_methods(["POST"])
@staff_member_required
def verify_vimeo_url(request):
    """AJAX endpoint to verify a pasted video link (Vimeo / YouTube / Drive / embed)."""
    video_url = (
        request.POST.get('video_url', '').strip()
        or request.POST.get('vimeo_url', '').strip()
    )
    if not video_url:
        return JsonResponse({'success': False, 'error': 'Paste a video link first.'})

    source = detect_video_source(video_url)
    if source == 'unknown':
        return JsonResponse({
            'success': False,
            'error': 'Could not recognize that link. Use Vimeo, YouTube, Google Drive, or an embed URL.',
        })

    fields = derive_lesson_video_fields(video_url)
    source_labels = {
        'vimeo': 'Vimeo',
        'youtube': 'YouTube',
        'google_drive': 'Google Drive',
        'embed': 'Embed URL',
    }

    title = 'Video recognized'
    thumbnail = ''
    duration = 0
    duration_formatted = ''

    if source == 'vimeo' and fields.get('vimeo_id'):
        vimeo_data = fetch_vimeo_metadata(fields['vimeo_id']) or {}
        title = vimeo_data.get('title') or 'Vimeo video'
        thumbnail = vimeo_data.get('thumbnail') or fields.get('vimeo_thumbnail') or ''
        duration = int(vimeo_data.get('duration') or fields.get('vimeo_duration_seconds') or 0)
        duration_formatted = format_duration(duration)
    elif source == 'youtube':
        yt = re.search(
            r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})',
            video_url,
        )
        yt_id = yt.group(1) if yt else ''
        title = 'YouTube video'
        thumbnail = f'https://img.youtube.com/vi/{yt_id}/hqdefault.jpg' if yt_id else ''
        duration_formatted = 'YouTube'
    elif source == 'google_drive':
        title = 'Google Drive video'
        duration_formatted = 'Google Drive'
    else:
        title = 'Embed URL'
        duration_formatted = 'Embed'

    return JsonResponse({
        'success': True,
        'source': source,
        'source_label': source_labels.get(source, source),
        'vimeo_id': fields.get('vimeo_id', ''),
        'thumbnail': thumbnail,
        'duration': duration,
        'duration_formatted': duration_formatted,
        'title': title,
        'normalized': {
            'video_url': fields.get('video_url', ''),
            'vimeo_url': fields.get('vimeo_url', ''),
            'google_drive_url': fields.get('google_drive_url', ''),
        },
    })


@require_http_methods(["POST"])
@staff_member_required
def upload_video_transcribe(request):
    """AJAX endpoint to upload video and start transcription - video is NOT saved, only used temporarily"""
    if 'video_file' not in request.FILES:
        return JsonResponse({
            'success': False,
            'error': 'No video file provided'
        })

    video_file = request.FILES['video_file']

    # Validate file type
    if not video_file.name.lower().endswith('.mp4'):
        return JsonResponse({
            'success': False,
            'error': 'Please upload an MP4 video file'
        })

    # Validate file size (500MB limit)
    if video_file.size > 500 * 1024 * 1024:
        return JsonResponse({
            'success': False,
            'error': 'File size exceeds 500MB limit'
        })

    # Use system temp directory (not media folder) - will be deleted after transcription
    import tempfile
    temp_path = None

    try:
        # Save to system temporary file (outside media folder)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            for chunk in video_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name

        # Transcribe from temporary file
        result = transcribe_video(temp_path)

        # Always delete temporary video file (we don't save videos)
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

        if result['success']:
            return JsonResponse({
                'success': True,
                'transcription': result['transcription'],
                'status': 'completed'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error', 'Transcription failed')
            })
    except Exception as e:
        # Clean up temp file on error
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@require_http_methods(["POST"])
@staff_member_required
def check_transcription_status(request, lesson_id):
    """AJAX endpoint to check transcription status"""
    lesson = get_object_or_404(Lesson, id=lesson_id)

    return JsonResponse({
        'status': lesson.transcription_status,
        'transcription': lesson.transcription,
        'error': lesson.transcription_error
    })


# ========== HELPER FUNCTIONS ==========

def detect_video_source(url):
    """Classify a pasted video link: vimeo | youtube | google_drive | embed | unknown."""
    raw = (url or '').strip()
    if not raw:
        return 'unknown'
    lower = raw.lower()
    if 'drive.google.com' in lower or 'docs.google.com/file' in lower:
        return 'google_drive'
    if extract_vimeo_id(raw):
        return 'vimeo'
    if re.search(r'(?:youtube\.com|youtu\.be)/', lower):
        return 'youtube'
    if lower.startswith('http://') or lower.startswith('https://'):
        return 'embed'
    return 'unknown'


def derive_lesson_video_fields(video_link):
    """
    Normalize a pasted video link into Lesson field kwargs.
    Supports Vimeo, YouTube, Google Drive, and generic embed URLs.
    """
    link = (video_link or '').strip()
    fields = {
        'video_url': '',
        'vimeo_url': '',
        'vimeo_id': '',
        'vimeo_thumbnail': '',
        'vimeo_duration_seconds': 0,
        'video_duration': 0,
        'google_drive_url': '',
        'google_drive_id': '',
    }
    if not link:
        return fields

    source = detect_video_source(link)

    if source == 'google_drive':
        drive_match = re.search(
            r'(?:drive\.google\.com/(?:file/d/|open\?id=)|docs\.google\.com/file/d/)([a-zA-Z0-9_-]+)',
            link,
            flags=re.IGNORECASE,
        )
        if drive_match:
            drive_id = drive_match.group(1)
            fields['google_drive_id'] = drive_id
            fields['google_drive_url'] = f'https://drive.google.com/file/d/{drive_id}/preview'
        else:
            # Fallback: store as-is so the operator can still open it
            fields['google_drive_url'] = link
        return fields

    if source == 'vimeo':
        vimeo_id = extract_vimeo_id(link)
        fields['vimeo_url'] = link
        fields['vimeo_id'] = vimeo_id or ''
        if vimeo_id:
            vimeo_data = fetch_vimeo_metadata(vimeo_id) or {}
            fields['vimeo_thumbnail'] = vimeo_data.get('thumbnail', '') or ''
            duration = int(vimeo_data.get('duration') or 0)
            if duration > 0:
                fields['vimeo_duration_seconds'] = duration
                fields['video_duration'] = duration // 60
        return fields

    # YouTube + generic embed URLs live on video_url
    fields['video_url'] = link
    return fields


def extract_vimeo_id(url):
    """Extract Vimeo video ID from URL"""
    if not url:
        return None

    # Supports common Vimeo URL shapes:
    # - vimeo.com/123456789
    # - player.vimeo.com/video/123456789
    # - vimeo.com/manage/videos/123456789
    # - vimeo.com/channels/<name>/123456789
    pattern = (
        r'(?:vimeo\.com/(?:video/|channels/[^/]+/|groups/[^/]+/videos/|album/\d+/video/|'
        r'ondemand/[^/]+/|manage/videos/)?|player\.vimeo\.com/video/)(\d+)'
    )
    match = re.search(pattern, str(url).strip())

    if match:
        return match.group(1)
    return None


def fetch_vimeo_metadata(vimeo_id):
    """Fetch metadata from Vimeo API (using oEmbed endpoint)"""
    try:
        oembed_url = f"https://vimeo.com/api/oembed.json?url=https://vimeo.com/{vimeo_id}"
        response = requests.get(oembed_url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            return {
                'title': data.get('title', ''),
                'thumbnail': data.get('thumbnail_url', ''),
                'duration': data.get('duration', 0),
            }
    except Exception as e:
        print(f"Error fetching Vimeo metadata: {e}")

    return {}


def improve_ai_full_description(lesson, current_text=''):
    """Improve and polish the full lesson description using local AI-style rewrite."""
    base = (current_text or '').strip() or (lesson.ai_full_description or '').strip() or (lesson.description or '').strip()
    if not base:
        base = f"This lesson covers {lesson.working_title or lesson.title or 'the topic'} and gives practical guidance."

    topic = (lesson.ai_clean_title or lesson.working_title or lesson.title or 'this lesson').strip()
    # Lightweight enhancement: tighten voice, outcome orientation, and readability.
    improved = (
        f"In this lesson, you will build a practical understanding of {topic}. "
        f"{base}\n\n"
        "You will move from concept to execution with clear examples, guided thinking prompts, and specific actions you can apply immediately. "
        "By the end, you should be able to explain the core idea in your own words and translate it into a repeatable approach."
    )
    return improved.strip()


def generate_slug(text):
    """Generate URL-friendly slug from text"""
    import unicodedata
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def format_duration(seconds):
    """Format seconds as MM:SS"""
    if not seconds:
        return "0:00"
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


# ========== LANGUAGE PREFERENCE ==========

@require_http_methods(["POST"])
@login_required
def set_language_preference(request):
    """Persist student UI language preference."""
    tenant = getattr(request, 'tenant', None)
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

    language = normalize_language_code(data.get('language'))
    config = get_tenant_language_config(tenant)
    if language not in config['enabled']:
        return JsonResponse({'success': False, 'error': 'Language not enabled.'}, status=400)

    set_user_preferred_language(request.user, language)
    request.session['preferred_language'] = language
    response = JsonResponse({'success': True, 'language': language})
    response.set_cookie('lang', language, max_age=60 * 60 * 24 * 365, samesite='Lax')
    return response


# ========== CHATBOT WEBHOOK ==========

@require_http_methods(["POST"])
@login_required
def update_video_progress(request, lesson_id):
    """Update video watch progress for a lesson"""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    progress_tenant = _resolve_progress_tenant(request, lesson)

    try:
        data = json.loads(request.body)
        watch_percentage = float(data.get('watch_percentage', 0))
        timestamp = float(data.get('timestamp', 0))

        # Get or create UserProgress
        user_progress, created = UserProgress.objects.get_or_create(
            tenant=progress_tenant,
            user=request.user,
            lesson=lesson,
            defaults={
                'tenant': progress_tenant,
                'video_watch_percentage': watch_percentage,
                'last_watched_timestamp': timestamp,
                'progress_percentage': int(watch_percentage)
            }
        )

        # Update progress
        if not created:
            user_progress.video_watch_percentage = watch_percentage
            user_progress.last_watched_timestamp = timestamp
            user_progress.progress_percentage = int(watch_percentage)

        # Auto-update status based on watch progress
        user_progress.update_status()

        return JsonResponse({
            'success': True,
            'watch_percentage': user_progress.video_watch_percentage,
            'status': user_progress.status,
            'completed': user_progress.completed
        })
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return JsonResponse({'error': f'Invalid data: {str(e)}'}, status=400)


@require_http_methods(["POST"])
@login_required
def complete_lesson(request, lesson_id):
    """Mark a lesson as complete for the current user.

    If the lesson has a quiz, it must be passed before the lesson can be completed.
    """
    lesson = get_object_or_404(Lesson, id=lesson_id)
    progress_tenant = _resolve_progress_tenant(request, lesson)

    # Check if lesson has a required quiz
    try:
        quiz = lesson.quiz
        if quiz.is_required:
            # Check if user has passed the quiz
            passed_attempt = LessonQuizAttempt.objects.filter(
                user=request.user,
                quiz=quiz,
                passed=True
            ).exists()

            if not passed_attempt:
                return JsonResponse({
                    'success': False,
                    'error': 'You must pass the lesson quiz before completing this lesson.',
                    'quiz_required': True,
                    'quiz_url': f'/courses/{lesson.course.slug}/{lesson.slug}/quiz/'
                }, status=400)
    except LessonQuiz.DoesNotExist:
        # No quiz, proceed with completion
        pass

    # Get or create UserProgress
    user_progress, created = UserProgress.objects.get_or_create(
        tenant=progress_tenant,
        user=request.user,
        lesson=lesson,
        defaults={'tenant': progress_tenant},
    )

    # Mark as completed
    user_progress.completed = True
    user_progress.status = 'completed'
    user_progress.completed_at = datetime.now()
    user_progress.progress_percentage = 100
    user_progress.save()

    cert = _issue_certificate_if_earned(request.user, lesson.course, request=request)
    course_complete = _course_certificate_ready(request.user, lesson.course)
    certificate_url = ''
    certificate_id = ''
    if cert:
        certificate_url = reverse('download_course_certificate', kwargs={'course_slug': lesson.course.slug})
        certificate_id = cert.accredible_certificate_id or ''

    return JsonResponse({
        'success': True,
        'message': 'Lesson marked as complete',
        'lesson_id': lesson_id,
        'course_complete': course_complete,
        'certificate_url': certificate_url,
        'certificate_id': certificate_id,
        'certifications_url': reverse('student_certifications'),
    })


@require_http_methods(["POST"])
@login_required
def toggle_favorite_course(request, course_id):
    """Toggle favorite status for a course"""
    from .models import FavoriteCourse, Course
    course = get_object_or_404(Course, id=course_id)
    user = request.user

    favorite, created = FavoriteCourse.objects.get_or_create(
        user=user,
        course=course,
        defaults={'tenant': course.tenant}
    )

    if not created:
        # Already favorited, remove it
        favorite.delete()
        is_favorited = False
    else:
        # Just favorited
        is_favorited = True

    return JsonResponse({
        'success': True,
        'is_favorited': is_favorited,
        'message': 'Course favorited' if is_favorited else 'Course unfavorited'
    })


@require_http_methods(["POST"])
@login_required
def chatbot_webhook(request):
    """Forward chatbot messages to the appropriate webhook based on lesson"""
    # Default webhook URL
    DEFAULT_WEBHOOK_URL = "https://kane-course-website.fly.dev/webhook/12e91cca-0e58-4769-9f11-68399ec2f970"

    # Lesson-specific webhook URLs
    LESSON_WEBHOOKS = {
        2: "https://kane-course-website.fly.dev/webhook/7d81ca5f-0033-4a9c-8b75-ae44005f8451",
        3: "https://kane-course-website.fly.dev/webhook/258fb5ce-b70f-48a7-b8b6-f6b0449ddbeb",
        4: "https://kane-course-website.fly.dev/webhook/19fd5879-7fc0-437d-9953-65bb70526c0b",
        5: "https://kane-course-website.fly.dev/webhook/bab1f0ef-b5bc-415f-8f73-88cc31c5c75a",
        6: "https://kane-course-website.fly.dev/webhook/6ed2483b-9c8d-4c20-85e4-432fbf033ad8",
        7: "https://kane-course-website.fly.dev/webhook/400f7a4d-3731-4ed0-90f1-35157579c7b0",
        8: "https://kane-course-website.fly.dev/webhook/0b6fee4a-bb9a-46da-831c-7d20ec7dd627",
        9: "https://kane-course-website.fly.dev/webhook/4c79ba33-2660-4816-9526-8e3513aad427",
        10: "https://kane-course-website.fly.dev/webhook/0373896c-d889-4f72-ba42-83ad6857a5e1",
        11: "https://kane-course-website.fly.dev/webhook/a571ba83-d96d-46c0-a88c-71416eda82a3",
        12: "https://kane-course-website.fly.dev/webhook/97427f57-0e89-4da3-846a-1e4453f8a58c",
    }

    try:
        # Get the request data
        data = json.loads(request.body)

        # Ensure we have a Django session and attach its ID
        if not request.session.session_key:
            request.session.save()
        data['session_id'] = request.session.session_key

        # Enrich payload with course/lesson code for downstream processing,
        # e.g. "virtualrockstar_session1"
        lesson_id = data.get('lesson_id')
        if lesson_id:
            try:
                lesson_obj = Lesson.objects.select_related('course').get(id=lesson_id)
                course_slug = (lesson_obj.course.slug or '').replace('-', '').replace(' ', '').lower()
                lesson_slug = (lesson_obj.slug or '').replace('-', '').replace(' ', '').lower()
                if course_slug and lesson_slug:
                    data['course_lesson_code'] = f"{course_slug}_{lesson_slug}"
            except Lesson.DoesNotExist:
                pass

        # Determine which webhook URL to use based on lesson_id
        webhook_url = LESSON_WEBHOOKS.get(lesson_id, DEFAULT_WEBHOOK_URL)

        # Forward to the webhook
        response = requests.post(
            webhook_url,
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )

        # Return the response from the webhook
        # Frontend treats any "error" key as a hard error, so we avoid using that
        # here and always surface the upstream payload as a normal response.
        try:
            upstream_payload = response.json()
        except ValueError:
            upstream_payload = response.text

        # Extract a clean text message for the frontend chat UI.
        message_text = None
        if isinstance(upstream_payload, list) and len(upstream_payload) > 0:
            # Handle list format like [{'output': '...'}]
            first_item = upstream_payload[0]
            if isinstance(first_item, dict):
                message_text = (
                    first_item.get('output')
                    or first_item.get('Output')
                    or first_item.get('message')
                    or first_item.get('Message')
                    or first_item.get('response')
                    or first_item.get('Response')
                    or first_item.get('text')
                    or first_item.get('Text')
                    or first_item.get('answer')
                    or first_item.get('Answer')
                )
            elif isinstance(first_item, str):
                message_text = first_item
        elif isinstance(upstream_payload, dict):
            # Many of your test webhooks wrap like: {"Response": {"output": "..."}}.
            inner = upstream_payload.get('Response', upstream_payload)
            if isinstance(inner, dict):
                message_text = (
                    inner.get('output')
                    or inner.get('Output')
                    or inner.get('message')
                    or inner.get('Message')
                    or inner.get('response')
                    or inner.get('Response')
                    or inner.get('text')
                    or inner.get('Text')
                    or inner.get('answer')
                    or inner.get('Answer')
                )
            else:
                # Try direct keys on upstream_payload
                message_text = (
                    upstream_payload.get('output')
                    or upstream_payload.get('Output')
                    or upstream_payload.get('message')
                    or upstream_payload.get('Message')
                    or upstream_payload.get('response')
                    or upstream_payload.get('Response')
                    or upstream_payload.get('text')
                    or upstream_payload.get('Text')
                    or upstream_payload.get('answer')
                    or upstream_payload.get('Answer')
                )
        if not message_text:
            message_text = str(upstream_payload)

        # Frontend expects `data.response` to be the text to display.
        return JsonResponse({'response': message_text}, status=200)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except requests.RequestException as e:
        return JsonResponse({'error': str(e)}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ========== STUDENT DASHBOARD (CLIENT VIEW) ==========

def student_dashboard(request):
    """Redirect to unified courses hub (same content as /courses/ for logged-in users)."""
    if request.user.is_authenticated:
        return redirect('courses')
    return redirect('login')


@login_required
def student_course_progress(request, course_slug):
    """Detailed progress view for a specific course"""
    course = get_object_or_404(course_queryset_for_slug(request, course_slug))
    user = request.user

    # Check access (CourseAccess or legacy CourseEnrollment)
    from .utils.access import has_course_access
    has_access, access_record, _ = has_course_access(user, course)
    if not has_access:
        messages.error(request, 'You do not have access to this course.')
        return redirect('courses')

    enrollment = CourseEnrollment.objects.filter(user=user, course=course).select_related('course').first()

    # Get all lessons ordered by module, then lesson order.
    lessons = list(
        course.lessons
        .select_related('module')
        .order_by('module__order', 'module_id', 'order', 'id')
    )
    lesson_ids = [l.id for l in lessons]

    # Batch fetch all UserProgress for this course (1 query instead of N)
    progress_by_lesson = {
        p.lesson_id: p
        for p in UserProgress.objects.filter(
            user=user,
            lesson_id__in=lesson_ids
        ).select_related('lesson')
    }

    lesson_progress = []
    for lesson in lessons:
        progress = progress_by_lesson.get(lesson.id)
        lesson_progress.append({
            'lesson': lesson,
            'progress': progress,
            'watch_percentage': progress.video_watch_percentage if progress else 0,
            'status': progress.status if progress else 'not_started',
            'completed': progress.completed if progress else False,
            'last_accessed': progress.last_accessed if progress else None,
        })

    module_sections = []
    module_lookup = {}
    for lp in lesson_progress:
        lesson = lp['lesson']
        module = lesson.module
        module_key = module.id if module else 'ungrouped'
        if module_key not in module_lookup:
            module_lookup[module_key] = {
                'module': module,
                'title': module.name if module else 'Ungrouped Lessons',
                'lessons': [],
            }
            module_sections.append(module_lookup[module_key])
        module_lookup[module_key]['lessons'].append(lp)

    # Calculate overall progress
    total_lessons = len(lessons)
    completed_lessons = sum(1 for lp in lesson_progress if lp['completed'])
    progress_percentage = int((completed_lessons / total_lessons * 100)) if total_lessons > 0 else 0

    # Get exam info
    exam = None
    exam_attempts = []
    try:
        exam = Exam.objects.get(course=course)
        exam_attempts = ExamAttempt.objects.filter(user=user, exam=exam).order_by('-started_at')
    except Exam.DoesNotExist:
        pass

    required_quiz_ids = list(
        LessonQuiz.objects.filter(
            lesson__course=course,
            is_required=True,
        ).values_list('id', flat=True)
    )
    passed_required_quiz_ids = set()
    if required_quiz_ids:
        passed_required_quiz_ids = set(
            LessonQuizAttempt.objects.filter(
                user=user,
                quiz_id__in=required_quiz_ids,
                passed=True,
            ).values_list('quiz_id', flat=True)
        )
    required_quizzes_complete = len(passed_required_quiz_ids) >= len(required_quiz_ids)

    has_passed_exam = any(attempt.passed for attempt in exam_attempts)
    certificate_available = _course_certificate_ready(user, course)

    # Get certification
    try:
        certification = Certification.objects.get(user=user, course=course)
    except Certification.DoesNotExist:
        certification = None

    if certificate_available:
        certification = _auto_issue_course_certificate(
            user=user,
            course=course,
            certification=certification,
            request=request,
        )

    # Get course resources (downloadable SOP materials)
    course_resources = course.resources.all()

    return render(request, 'student/course_progress.html', {
        'course': course,
        'enrollment': enrollment,
        'lesson_progress': lesson_progress,
        'module_sections': module_sections,
        'total_lessons': total_lessons,
        'completed_lessons': completed_lessons,
        'progress_percentage': progress_percentage,
        'exam': exam,
        'exam_attempts': exam_attempts,
        'certification': certification,
        'certificate_available': certificate_available,
        'required_quiz_count': len(required_quiz_ids),
        'passed_required_quiz_count': len(passed_required_quiz_ids),
        'is_exam_available': enrollment.is_exam_available() if enrollment else False,
        'course_resources': course_resources,
    })


@login_required
def student_certifications(request):
    """View all certifications"""
    user = request.user

    finished_course_ids = (
        UserProgress.objects.filter(user=user, completed=True)
        .values_list('lesson__course_id', flat=True)
        .distinct()
    )
    for course in Course.objects.filter(id__in=finished_course_ids).select_related('tenant'):
        _issue_certificate_if_earned(user, course, request=request)

    certifications = Certification.objects.filter(user=user).select_related('course').order_by('-issued_at', '-created_at')

    # Get eligible courses (completed but no certification yet)
    enrollments = CourseEnrollment.objects.filter(user=user).select_related('course')
    eligible_courses = []

    for enrollment in enrollments:
        total_lessons = enrollment.course.lessons.count()
        completed_lessons = UserProgress.objects.filter(
            user=user,
            lesson__course=enrollment.course,
            completed=True
        ).count()

        if completed_lessons >= total_lessons and total_lessons > 0:
            # Check if certification exists
            if not Certification.objects.filter(user=user, course=enrollment.course).exists():
                eligible_courses.append(enrollment.course)

    return render(request, 'student/certifications.html', {
        'certifications': certifications,
        'eligible_courses': eligible_courses,
    })


@staff_member_required
@require_http_methods(["POST"])
def train_lesson_chatbot(request, lesson_id):
    """Mark the per-lesson AI assistant ready from lesson content or pasted transcript."""
    lesson = get_object_or_404(Lesson, id=lesson_id)

    try:
        data = json.loads(request.body) if request.body else {}
        transcript = (data.get('transcript') or '').strip()

        if transcript:
            lesson.transcription = transcript
            lesson.save(update_fields=['transcription'])

        lesson.ai_chatbot_training_status = 'training'
        lesson.save(update_fields=['ai_chatbot_training_status'])

        if mark_lesson_chatbot_ready(lesson):
            return JsonResponse({
                'success': True,
                'message': 'Lesson AI assistant is ready.',
            })

        return JsonResponse({
            'success': False,
            'error': lesson.ai_chatbot_training_error or 'No lesson content to train on.',
        }, status=400)

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        lesson.ai_chatbot_training_status = 'failed'
        lesson.ai_chatbot_training_error = str(e)
        lesson.save(update_fields=['ai_chatbot_training_status', 'ai_chatbot_training_error'])
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def lesson_chatbot(request, lesson_id):
    """Per-lesson AI coach — answers only from this lesson's stored content."""
    lesson = get_object_or_404(Lesson.objects.select_related('course', 'tenant'), id=lesson_id)

    if not lesson.ai_chatbot_enabled or lesson.ai_chatbot_training_status != 'trained':
        return JsonResponse({
            'success': False,
            'error': 'Chatbot is not available for this lesson',
        }, status=400)

    has_access, _, _ = has_course_access(request.user, lesson.course)
    if not has_access:
        return JsonResponse({
            'success': False,
            'error': 'You do not have access to this lesson',
        }, status=403)

    try:
        data = json.loads(request.body)
        user_message = (data.get('message') or '').strip()
        if not user_message:
            return JsonResponse({'success': False, 'error': 'Message is required'}, status=400)

        ai_response = lesson_chatbot_openai_reply(lesson, user_message)
        if not ai_response:
            return JsonResponse({
                'success': False,
                'error': 'The AI assistant did not return a response. Please try again.',
            }, status=500)

        return JsonResponse({'success': True, 'response': ai_response})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ========== TENANT NOTIFICATION DISMISS ==========

@login_required
@require_http_methods(["POST"])
def dismiss_notification(request, delivery_id):
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No tenant context'}, status=400)
    delivery = get_object_or_404(
        TenantNotificationDelivery,
        id=delivery_id,
        tenant=tenant,
    )
    delivery.seen_at = timezone.now()
    body = {}
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        pass
    if body.get('clicked'):
        delivery.clicked_at = timezone.now()
    delivery.save(update_fields=['seen_at', 'clicked_at'])
    return JsonResponse({'success': True})


# ========== UPGRADE CHECKOUT FLOW ==========

@login_required
def upgrade_choose_interval(request, tier_code):
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No tenant context found.')
        return redirect('dashboard_home')

    tier = PricingTier.objects.filter(code=tier_code, is_active=True).first()
    if not tier:
        return render(request, 'upgrade/unavailable.html', {'reason': 'tier_not_found'})

    if tenant.billing_status == 'active' and tenant.stripe_subscription_id:
        return render(request, 'upgrade/already_subscribed.html', {
            'tenant': tenant, 'tier': tier,
        })

    if not tier.stripe_product_id:
        return render(request, 'upgrade/unavailable.html', {
            'reason': 'not_synced', 'tier': tier,
        })

    delivery_id = (request.GET.get('delivery_id') or '').strip()
    if delivery_id:
        delivery = TenantNotificationDelivery.objects.filter(
            id=delivery_id, tenant=tenant,
        ).first()
        if delivery and not delivery.clicked_at:
            delivery.clicked_at = timezone.now()
            delivery.save(update_fields=['clicked_at'])

    yearly_savings = (tier.monthly_cents * 12) - tier.yearly_cents

    return render(request, 'upgrade/choose_interval.html', {
        'tier': tier,
        'tenant': tenant,
        'delivery_id': delivery_id,
        'yearly_savings': yearly_savings,
    })


@login_required
def upgrade_checkout(request, tier_code, interval):
    if interval not in ('monthly', 'yearly'):
        messages.error(request, 'Invalid billing interval.')
        return redirect('dashboard_home')

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No tenant context found.')
        return redirect('dashboard_home')

    tier = PricingTier.objects.filter(code=tier_code, is_active=True).first()
    if not tier:
        return render(request, 'upgrade/unavailable.html', {
            'reason': 'tier_not_found',
        })

    if tenant.billing_status == 'active' and tenant.stripe_subscription_id:
        return render(request, 'upgrade/already_subscribed.html', {
            'tenant': tenant,
            'tier': tier,
        })

    if not tier.stripe_product_id:
        return render(request, 'upgrade/unavailable.html', {
            'reason': 'not_synced',
            'tier': tier,
        })

    if not _stripe_client_configured():
        messages.error(request, 'Stripe is not configured.')
        return redirect('dashboard_home')

    recurring_price_id = tier.stripe_price_monthly_id if interval == 'monthly' else tier.stripe_price_yearly_id
    if not recurring_price_id:
        return render(request, 'upgrade/unavailable.html', {
            'reason': 'not_synced',
            'tier': tier,
        })

    line_items = [{'price': recurring_price_id, 'quantity': 1}]
    if tier.charge_setup_fee and tier.stripe_price_setup_id:
        line_items.append({'price': tier.stripe_price_setup_id, 'quantity': 1})

    delivery_id = (request.GET.get('delivery_id') or '').strip()
    if delivery_id:
        delivery = TenantNotificationDelivery.objects.filter(
            id=delivery_id, tenant=tenant,
        ).first()
        if delivery and not delivery.clicked_at:
            delivery.clicked_at = timezone.now()
            delivery.save(update_fields=['clicked_at'])

    success_url = f"{request.scheme}://{request.get_host()}/upgrade/success/?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = request.META.get('HTTP_REFERER') or f"{request.scheme}://{request.get_host()}/dashboard/"

    metadata = {
        'tenant_id': str(tenant.id),
        'tier_code': tier.code,
        'interval': interval,
        'flow': 'tier_upgrade',
    }
    if delivery_id:
        metadata['notification_delivery_id'] = delivery_id

    session_kwargs = {
        'mode': 'subscription',
        'payment_method_types': ['card'],
        'line_items': line_items,
        'success_url': success_url,
        'cancel_url': cancel_url,
        'metadata': metadata,
        'client_reference_id': str(tenant.id),
    }
    if tenant.stripe_customer_id:
        session_kwargs['customer'] = tenant.stripe_customer_id
    else:
        admin_membership = TenantMembership.objects.filter(
            tenant=tenant, role='tenant_admin', is_active=True,
        ).select_related('user').first()
        if admin_membership and admin_membership.user.email:
            session_kwargs['customer_email'] = admin_membership.user.email

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
        response = redirect(session.url, permanent=False)
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response
    except Exception as exc:
        messages.error(request, f'Unable to create checkout session: {exc}')
        return redirect('dashboard_billing')


@login_required
@never_cache
def upgrade_success(request):
    if not _stripe_client_configured():
        messages.error(request, 'Stripe is not configured.')
        return redirect('dashboard_home')

    session_id = (request.GET.get('session_id') or '').strip()
    if not session_id:
        messages.error(request, 'Missing checkout session.')
        return redirect('dashboard_home')

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No tenant context found.')
        return redirect('dashboard_home')

    try:
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=['subscription', 'line_items'],
        )
    except Exception as exc:
        messages.error(request, f'Unable to verify checkout: {exc}')
        return redirect('dashboard_billing')

    session_tenant_id = (session.metadata or {}).get('tenant_id') or session.client_reference_id
    if str(tenant.id) != str(session_tenant_id):
        messages.error(request, 'This checkout session does not belong to your account.')
        return redirect('dashboard_home')

    tier_code = (session.metadata or {}).get('tier_code', '')
    tier = PricingTier.objects.filter(code=tier_code).first()
    interval = (session.metadata or {}).get('interval', 'monthly')

    subscription = session.subscription
    next_billing_date = None
    if subscription and hasattr(subscription, 'current_period_end'):
        next_billing_date = datetime.fromtimestamp(
            subscription.current_period_end, tz=timezone.utc,
        )

    setup_fee_paid = False
    recurring_amount = 0
    if session.line_items and session.line_items.data:
        for item in session.line_items.data:
            price = item.get('price', {}) if isinstance(item, dict) else getattr(item, 'price', None)
            if price:
                recurring_obj = getattr(price, 'recurring', None) or (price.get('recurring') if isinstance(price, dict) else None)
                if not recurring_obj:
                    setup_fee_paid = True
                else:
                    amount = getattr(price, 'unit_amount', 0) or (price.get('unit_amount', 0) if isinstance(price, dict) else 0)
                    recurring_amount = amount

    if tenant.billing_status != 'active' and session.payment_status == 'paid':
        _activate_tier_upgrade(session)

    return render(request, 'upgrade/success.html', {
        'tier': tier,
        'interval': interval,
        'setup_fee_paid': setup_fee_paid,
        'recurring_amount': recurring_amount,
        'next_billing_date': next_billing_date,
        'tenant': tenant,
    })


def _activate_tier_upgrade(session):
    """Activate a tier upgrade from a completed checkout session.
    Works with both Stripe API objects (attribute access) and webhook dicts."""
    def _get(obj, key, default=''):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    metadata = _get(session, 'metadata') or {}
    if _get(metadata, 'flow') != 'tier_upgrade':
        return None

    tenant_id = _get(metadata, 'tenant_id') or _get(session, 'client_reference_id')
    tenant = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None
    if not tenant:
        return None

    tier_code = _get(metadata, 'tier_code', '')
    subscription_id = _get(session, 'subscription')
    if hasattr(subscription_id, 'id'):
        subscription_id = subscription_id.id
    customer_id = _get(session, 'customer')
    if hasattr(customer_id, 'id'):
        customer_id = customer_id.id

    update_fields = ['plan_code', 'billing_status', 'updated_at']
    tenant.plan_code = tier_code
    tenant.billing_status = 'active'
    if subscription_id:
        tenant.stripe_subscription_id = subscription_id
        update_fields.append('stripe_subscription_id')
    if customer_id and not tenant.stripe_customer_id:
        tenant.stripe_customer_id = customer_id
        update_fields.append('stripe_customer_id')
    tenant.save(update_fields=update_fields)
    return tenant


# ========== SETUP FEE CHECKOUT FLOW ==========

@login_required
def setup_fee_checkout(request, tier_code):
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No tenant context found.')
        return redirect('dashboard_home')

    if tenant.setup_fee_paid:
        messages.info(request, 'Your setup fee has already been paid.')
        return redirect('dashboard_home')

    tier = PricingTier.objects.filter(code=tier_code, is_active=True).first()
    if not tier:
        return render(request, 'upgrade/unavailable.html', {'reason': 'tier_not_found'})

    if not tier.stripe_price_setup_id:
        return render(request, 'upgrade/unavailable.html', {
            'reason': 'not_synced', 'tier': tier,
        })

    if not _stripe_client_configured():
        messages.error(request, 'Stripe is not configured.')
        return redirect('dashboard_home')

    delivery_id = (request.GET.get('delivery_id') or '').strip()
    if delivery_id:
        delivery = TenantNotificationDelivery.objects.filter(
            id=delivery_id, tenant=tenant,
        ).first()
        if delivery and not delivery.clicked_at:
            delivery.clicked_at = timezone.now()
            delivery.save(update_fields=['clicked_at'])

    success_url = f"{request.scheme}://{request.get_host()}/setup-fee/success/?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = request.META.get('HTTP_REFERER') or f"{request.scheme}://{request.get_host()}/dashboard/"

    metadata = {
        'tenant_id': str(tenant.id),
        'tier_code': tier.code,
        'flow': 'setup_fee',
    }
    if delivery_id:
        metadata['notification_delivery_id'] = delivery_id

    session_kwargs = {
        'mode': 'payment',
        'payment_method_types': ['card'],
        'line_items': [{'price': tier.stripe_price_setup_id, 'quantity': 1}],
        'success_url': success_url,
        'cancel_url': cancel_url,
        'metadata': metadata,
        'client_reference_id': str(tenant.id),
    }
    if tenant.stripe_customer_id:
        session_kwargs['customer'] = tenant.stripe_customer_id
    else:
        admin_membership = TenantMembership.objects.filter(
            tenant=tenant, role='tenant_admin', is_active=True,
        ).select_related('user').first()
        if admin_membership and admin_membership.user.email:
            session_kwargs['customer_email'] = admin_membership.user.email

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
        response = redirect(session.url, permanent=False)
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response
    except Exception as exc:
        messages.error(request, f'Unable to create checkout session: {exc}')
        return redirect('dashboard_billing')


@login_required
@never_cache
def setup_fee_success(request):
    if not _stripe_client_configured():
        messages.error(request, 'Stripe is not configured.')
        return redirect('dashboard_home')

    session_id = (request.GET.get('session_id') or '').strip()
    if not session_id:
        messages.error(request, 'Missing checkout session.')
        return redirect('dashboard_home')

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        messages.error(request, 'No tenant context found.')
        return redirect('dashboard_home')

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as exc:
        messages.error(request, f'Unable to verify checkout: {exc}')
        return redirect('dashboard_billing')

    session_tenant_id = (session.metadata or {}).get('tenant_id') or session.client_reference_id
    if str(tenant.id) != str(session_tenant_id):
        messages.error(request, 'This checkout session does not belong to your account.')
        return redirect('dashboard_home')

    tier_code = (session.metadata or {}).get('tier_code', '')
    tier = PricingTier.objects.filter(code=tier_code).first()

    if not tenant.setup_fee_paid and session.payment_status == 'paid':
        _activate_setup_fee_payment(session)
        tenant.refresh_from_db()

    return render(request, 'upgrade/setup_fee_success.html', {
        'tier': tier,
        'tenant': tenant,
    })


def _activate_setup_fee_payment(session):
    """Mark a tenant's setup fee as paid from a completed checkout session."""
    def _get(obj, key, default=''):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    metadata = _get(session, 'metadata') or {}
    if _get(metadata, 'flow') != 'setup_fee':
        return None

    tenant_id = _get(metadata, 'tenant_id') or _get(session, 'client_reference_id')
    tenant = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None
    if not tenant:
        return None

    customer_id = _get(session, 'customer')
    if hasattr(customer_id, 'id'):
        customer_id = customer_id.id

    update_fields = ['setup_fee_paid', 'updated_at']
    tenant.setup_fee_paid = True
    if customer_id and not tenant.stripe_customer_id:
        tenant.stripe_customer_id = customer_id
        update_fields.append('stripe_customer_id')
    tenant.save(update_fields=update_fields)
    return tenant


@require_http_methods(["POST"])
@login_required
def toggle_theme(request):
    """Toggle user's theme preference between dark and light."""
    from .models import TenantMembership
    from .utils.branding import get_tenant_branding
    from .utils.tenancy import resolve_request_tenant

    tenant = resolve_request_tenant(request)
    membership = None
    if tenant:
        membership = TenantMembership.objects.filter(
            tenant=tenant, user=request.user, is_active=True,
        ).first()

    tenant_default = get_tenant_branding(tenant).get('theme_mode', 'light')

    # Use whichever stored preference applies, falling back to the tenant default.
    current = membership.theme_preference if membership and membership.theme_preference \
        else request.session.get('theme_preference') or tenant_default
    new_theme = 'light' if current == 'dark' else 'dark'

    if membership:
        # Tenant members persist their preference on the membership row.
        membership.theme_preference = new_theme
        membership.save(update_fields=['theme_preference'])
    # Always mirror to the session too. The context processor reads membership
    # first, then session; mirroring guarantees the choice survives reloads even
    # when the next request resolves no tenant (e.g. superadmins toggling between
    # the global console and tenant-scoped pages).
    request.session['theme_preference'] = new_theme

    return JsonResponse({'success': True, 'theme': new_theme})
