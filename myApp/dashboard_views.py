from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Q
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
import json
import re
import requests
import csv
import io
import os
import uuid
import threading
from urllib.parse import urlparse
from decimal import Decimal
import stripe
from django.utils import timezone
from PIL import Image
try:
    import cloudinary.uploader as cloudinary_uploader
    CLOUDINARY_UPLOAD_AVAILABLE = True
except ImportError:
    CLOUDINARY_UPLOAD_AVAILABLE = False
try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
from .models import (
    Course,
    CourseResource,
    Lesson,
    Module,
    UserProgress,
    CourseEnrollment,
    Exam,
    ExamQuestion,
    CourseAccess,
    ExamAttempt,
    Certification,
    LessonQuiz,
    LessonQuizAttempt,
    LessonQuizQuestion,
    Bundle,
    BundlePurchase,
    Cohort,
    CohortMember,
    TenantConfig,
    Tenant,
    TenantMembership,
    TenantDomain,
    AIUsageLog,
)
from django.contrib import messages
from django.core.cache import cache
from django.db import models
from django.contrib.auth.models import User
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from .utils.tenancy import get_default_tenant
from .utils.domains import normalize_domain, ensure_temporary_domain, get_platform_base_domain, get_tenant_public_home_url
from .utils.branding import get_tenant_branding, ensure_tenant_branding

# Tenant admins should use app login, not Django admin login.
staff_member_required = user_passes_test(
    lambda u: u.is_authenticated and u.is_staff,
    login_url='login'
)

COURSEFORGE_FORMAT_CHOICES = (
    ('mini_course', 'Mini Course (20–60 min total)'),
    ('masterclass', 'Masterclass (2–24 hours)'),
    ('challenge_3', 'Challenge — 3 days'),
    ('challenge_5', 'Challenge — 5 days'),
    ('challenge_7', 'Challenge — 7 days'),
    ('summit', 'Summit (1–3 days)'),
    ('certification_soon', 'Certification (coming soon)'),
    ('retreat_soon', 'Retreat (coming soon)'),
)

COURSEFORGE_LEVEL_CHOICES = (
    ('beginner', 'Beginner'),
    ('intermediate', 'Intermediate'),
    ('advanced', 'Advanced'),
)


def _parse_course_creation_blueprint(post):
    """Build creation_blueprint dict from POST (CourseForge wizard)."""
    raw_steps = (post.get('cf_framework_steps') or '').replace('\r\n', '\n')
    framework_steps = [s.strip() for s in raw_steps.split('\n') if s.strip()]
    raw_outcomes = (post.get('cf_outcomes') or '').replace('\r\n', '\n')
    outcomes = [s.strip() for s in raw_outcomes.split('\n') if s.strip()]
    fmt = (post.get('cf_course_format') or '').strip()
    valid_formats = {c[0] for c in COURSEFORGE_FORMAT_CHOICES}
    if fmt not in valid_formats:
        fmt = 'masterclass'
    level = (post.get('cf_knowledge_level') or '').strip()
    valid_levels = {c[0] for c in COURSEFORGE_LEVEL_CHOICES}
    if level not in valid_levels:
        level = 'beginner'
    total_raw = (post.get('cf_total_classes') or '').strip()
    try:
        total_classes = max(1, min(120, int(total_raw)))
    except ValueError:
        total_classes = 12
    return {
        'blueprint_version': 1,
        'topic': (post.get('cf_topic') or '').strip(),
        'target_audience': (post.get('cf_target_audience') or '').strip(),
        'learning_goals': (post.get('cf_learning_goals') or '').strip(),
        'required_knowledge': (post.get('cf_required_knowledge') or '').strip(),
        'course_format': fmt,
        'class_length': (post.get('cf_class_length') or '').strip(),
        'total_classes': total_classes,
        'knowledge_level': level,
        'writing_sample': (post.get('cf_writing_sample') or '').strip(),
        'reference_content': (post.get('cf_reference_content') or '').strip(),
        'course_promise': (post.get('cf_course_promise') or '').strip(),
        'framework_title': (post.get('cf_framework_title') or '').strip(),
        'framework_steps': framework_steps,
        'framework_generate_auto': post.get('cf_framework_auto') == 'on',
        'outcomes': outcomes,
    }


def _parse_seed_lessons(raw_json):
    """Parse optional per-lesson source inputs from step 6 JSON."""
    if not raw_json:
        return []
    try:
        parsed = json.loads(raw_json)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    cleaned = []
    for item in parsed[:60]:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        source = str(item.get('source') or '').strip()
        video_link = str(item.get('video_link') or '').strip()
        if not title or not source:
            continue
        cleaned.append({
            'title': title[:200],
            'source': source[:20000],
            'video_link': video_link[:1000],
        })
    return cleaned


def _validate_blueprint_for_ai(bp):
    """Return list of user-facing error strings when AI generation is requested."""
    errs = []
    if not bp.get('topic'):
        errs.append('Course topic is required for AI generation (Step 1).')
    if not bp.get('target_audience'):
        errs.append('Target audience is required (Step 1).')
    if not bp.get('learning_goals'):
        errs.append('High-level learning goals are required (Step 1).')
    if not bp.get('required_knowledge'):
        errs.append('Required prior knowledge is required (Step 1).')
    if not bp.get('class_length'):
        errs.append('Class length is required (Step 1).')
    if not bp.get('course_promise'):
        errs.append('Course promise is required (Step 3).')
    if not bp.get('framework_title'):
        errs.append('Framework title is required (Step 4).')
    if not bp.get('framework_generate_auto') and len(bp.get('framework_steps') or []) < 2:
        errs.append('Add at least two framework steps, or enable “Generate framework steps automatically”.')
    if len(bp.get('outcomes') or []) < 2:
        errs.append('Add at least two learning outcomes (Step 5), each on its own line.')
    return errs


def _compose_description_from_blueprint(bp):
    """Rich text brief for storage + AI (when user leaves full description empty)."""
    parts = []
    if bp.get('topic'):
        parts.append(f"## Subject / topic\n{bp['topic']}")
    if bp.get('target_audience'):
        parts.append(f"## Target audience\n{bp['target_audience']}")
    if bp.get('learning_goals'):
        parts.append(f"## High-level learning goals\n{bp['learning_goals']}")
    if bp.get('required_knowledge'):
        parts.append(f"## Required knowledge before starting\n{bp['required_knowledge']}")
    fmt_labels = dict(COURSEFORGE_FORMAT_CHOICES)
    parts.append(
        f"## Format & pacing\n"
        f"- Format: {fmt_labels.get(bp.get('course_format'), bp.get('course_format', ''))}\n"
        f"- Typical class length: {bp.get('class_length', '')}\n"
        f"- Target number of classes/lessons: {bp.get('total_classes', '')}\n"
        f"- Knowledge level: {bp.get('knowledge_level', '')}"
    )
    if bp.get('writing_sample'):
        parts.append(f"## Writing style reference (tone only)\n{bp['writing_sample'][:8000]}")
    if bp.get('reference_content'):
        parts.append(f"## Existing material to incorporate\n{bp['reference_content'][:12000]}")
    if bp.get('course_promise'):
        parts.append(f"## Course promise (transformation + timeframe)\n{bp['course_promise']}")
    ft = bp.get('framework_title') or ''
    if bp.get('framework_generate_auto'):
        parts.append(f"## Teaching framework\nTitle: {ft}\n(Steps should be invented to match this system name.)")
    elif bp.get('framework_steps'):
        steps = '\n'.join(f"{i + 1}. {s}" for i, s in enumerate(bp['framework_steps']))
        parts.append(f"## Teaching framework\n**{ft}**\n{steps}")
    if bp.get('outcomes'):
        ol = '\n'.join(f"- {o}" for o in bp['outcomes'])
        parts.append(f"## Measurable learning outcomes\n{ol}")
    return '\n\n'.join(parts)


def _default_short_description_from_blueprint(bp):
    promise = (bp.get('course_promise') or '')[:900]
    if promise:
        return promise
    goals = (bp.get('learning_goals') or '')[:900]
    return goals or (bp.get('topic') or 'New course')[:900]


def _blueprint_lesson_context_block(bp):
    """Short block appended to per-lesson AI prompts."""
    if not bp or not isinstance(bp, dict) or not bp.get('topic'):
        return ''
    lines = [
        'CourseForge brief (keep tone and difficulty consistent):',
        f"- Topic: {bp.get('topic', '')}",
        f"- Audience: {bp.get('target_audience', '')}",
        f"- Level: {bp.get('knowledge_level', '')}",
        f"- Promise: {bp.get('course_promise', '')}",
        f"- Prerequisites: {bp.get('required_knowledge', '')}",
    ]
    ws = (bp.get('writing_sample') or '').strip()
    if ws:
        lines.append(f"- Match this voice (tone only, do not copy as lesson facts): {ws[:1200]}")
    ref = (bp.get('reference_content') or '').strip()
    if ref:
        lines.append(f"- Incorporate themes from reference material where relevant: {ref[:2000]}")
    if bp.get('outcomes'):
        lines.append('- Course outcomes: ' + '; '.join(bp['outcomes'][:12]))
    return '\n'.join(lines)


def _blueprint_structure_prompt_section(bp):
    """Extra instructions for module/lesson structure generation."""
    if not bp or not isinstance(bp, dict) or not bp.get('topic'):
        return ''
    fmt_labels = dict(COURSEFORGE_FORMAT_CHOICES)
    fmt = fmt_labels.get(bp.get('course_format'), bp.get('course_format', ''))
    n = bp.get('total_classes') or 12
    n = max(4, min(40, int(n)))
    framework_lines = ''
    if bp.get('framework_generate_auto'):
        framework_lines = (
            f"Teaching system name: \"{bp.get('framework_title', '')}\". "
            "Invent clear, memorable steps for this methodology and align module names and lesson flow with those steps."
        )
    else:
        steps = bp.get('framework_steps') or []
        if steps:
            framework_lines = (
                f"Teaching system: \"{bp.get('framework_title', '')}\" with steps: "
                + '; '.join(steps)
                + ". Module boundaries should reflect this progression."
            )
        else:
            framework_lines = f"Teaching system: \"{bp.get('framework_title', '')}\"."
    return f"""
Additional CourseForge requirements (follow closely):
- Subject: {bp.get('topic', '')}
- Audience: {bp.get('target_audience', '')}
- Learning goals: {bp.get('learning_goals', '')}
- Prior knowledge: {bp.get('required_knowledge', '')}
- Difficulty: {bp.get('knowledge_level', '')}
- Course format: {fmt} — match pacing and depth to this format (e.g. mini-course = tighter, fewer concepts per lesson).
- Aim for approximately {n} lessons total across 3–6 modules (adjust counts to fit the format).
- Typical session length context from author: {bp.get('class_length', '')}
- Transformation promise: {bp.get('course_promise', '')}
- {framework_lines}
- Measurable outcomes (lessons should build toward these): {', '.join(bp.get('outcomes') or [])}
"""


LANDING_HTML_SAMPLE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Your Brand</title>
  <style>
    :root { --bg:#0b1028; --card:#101735; --text:#e8ecff; --muted:#a8b3d8; --accent:#22d3ee; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, Arial, sans-serif; background: linear-gradient(180deg,#0a0f25,#050814); color: var(--text); }
    .wrap { max-width: 960px; margin: 0 auto; padding: 28px 18px 56px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:12px; }
    .brand { display:flex; align-items:center; gap:10px; font-weight:700; letter-spacing:.02em; }
    .brand-logo { width:38px; height:38px; border-radius:10px; object-fit:cover; border:1px solid rgba(255,255,255,.14); background:#0a0f25; }
    .brand-note { font-size:12px; color:#9aa8d8; margin-top:6px; }
    .nav { display:flex; gap:10px; flex-wrap:wrap; }
    .btn { display:inline-block; text-decoration:none; border:1px solid rgba(34,211,238,.45); color:var(--accent); padding:9px 13px; border-radius:10px; font-size:14px; }
    .btn-solid { background: rgba(34,211,238,.14); }
    .hero { margin-top: 42px; background: var(--card); border:1px solid rgba(255,255,255,.08); border-radius:16px; padding:28px; }
    h1 { margin:0 0 12px; font-size:34px; line-height:1.15; }
    p { margin:0; color: var(--muted); line-height:1.65; }
    .cta-row { margin-top:20px; display:flex; gap:10px; flex-wrap:wrap; }
    .grid { margin-top:16px; display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
    .card { background: rgba(255,255,255,.02); border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:14px; }
    .card h3 { margin:0 0 8px; font-size:16px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div class="brand">
          <img class="brand-logo" src="__TENANT_LOGO_URL__" alt="__TENANT_BRAND_NAME__ Logo" />
          <span>__TENANT_BRAND_NAME__ Academy</span>
        </div>
        <div class="brand-note">Set your tenant logo in Branding Settings. This sample auto-uses it.</div>
      </div>
      <div class="nav">
        <a class="btn" href="/login/">Sign in</a>
        <a class="btn btn-solid" href="/register/">Get started</a>
      </div>
    </div>
    <section class="hero">
      <h1>Turn your expertise into a premium learning experience.</h1>
      <p>Launch your academy, onboard students, and sell your programs under your own brand.</p>
      <div class="cta-row">
        <a class="btn btn-solid" href="/register/">Create account</a>
        <a class="btn" href="/courses/">Browse courses</a>
      </div>
      <div class="grid">
        <div class="card"><h3>Structured Programs</h3><p>Organize modules, lessons, and progress in one place.</p></div>
        <div class="card"><h3>Student Payments</h3><p>Accept payments directly with your connected Stripe account.</p></div>
        <div class="card"><h3>Branded Experience</h3><p>Use your own domain and customize copy, logo, and visuals.</p></div>
      </div>
    </section>
  </div>
</body>
</html>
"""

SIGNUP_HTML_SAMPLE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Create your account</title>
  <style>
    body { margin:0; font-family: Inter, Arial, sans-serif; background:#0b1028; color:#e8ecff; }
    .wrap { max-width:560px; margin:40px auto; padding:24px; background:#101735; border:1px solid rgba(255,255,255,.09); border-radius:14px; }
    .brand { display:flex; align-items:center; gap:10px; margin-bottom:12px; }
    .brand-logo { width:36px; height:36px; border-radius:10px; object-fit:cover; border:1px solid rgba(255,255,255,.15); background:#0a0f25; }
    .brand-note { margin:0 0 14px; color:#8fa0d8; font-size:12px; }
    h1 { margin:0 0 8px; font-size:28px; }
    p { margin:0 0 18px; color:#a8b3d8; }
    .field { margin-bottom:12px; }
    label { display:block; margin-bottom:6px; font-size:13px; color:#b9c3e4; }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(255,255,255,.15); background:#0a0f25; color:#fff; }
    button { width:100%; margin-top:8px; padding:10px 12px; border-radius:10px; border:1px solid rgba(34,211,238,.5); background:rgba(34,211,238,.14); color:#22d3ee; font-weight:600; cursor:pointer; }
    .links { margin-top:14px; display:flex; justify-content:space-between; gap:10px; }
    .links a { color:#22d3ee; text-decoration:none; font-size:13px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">
      <img class="brand-logo" src="__TENANT_LOGO_URL__" alt="__TENANT_BRAND_NAME__ Logo" />
      <strong>__TENANT_BRAND_NAME__ Academy</strong>
    </div>
    <p class="brand-note">Set your tenant logo in Branding Settings. This sample auto-uses it.</p>
    <h1>Create account</h1>
    <p>Join and start learning right away.</p>
    <form method="post" action="/register/">
      <div class="field"><label>Username</label><input name="username" required /></div>
      <div class="field"><label>Email</label><input type="email" name="email" /></div>
      <div class="field"><label>Password</label><input type="password" name="password" required /></div>
      <div class="field"><label>Confirm Password</label><input type="password" name="confirm_password" required /></div>
      <button type="submit">Create account</button>
    </form>
    <div class="links">
      <a href="/login/">Already have an account?</a>
      <a href="/courses/">Browse courses</a>
    </div>
  </div>
</body>
</html>
"""

LOGIN_HTML_SAMPLE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Sign in</title>
  <style>
    body { margin:0; font-family: Inter, Arial, sans-serif; background:#0b1028; color:#e8ecff; }
    .wrap { max-width:520px; margin:48px auto; padding:24px; background:#101735; border:1px solid rgba(255,255,255,.09); border-radius:14px; }
    .brand { display:flex; align-items:center; gap:10px; margin-bottom:12px; }
    .brand-logo { width:36px; height:36px; border-radius:10px; object-fit:cover; border:1px solid rgba(255,255,255,.15); background:#0a0f25; }
    .brand-note { margin:0 0 14px; color:#8fa0d8; font-size:12px; }
    h1 { margin:0 0 8px; font-size:28px; }
    p { margin:0 0 18px; color:#a8b3d8; }
    .field { margin-bottom:12px; }
    label { display:block; margin-bottom:6px; font-size:13px; color:#b9c3e4; }
    input { width:100%; padding:10px 12px; border-radius:10px; border:1px solid rgba(255,255,255,.15); background:#0a0f25; color:#fff; }
    button { width:100%; margin-top:8px; padding:10px 12px; border-radius:10px; border:1px solid rgba(34,211,238,.5); background:rgba(34,211,238,.14); color:#22d3ee; font-weight:600; cursor:pointer; }
    .links { margin-top:14px; display:flex; justify-content:space-between; gap:10px; }
    .links a { color:#22d3ee; text-decoration:none; font-size:13px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">
      <img class="brand-logo" src="__TENANT_LOGO_URL__" alt="__TENANT_BRAND_NAME__ Logo" />
      <strong>__TENANT_BRAND_NAME__ Academy</strong>
    </div>
    <p class="brand-note">Set your tenant logo in Branding Settings. This sample auto-uses it.</p>
    <h1>Welcome back</h1>
    <p>Sign in to continue.</p>
    <form method="post" action="/login/">
      <div class="field"><label>Username</label><input name="username" required /></div>
      <div class="field"><label>Password</label><input type="password" name="password" required /></div>
      <button type="submit">Sign in</button>
    </form>
    <div class="links">
      <a href="/register/">Create account</a>
      <a href="/courses/">Browse courses</a>
    </div>
  </div>
</body>
</html>
"""

OPENAI_DEFAULT_RATES_PER_MILLION = {
    'gpt-4o-mini': (Decimal('0.15'), Decimal('0.60')),
}


def _resolve_openai_rates(model_name):
    """Resolve input/output rate per million tokens for a model."""
    normalized = (model_name or 'gpt-4o-mini').upper().replace('-', '_').replace('.', '_')
    env_in = os.getenv(f'OPENAI_RATE_{normalized}_INPUT_PER_MILLION')
    env_out = os.getenv(f'OPENAI_RATE_{normalized}_OUTPUT_PER_MILLION')
    if env_in and env_out:
        try:
            return Decimal(env_in), Decimal(env_out)
        except Exception:
            pass
    return OPENAI_DEFAULT_RATES_PER_MILLION.get(model_name, OPENAI_DEFAULT_RATES_PER_MILLION['gpt-4o-mini'])


def _log_openai_usage(feature, response, tenant=None, course=None, lesson=None, model_name=''):
    """
    Persist per-call OpenAI token usage for exact spend reporting.
    Safe no-op when usage metadata is missing.
    """
    usage = getattr(response, 'usage', None)
    if usage is None:
        return

    prompt_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
    completion_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
    total_tokens = int(getattr(usage, 'total_tokens', prompt_tokens + completion_tokens) or 0)
    if total_tokens <= 0:
        return

    input_rate, output_rate = _resolve_openai_rates(model_name or 'gpt-4o-mini')
    cost_usd = (
        (Decimal(prompt_tokens) / Decimal(1_000_000)) * input_rate
        + (Decimal(completion_tokens) / Decimal(1_000_000)) * output_rate
    )

    AIUsageLog.objects.create(
        tenant=tenant,
        course=course,
        lesson=lesson,
        provider='openai',
        feature=feature,
        model_name=model_name or '',
        request_id=str(getattr(response, 'id', '') or ''),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        input_rate_per_million=input_rate,
        output_rate_per_million=output_rate,
        cost_usd=cost_usd,
    )


def _configure_stripe():
    key = os.getenv('STRIPE_SECRET_KEY', '').strip()
    if not key:
        return False
    stripe.api_key = key
    return True


@login_required(login_url='login')
def dashboard_connect_stripe(request):
    if not request.user.is_staff:
        messages.error(request, 'Only tenant admins can connect Stripe.')
        return redirect('courses')
    tenant = getattr(request, 'tenant', None) or get_default_tenant()
    if tenant is None:
        messages.error(request, 'No tenant context available.')
        return redirect('dashboard_home')
    if not _configure_stripe():
        messages.error(request, 'Stripe is not configured.')
        return redirect('dashboard_domain_settings')
    client_id = os.getenv('STRIPE_CONNECT_CLIENT_ID', '').strip()
    if not client_id:
        messages.error(request, 'Stripe Connect is not configured (missing client ID).')
        return redirect('dashboard_domain_settings')
    redirect_base = os.getenv('STRIPE_CONNECT_REDIRECT_BASE_URL', '').rstrip('/')
    if not redirect_base:
        redirect_base = f"{request.scheme}://{request.get_host()}"
    redirect_uri = f"{redirect_base}/dashboard/payments/stripe/callback/"
    state = f"tenant:{tenant.id}"
    connect_url = (
        "https://connect.stripe.com/oauth/authorize"
        f"?response_type=code&client_id={client_id}"
        f"&scope=read_write&state={state}&redirect_uri={redirect_uri}"
    )
    return redirect(connect_url)


@login_required(login_url='login')
def dashboard_stripe_connect_callback(request):
    if not request.user.is_staff:
        messages.error(request, 'Only tenant admins can complete Stripe connection.')
        return redirect('courses')

    # Resolve tenant from state param first (callback lands on platform domain,
    # so request.tenant is None; state="tenant:<id>" carries the identity).
    tenant = None
    state = (request.GET.get('state') or '').strip()
    if state.startswith('tenant:'):
        try:
            from myApp.models import Tenant as TenantModel
            tenant_id = int(state.split(':', 1)[1])
            tenant = TenantModel.objects.get(id=tenant_id)
        except Exception:
            tenant = None
    if tenant is None:
        tenant = getattr(request, 'tenant', None) or get_default_tenant()
    if tenant is None:
        messages.error(request, 'No tenant context available.')
        return redirect('dashboard_home')

    # Build a URL to redirect back to the tenant's own domain after the flow.
    from myApp.models import TenantDomain
    tenant_domain_obj = TenantDomain.objects.filter(
        tenant=tenant, is_primary=True, is_verified=True
    ).first() or TenantDomain.objects.filter(
        tenant=tenant, is_verified=True
    ).first()
    if tenant_domain_obj:
        tenant_settings_url = f"https://{tenant_domain_obj.domain}/dashboard/payments/settings/"
    else:
        tenant_settings_url = None

    if not _configure_stripe():
        messages.error(request, 'Stripe is not configured.')
        if tenant_settings_url:
            return redirect(tenant_settings_url)
        return redirect('dashboard_domain_settings')

    code = (request.GET.get('code') or '').strip()
    if not code:
        messages.error(request, 'Stripe connection failed or was canceled.')
        if tenant_settings_url:
            return redirect(tenant_settings_url)
        return redirect('dashboard_domain_settings')

    try:
        response = stripe.OAuth.token(grant_type='authorization_code', code=code)
        account_id = response.get('stripe_user_id')
        if not account_id:
            raise ValueError('Missing connected account id.')
        account = stripe.Account.retrieve(account_id)
        charges_enabled = bool(account.get('charges_enabled'))
        details_submitted = bool(account.get('details_submitted'))

        config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
        config.stripe_connect_account_id = account_id
        config.stripe_connect_onboarding_complete = details_submitted
        config.stripe_connect_charges_enabled = charges_enabled
        config.save(update_fields=[
            'stripe_connect_account_id',
            'stripe_connect_onboarding_complete',
            'stripe_connect_charges_enabled',
            'updated_at'
        ])
        if charges_enabled:
            messages.success(request, 'Stripe connected successfully. You can now accept student payments.')
        else:
            messages.warning(request, 'Stripe connected, but payouts/charges are not fully enabled yet. Complete onboarding in Stripe.')
    except Exception as exc:
        messages.error(request, f'Unable to complete Stripe connection: {str(exc)}')

    if tenant_settings_url:
        return redirect(tenant_settings_url)
    return redirect('dashboard_domain_settings')


@login_required(login_url='login')
@require_http_methods(["POST"])
def dashboard_save_stripe_own_keys(request):
    """Save (or clear) tenant's own Stripe API keys for direct-charge mode."""
    if not request.user.is_staff:
        messages.error(request, 'Only tenant admins can configure Stripe.')
        return redirect('courses')
    tenant = _get_dashboard_tenant(request)
    if tenant is None:
        messages.error(request, 'No tenant context available.')
        return redirect('dashboard_domain_settings')

    secret_key = request.POST.get('stripe_own_secret_key', '').strip()
    pub_key = request.POST.get('stripe_own_publishable_key', '').strip()
    webhook_secret = request.POST.get('stripe_own_webhook_secret', '').strip()
    clear = request.POST.get('clear_own_keys') == '1'

    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)

    if clear:
        config.stripe_own_secret_key = ''
        config.stripe_own_publishable_key = ''
        config.stripe_own_webhook_secret = ''
        config.save(update_fields=['stripe_own_secret_key', 'stripe_own_publishable_key', 'stripe_own_webhook_secret', 'updated_at'])
        messages.success(request, 'Own Stripe keys cleared.')
        return redirect('dashboard_domain_settings')

    if not secret_key or not pub_key:
        messages.error(request, 'Secret Key and Publishable Key are required.')
        return redirect('dashboard_domain_settings')
    if not secret_key.startswith('sk_'):
        messages.error(request, 'Secret Key must start with sk_live_ or sk_test_.')
        return redirect('dashboard_domain_settings')
    if not pub_key.startswith('pk_'):
        messages.error(request, 'Publishable Key must start with pk_live_ or pk_test_.')
        return redirect('dashboard_domain_settings')
    if webhook_secret and not webhook_secret.startswith('whsec_'):
        messages.error(request, 'Webhook Secret must start with whsec_.')
        return redirect('dashboard_domain_settings')

    config.stripe_own_secret_key = secret_key
    config.stripe_own_publishable_key = pub_key
    config.stripe_own_webhook_secret = webhook_secret
    config.save(update_fields=['stripe_own_secret_key', 'stripe_own_publishable_key', 'stripe_own_webhook_secret', 'updated_at'])
    messages.success(request, 'Own Stripe keys saved. Students can now pay via your Stripe account.')
    return redirect('dashboard_domain_settings')


@login_required(login_url='login')
def dashboard_billing(request):
    if not request.user.is_staff:
        messages.error(request, 'Only tenant admins can view billing.')
        return redirect('courses')
    tenant = getattr(request, 'tenant', None) or get_default_tenant()
    if tenant is None:
        messages.error(request, 'No tenant context available.')
        return redirect('dashboard_home')
    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    plan_labels = {
        'lean': 'Lean',
        'baseline': 'Baseline',
        'growth': 'Growth',
        'starter': 'Starter',
    }
    return render(request, 'dashboard/billing.html', {
        'tenant': tenant,
        'tenant_config': config,
        'plan_label': plan_labels.get((tenant.plan_code or '').lower(), (tenant.plan_code or 'Starter').title()),
    })


@login_required(login_url='login')
@require_http_methods(["POST"])
def dashboard_billing_portal(request):
    if not request.user.is_staff:
        messages.error(request, 'Only tenant admins can manage billing.')
        return redirect('courses')
    tenant = getattr(request, 'tenant', None) or get_default_tenant()
    if tenant is None:
        messages.error(request, 'No tenant context available.')
        return redirect('dashboard_home')
    if not _configure_stripe():
        messages.error(request, 'Stripe is not configured.')
        return redirect('dashboard_billing')
    if not tenant.stripe_customer_id:
        messages.error(request, 'No Stripe customer record found for this tenant yet.')
        return redirect('dashboard_billing')
    try:
        return_url = f"{request.scheme}://{request.get_host()}/dashboard/billing/"
        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=return_url,
        )
        return redirect(session.url)
    except Exception as exc:
        messages.error(request, f'Unable to open billing portal: {str(exc)}')
        return redirect('dashboard_billing')


def _sanitize_uploaded_html(raw_html):
    """
    Keep tenant custom landing HTML safe enough for admin-uploaded content.
    Removes scripts/iframes/object/embed and strips Django template delimiters.
    """
    if not raw_html:
        return ''
    html = str(raw_html)
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<iframe[\s\S]*?</iframe>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<object[\s\S]*?</object>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<embed[\s\S]*?>', '', html, flags=re.IGNORECASE)
    html = html.replace('{%', '').replace('%}', '').replace('{{', '').replace('}}', '')
    return html.strip()


def _upload_tenant_logo_webp_to_cloudinary(tenant, logo_file):
    """
    Convert uploaded logo to webp and upload to Cloudinary.
    Returns secure URL on success, or empty string.
    """
    if not CLOUDINARY_UPLOAD_AVAILABLE:
        return ''
    if not (os.getenv('CLOUDINARY_CLOUD_NAME') and os.getenv('CLOUDINARY_API_KEY') and os.getenv('CLOUDINARY_API_SECRET')):
        return ''
    if not logo_file:
        return ''
    try:
        image = Image.open(logo_file)
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA')
        if image.mode == 'RGBA':
            # Keep transparency if present.
            converted = image
        else:
            converted = image.convert('RGB')

        out = io.BytesIO()
        converted.save(out, format='WEBP', quality=88, method=6)
        out.seek(0)
        out.name = f"tenant_{tenant.id}_logo.webp"

        result = cloudinary_uploader.upload(
            out,
            folder='courseforge/tenant_logos',
            public_id=f"tenant_{tenant.id}_logo",
            overwrite=True,
            resource_type='image',
            format='webp',
        )
        return (result.get('secure_url') or '').strip()
    except Exception:
        return ''


def _upload_tenant_certificate_template_to_cloudinary(tenant, template_file):
    """
    Upload tenant certificate PDF template to Cloudinary and return secure URL.
    """
    if not CLOUDINARY_UPLOAD_AVAILABLE:
        return ''
    if not (os.getenv('CLOUDINARY_CLOUD_NAME') and os.getenv('CLOUDINARY_API_KEY') and os.getenv('CLOUDINARY_API_SECRET')):
        return ''
    if not template_file:
        return ''
    try:
        name = (getattr(template_file, 'name', '') or '').lower()
        if not name.endswith('.pdf'):
            return ''

        result = cloudinary_uploader.upload(
            template_file,
            folder='courseforge/certificate_templates',
            public_id=f"tenant_{tenant.id}_certificate_template_{uuid.uuid4().hex[:10]}",
            overwrite=True,
            resource_type='raw',
            format='pdf',
        )
        return (result.get('secure_url') or '').strip()
    except Exception:
        return ''


def _is_valid_logo_url(raw_url):
    url = (raw_url or '').strip()
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False


def _is_valid_hex_color(raw_color):
    value = (raw_color or '').strip()
    return bool(re.match(r'^#[0-9a-fA-F]{6}$', value))


@staff_member_required
def dashboard_home(request):
    """Main dashboard overview with analytics"""
    from datetime import timedelta

    tenant = _get_dashboard_tenant(request)
    is_superadmin = bool(request.user.is_superuser)
    if not is_superadmin and tenant is None:
        messages.error(request, 'Tenant context is required for dashboard access.')
        return redirect('courses')

    scoped_courses_qs = Course.objects.all()
    if not is_superadmin:
        scoped_courses_qs = scoped_courses_qs.filter(tenant=tenant)
    scoped_course_ids = scoped_courses_qs.values_list('id', flat=True)
    scoped_lessons_qs = Lesson.objects.filter(course_id__in=scoped_course_ids)
    scoped_enrollments_qs = CourseEnrollment.objects.filter(course_id__in=scoped_course_ids)
    scoped_access_qs = CourseAccess.objects.filter(course_id__in=scoped_course_ids)
    scoped_progress_qs = UserProgress.objects.filter(lesson__course_id__in=scoped_course_ids)
    scoped_certs_qs = Certification.objects.filter(course_id__in=scoped_course_ids)

    # Basic stats
    total_courses = scoped_courses_qs.count()
    total_lessons = scoped_lessons_qs.count()
    approved_lessons = scoped_lessons_qs.filter(ai_generation_status='approved').count()
    pending_lessons = scoped_lessons_qs.filter(ai_generation_status='pending').count()
    recent_lessons = scoped_lessons_qs.select_related('course').order_by('-created_at')[:10]
    courses = scoped_courses_qs.annotate(lesson_count=Count('lessons')).order_by('-created_at')
    
    # Student Analytics
    scoped_student_ids = set(scoped_enrollments_qs.values_list('user_id', flat=True))
    scoped_student_ids.update(scoped_access_qs.values_list('user_id', flat=True))
    scoped_students_qs = User.objects.filter(id__in=scoped_student_ids)
    total_students = scoped_students_qs.filter(is_staff=False, is_superuser=False).count()
    active_students = scoped_students_qs.filter(
        is_staff=False, 
        is_superuser=False,
        last_login__gte=timezone.now() - timedelta(days=30)
    ).count()
    new_students_30d = scoped_students_qs.filter(
        is_staff=False,
        is_superuser=False,
        date_joined__gte=timezone.now() - timedelta(days=30)
    ).count()
    
    # Enrollment Analytics
    total_enrollments = scoped_enrollments_qs.count()
    active_enrollments = scoped_enrollments_qs.filter(
        enrolled_at__gte=timezone.now() - timedelta(days=30)
    ).count()
    
    # Course Access Analytics
    total_accesses = scoped_access_qs.filter(status='unlocked').count()
    expired_accesses = scoped_access_qs.filter(status='expired').count()
    
    # Progress Analytics
    total_progress = scoped_progress_qs.count()
    completed_lessons = scoped_progress_qs.filter(completed=True).count()
    completion_rate = (completed_lessons / total_progress * 100) if total_progress > 0 else 0
    
    # Certification Analytics
    total_certifications = scoped_certs_qs.count()
    certifications_30d = scoped_certs_qs.filter(
        issued_at__gte=timezone.now() - timedelta(days=30)
    ).count() if scoped_certs_qs.filter(issued_at__isnull=False).exists() else 0
    
    # Course Performance Analytics
    course_performance = []
    for course in scoped_courses_qs[:10]:
        enrollments = scoped_enrollments_qs.filter(course=course).count()
        accesses = scoped_access_qs.filter(course=course, status='unlocked').count()
        total_students_course = enrollments + accesses
        
        total_lessons_course = course.lessons.count()
        completed = scoped_progress_qs.filter(
            lesson__course=course,
            completed=True
        ).count()
        course_completion_rate = (completed / (total_lessons_course * total_students_course * 100)) if total_students_course > 0 and total_lessons_course > 0 else 0
        
        certifications_course = scoped_certs_qs.filter(course=course, status='passed').count()
        
        course_performance.append({
            'course': course,
            'total_students': total_students_course,
            'completion_rate': min(course_completion_rate * 100, 100),
            'certifications': certifications_course,
            'lessons': total_lessons_course,
        })
    
    # Recent Activity (last 7 days)
    seven_days_ago = timezone.now() - timedelta(days=7)
    recent_progress = scoped_progress_qs.filter(
        last_accessed__gte=seven_days_ago
    ).count()
    recent_certifications = scoped_certs_qs.filter(
        issued_at__gte=seven_days_ago
    ).count() if scoped_certs_qs.filter(issued_at__isnull=False).exists() else 0
    
    # Get student activity feed
    student_activities = get_student_activity_feed(limit=10, course_ids_qs=scoped_course_ids)
    
    # Enrollment trend (last 30 days)
    enrollment_trend = []
    for i in range(30, 0, -1):
        date = timezone.now() - timedelta(days=i)
        count = scoped_enrollments_qs.filter(
            enrolled_at__date=date.date()
        ).count()
        enrollment_trend.append({
            'date': date.strftime('%m/%d'),
            'count': count
        })
    
    return render(request, 'dashboard/home.html', {
        'total_courses': total_courses,
        'total_lessons': total_lessons,
        'approved_lessons': approved_lessons,
        'pending_lessons': pending_lessons,
        'recent_lessons': recent_lessons,
        'courses': courses,
        'student_activities': student_activities,
        # Analytics data
        'total_students': total_students,
        'active_students': active_students,
        'new_students_30d': new_students_30d,
        'total_enrollments': total_enrollments,
        'active_enrollments': active_enrollments,
        'total_accesses': total_accesses,
        'expired_accesses': expired_accesses,
        'total_progress': total_progress,
        'completed_lessons': completed_lessons,
        'completion_rate': round(completion_rate, 1),
        'total_certifications': total_certifications,
        'certifications_30d': certifications_30d,
        'course_performance': course_performance,
        'recent_progress': recent_progress,
        'recent_certifications': recent_certifications,
        'enrollment_trend': enrollment_trend,
    })


@staff_member_required
def dashboard_students(request):
    """Smart student list with activity updates and filtering"""
    # Get filter parameters
    course_filter = request.GET.get('course', '')
    status_filter = request.GET.get('status', 'all')  # all, active, completed, certified
    search_query = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'recent')  # recent, progress, name, enrolled
    
    # Get all users including admin/staff
    # Show all users who have activity OR all users if none have activity
    students_query = User.objects.all()
    
    # Auto-enroll admin/staff users in all active courses if they don't have enrollments
    admin_users = students_query.filter(Q(is_staff=True) | Q(is_superuser=True))
    active_courses = Course.objects.filter(status='active')
    
    for admin_user in admin_users:
        for course in active_courses:
            CourseEnrollment.objects.get_or_create(
                user=admin_user,
                course=course,
                defaults={'tenant': course.tenant, 'payment_type': 'full'}
            )
    
    # Apply search filter
    if search_query:
        students_query = students_query.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )
    
    # Get student data with activity
    students_data = []
    for student in students_query:
        # Get enrollments (legacy system)
        enrollments = CourseEnrollment.objects.filter(user=student).select_related('course')
        
        # Get course access records (new access control system)
        course_accesses = CourseAccess.objects.filter(
            user=student,
            status='unlocked'
        ).select_related('course')
        
        # Combine both - get unique courses from enrollments and accesses
        enrollment_courses = set(enrollments.values_list('course_id', flat=True))
        access_courses = set(course_accesses.values_list('course_id', flat=True))
        all_course_ids = enrollment_courses | access_courses
        
        # Apply course filter
        if course_filter:
            if int(course_filter) not in all_course_ids:
                continue
            all_course_ids = {int(course_filter)}
        
        # Get all courses for this student (even if empty, we still show the student)
        student_courses = Course.objects.filter(id__in=all_course_ids) if all_course_ids else Course.objects.none()
        
        # Calculate overall stats
        total_courses = len(all_course_ids)
        total_lessons_all = 0
        completed_lessons_all = 0
        certifications_count = 0
        recent_activity = None
        
        for course in student_courses:
            total_lessons = course.lessons.count()
            completed_lessons = UserProgress.objects.filter(
                user=student,
                lesson__course=course,
                completed=True
            ).count()
            total_lessons_all += total_lessons
            completed_lessons_all += completed_lessons
            
            # Check for certification
            if Certification.objects.filter(user=student, course=course, status='passed').exists():
                certifications_count += 1
        
        overall_progress = int((completed_lessons_all / total_lessons_all * 100)) if total_lessons_all > 0 else 0
        
        # Get most recent activity
        recent_progress = UserProgress.objects.filter(user=student).order_by('-last_accessed').first()
        recent_exam = ExamAttempt.objects.filter(user=student).order_by('-started_at').first()
        recent_cert = Certification.objects.filter(user=student).order_by('-issued_at', '-created_at').first()
        
        # Determine most recent activity
        activities = []
        if recent_progress:
            activities.append(('progress', recent_progress.last_accessed, recent_progress))
        if recent_exam:
            activities.append(('exam', recent_exam.started_at, recent_exam))
        if recent_cert and recent_cert.issued_at:
            activities.append(('cert', recent_cert.issued_at, recent_cert))
        
        if activities:
            activities.sort(key=lambda x: x[1], reverse=True)
            recent_activity = activities[0]
        
        # Determine status
        if certifications_count > 0:
            student_status = 'certified'
        elif overall_progress == 100:
            student_status = 'completed'
        elif overall_progress > 0:
            student_status = 'active'
        else:
            student_status = 'inactive'
        
        # Apply status filter
        if status_filter != 'all':
            if status_filter == 'active' and student_status != 'active':
                continue
            elif status_filter == 'completed' and student_status != 'completed':
                continue
            elif status_filter == 'certified' and student_status != 'certified':
                continue
        
        students_data.append({
            'student': student,
            'total_courses': total_courses,
            'total_lessons': total_lessons_all,
            'completed_lessons': completed_lessons_all,
            'overall_progress': overall_progress,
            'certifications_count': certifications_count,
            'recent_activity': recent_activity,
            'status': student_status,
            'enrollments': enrollments,
            'course_accesses': course_accesses,
            'courses': student_courses,
        })
    
    # Sort students
    if sort_by == 'recent':
        students_data.sort(key=lambda x: x['recent_activity'][1] if x['recent_activity'] else (timezone.now() - timezone.timedelta(days=365)), reverse=True)
    elif sort_by == 'progress':
        students_data.sort(key=lambda x: x['overall_progress'], reverse=True)
    elif sort_by == 'name':
        students_data.sort(key=lambda x: x['student'].username.lower())
    elif sort_by == 'enrolled':
        students_data.sort(key=lambda x: x['student'].date_joined, reverse=True)
    
    # Get activity feed
    activity_feed = get_student_activity_feed(limit=50)
    
    courses = Course.objects.all()
    
    return render(request, 'dashboard/students.html', {
        'students_data': students_data,
        'activity_feed': activity_feed,
        'courses': courses,
        'course_filter': course_filter,
        'status_filter': status_filter,
        'search_query': search_query,
        'sort_by': sort_by,
    })


def get_student_activity_feed(limit=20, course_ids_qs=None):
    """Get a comprehensive activity feed of all student activities"""
    activities = []
    filter_kwargs = {}
    if course_ids_qs is not None:
        filter_kwargs = {'lesson__course_id__in': course_ids_qs}
    
    # Recent lesson completions
    recent_completions = UserProgress.objects.filter(
        completed=True,
        completed_at__isnull=False,
        **filter_kwargs
    ).select_related('user', 'lesson', 'lesson__course').order_by('-completed_at')[:limit]
    
    for progress in recent_completions:
        activities.append({
            'type': 'lesson_completed',
            'timestamp': progress.completed_at,
            'user': progress.user,
            'course': progress.lesson.course,
            'lesson': progress.lesson,
            'data': {
                'watch_percentage': progress.video_watch_percentage,
            }
        })
    
    # Recent exam attempts
    recent_exams = ExamAttempt.objects.select_related('user', 'exam', 'exam__course')
    if course_ids_qs is not None:
        recent_exams = recent_exams.filter(exam__course_id__in=course_ids_qs)
    recent_exams = recent_exams.order_by('-started_at')[:limit]
    
    for attempt in recent_exams:
        activities.append({
            'type': 'exam_attempt',
            'timestamp': attempt.started_at,
            'user': attempt.user,
            'course': attempt.exam.course,
            'data': {
                'score': attempt.score,
                'passed': attempt.passed,
                'attempt_number': attempt.attempt_number(),
            }
        })
    
    # Recent certifications
    recent_certs = Certification.objects.filter(issued_at__isnull=False)
    if course_ids_qs is not None:
        recent_certs = recent_certs.filter(course_id__in=course_ids_qs)
    recent_certs = recent_certs.select_related('user', 'course').order_by('-issued_at')[:limit]
    
    for cert in recent_certs:
        activities.append({
            'type': 'certification_issued',
            'timestamp': cert.issued_at,
            'user': cert.user,
            'course': cert.course,
            'data': {
                'certificate_id': cert.accredible_certificate_id,
            }
        })
    
    # Recent progress updates (video watch)
    recent_progress = UserProgress.objects.filter(
        video_watch_percentage__gt=0,
        last_accessed__isnull=False,
        **filter_kwargs
    ).select_related('user', 'lesson', 'lesson__course').order_by('-last_accessed')[:limit]
    
    for progress in recent_progress:
        # Only add if significant progress (avoid spam)
        if progress.video_watch_percentage >= 50 or progress.completed:
            activities.append({
                'type': 'progress_update',
                'timestamp': progress.last_accessed,
                'user': progress.user,
                'course': progress.lesson.course,
                'lesson': progress.lesson,
                'data': {
                    'watch_percentage': progress.video_watch_percentage,
                    'status': progress.status,
                }
            })
    
    # Sort by timestamp (most recent first)
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return activities[:limit]


@staff_member_required
def dashboard_courses(request):
    """List all courses"""
    tenant = _get_dashboard_tenant(request)
    is_superadmin = bool(request.user.is_superuser)
    courses_qs = Course.objects.all()
    if not is_superadmin:
        if tenant is None:
            messages.error(request, 'Tenant context is required to view courses.')
            return redirect('courses')
        courses_qs = courses_qs.filter(tenant=tenant)
    courses = list(courses_qs.select_related('tenant').annotate(lesson_count=Count('lessons')).order_by('-created_at'))
    if is_superadmin:
        for course in courses:
            owner_tenant = getattr(course, 'tenant', None)
            course.owner_name = owner_tenant.name if owner_tenant else 'Unassigned'
            course.owner_slug = owner_tenant.slug if owner_tenant else ''
            course.owner_site_url = get_tenant_public_home_url(request, owner_tenant) if owner_tenant else ''
    return render(request, 'dashboard/courses.html', {
        'courses': courses,
        'is_superadmin': is_superadmin,
    })


@staff_member_required
def dashboard_course_detail(request, course_slug):
    """Edit course details and manage resources"""
    tenant = _get_dashboard_tenant(request)
    if request.user.is_superuser:
        course = get_object_or_404(Course, slug=course_slug)
    else:
        if tenant is None:
            messages.error(request, 'Tenant context is required.')
            return redirect('dashboard_courses')
        course = get_object_or_404(Course, slug=course_slug, tenant=tenant)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'add_resource':
            title = request.POST.get('resource_title', '').strip()
            file_url = request.POST.get('resource_file_url', '').strip()
            uploaded_file = request.FILES.get('resource_file')
            if title and (uploaded_file or file_url):
                resource_type = request.POST.get('resource_type', 'other')
                description = request.POST.get('resource_description', '').strip()
                max_order = course.resources.aggregate(models.Max('order'))['order__max'] or 0
                CourseResource.objects.create(
                    tenant=course.tenant,
                    course=course,
                    title=title,
                    description=description,
                    resource_type=resource_type,
                    file=uploaded_file if uploaded_file else None,
                    file_url=file_url or '',
                    order=max_order + 1,
                )
                messages.success(request, f'Resource "{title}" added successfully.')
            elif title and not (uploaded_file or file_url):
                messages.error(request, 'Please provide either an uploaded file or an external URL.')
            return redirect('dashboard_course_detail', course_slug=course.slug)
        elif action == 'delete_resource':
            rid = request.POST.get('resource_id')
            if rid:
                try:
                    r = CourseResource.objects.get(id=rid, course=course)
                    r.delete()
                    messages.success(request, 'Resource deleted.')
                except CourseResource.DoesNotExist:
                    pass
            return redirect('dashboard_course_detail', course_slug=course.slug)
        else:
            course.name = request.POST.get('name', course.name)
            course.short_description = request.POST.get('short_description', course.short_description)
            course.description = request.POST.get('description', course.description)
            course.status = request.POST.get('status', course.status)
            course.course_type = request.POST.get('course_type', course.course_type)
            course.coach_name = request.POST.get('coach_name', course.coach_name)
            raw_price = request.POST.get('price', '').strip()
            try:
                price = round(float(raw_price), 2) if raw_price else None
                if price is not None and price <= 0:
                    price = None
            except (ValueError, TypeError):
                price = None
            course.price = price
            course.enrollment_method = 'purchase' if price else 'open'
            course.save()
            messages.success(request, 'Course updated.')
            return redirect('dashboard_course_detail', course_slug=course.slug)

    return render(request, 'dashboard/course_detail.html', {
        'course': course,
        'course_resources': course.resources.all(),
    })


@staff_member_required
@require_http_methods(["POST"])
def dashboard_delete_course(request, course_slug):
    """Delete a course"""
    tenant = _get_dashboard_tenant(request)
    if request.user.is_superuser:
        course = get_object_or_404(Course, slug=course_slug)
    else:
        if tenant is None:
            messages.error(request, 'Tenant context is required.')
            return redirect('dashboard_courses')
        course = get_object_or_404(Course, slug=course_slug, tenant=tenant)
    course_name = course.name
    
    try:
        course.delete()
        messages.success(request, f'Course "{course_name}" has been deleted successfully.')
    except Exception as e:
        messages.error(request, f'Error deleting course: {str(e)}')
    
    return redirect('dashboard_courses')


@staff_member_required
def dashboard_lesson_quiz(request, lesson_id):
    """Create and manage a simple quiz for a lesson."""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    quiz, created = LessonQuiz.objects.get_or_create(
        lesson=lesson,
        defaults={
            'tenant': lesson.tenant,
            'title': f'{lesson.title} Quiz',
            'passing_score': 80,
        },
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_quiz':
            quiz.title = request.POST.get('title') or quiz.title
            quiz.description = request.POST.get('description', '')
            try:
                quiz.passing_score = float(
                    request.POST.get('passing_score') or quiz.passing_score
                )
            except ValueError:
                pass
            quiz.is_required = bool(request.POST.get('is_required'))
            quiz.save()
            messages.success(request, 'Quiz settings updated.')
        elif action == 'add_question':
            text = request.POST.get('q_text', '').strip()
            if text:
                order = (
                    quiz.questions.aggregate(models.Max('order'))['order__max'] or 0
                ) + 1
                LessonQuizQuestion.objects.create(
                    quiz=quiz,
                    text=text,
                    option_a=request.POST.get('q_option_a', '').strip(),
                    option_b=request.POST.get('q_option_b', '').strip(),
                    option_c=request.POST.get('q_option_c', '').strip(),
                    option_d=request.POST.get('q_option_d', '').strip(),
                    correct_option=request.POST.get('q_correct_option', 'A') or 'A',
                    order=order,
                )
                messages.success(request, 'Question added.')
            else:
                messages.error(request, 'Question text is required.')
        elif action == 'edit_question':
            q_id = request.POST.get('question_id')
            if q_id:
                try:
                    question = LessonQuizQuestion.objects.get(id=q_id, quiz=quiz)
                    question.text = request.POST.get('q_text', '').strip()
                    question.option_a = request.POST.get('q_option_a', '').strip()
                    question.option_b = request.POST.get('q_option_b', '').strip()
                    question.option_c = request.POST.get('q_option_c', '').strip()
                    question.option_d = request.POST.get('q_option_d', '').strip()
                    question.correct_option = request.POST.get('q_correct_option', 'A') or 'A'
                    question.save()
                    messages.success(request, 'Question updated.')
                except LessonQuizQuestion.DoesNotExist:
                    messages.error(request, 'Question not found.')
        elif action == 'delete_question':
            q_id = request.POST.get('question_id')
            if q_id:
                LessonQuizQuestion.objects.filter(id=q_id, quiz=quiz).delete()
                messages.success(request, 'Question deleted.')

        return redirect('dashboard_lesson_quiz', lesson_id=lesson.id)

    questions = LessonQuizQuestion.objects.filter(quiz=quiz).order_by('order', 'id')
    return render(request, 'dashboard/lesson_quiz.html', {
        'lesson': lesson,
        'quiz': quiz,
        'questions': questions,
    })


@staff_member_required
@require_http_methods(["POST"])
def dashboard_delete_quiz(request, lesson_id):
    """Delete a quiz for a lesson"""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    
    try:
        if hasattr(lesson, 'quiz'):
            quiz_title = lesson.quiz.title
            lesson.quiz.delete()
            messages.success(request, f'Quiz "{quiz_title}" has been deleted successfully.')
        else:
            messages.warning(request, 'No quiz found for this lesson.')
    except Exception as e:
        messages.error(request, f'Error deleting quiz: {str(e)}')
    
    return redirect('dashboard_lesson_quiz', lesson_id=lesson.id)


@staff_member_required
def dashboard_quizzes(request):
    """List all quizzes across all lessons"""
    # Get filter parameters
    course_filter = request.GET.get('course', '')
    search_query = request.GET.get('search', '')
    
    # Get all quizzes with related lesson and course info
    quizzes = LessonQuiz.objects.select_related('lesson', 'lesson__course').prefetch_related('questions').all()
    
    # Apply course filter
    if course_filter:
        quizzes = quizzes.filter(lesson__course_id=course_filter)
    
    # Apply search filter
    if search_query:
        quizzes = quizzes.filter(
            Q(title__icontains=search_query) |
            Q(lesson__title__icontains=search_query) |
            Q(lesson__course__name__icontains=search_query)
        )
    
    # Order by course and lesson
    quizzes = quizzes.order_by('lesson__course__name', 'lesson__order', 'lesson__id')
    
    # Get quiz data with question counts
    quiz_data = []
    for quiz in quizzes:
        quiz_data.append({
            'quiz': quiz,
            'lesson': quiz.lesson,
            'course': quiz.lesson.course,
            'question_count': quiz.questions.count(),
        })
    
    courses = Course.objects.all()
    
    return render(request, 'dashboard/quizzes.html', {
        'quiz_data': quiz_data,
        'courses': courses,
        'course_filter': course_filter,
        'search_query': search_query,
    })


@staff_member_required
def dashboard_course_lessons(request, course_slug):
    """View all lessons for a course"""
    tenant = _get_dashboard_tenant(request)
    if request.user.is_superuser:
        course = get_object_or_404(Course, slug=course_slug)
    else:
        if tenant is None:
            messages.error(request, 'Tenant context is required.')
            return redirect('dashboard_courses')
        course = get_object_or_404(Course, slug=course_slug, tenant=tenant)
    lessons = course.lessons.all()
    modules = course.modules.all()
    
    return render(request, 'dashboard/course_lessons.html', {
        'course': course,
        'lessons': lessons,
        'modules': modules,
    })


def create_editorjs_block(block_type, data, block_id=None):
    """Create an Editor.js block"""
    return {
        "id": block_id or str(uuid.uuid4()),
        "type": block_type,
        "data": data
    }


def create_editorjs_content(content_sections):
    """Create Editor.js content blocks from content sections"""
    blocks = []
    for section in content_sections:
        if section.get('type') == 'paragraph':
            blocks.append(create_editorjs_block('paragraph', {'text': section.get('text', '')}))
        elif section.get('type') == 'header':
            blocks.append(create_editorjs_block('header', {
                'text': section.get('text', ''),
                'level': section.get('level', 2)
            }))
        elif section.get('type') == 'list':
            blocks.append(create_editorjs_block('list', {
                'style': section.get('style', 'unordered'),
                'items': section.get('items', [])
            }))
        elif section.get('type') == 'quote':
            blocks.append(create_editorjs_block('quote', {
                'text': section.get('text', ''),
                'caption': section.get('caption', '')
            }))
    
    return {
        "time": int(timezone.now().timestamp() * 1000),
        "blocks": blocks,
        "version": "2.28.2"
    }


def generate_ai_lesson_metadata(client, lesson_title, lesson_description, course_name, course_type, tenant=None, course=None, lesson=None, blueprint_context=''):
    """Generate all AI lesson metadata fields (title, summary, description, outcomes, coach actions)"""
    extra = f"\n{blueprint_context}\n" if blueprint_context else ''
    prompt = f"""You are an expert course creator. Generate comprehensive lesson metadata for the following lesson:

Course: {course_name}
Course Type: {course_type}
Lesson Title: {lesson_title}
Lesson Description: {lesson_description}
{extra}
Generate the following fields:
1. clean_title: A polished, professional version of the lesson title (keep it concise and clear)
2. short_summary: A 1-2 sentence summary for lesson cards/lists (max 150 characters)
3. full_description: A detailed 2-3 paragraph description explaining what students will learn (engaging and informative)
4. outcomes: An array of 3-5 specific learning outcomes (what students will achieve)
5. coach_actions: An array of 3-4 recommended AI coach actions (e.g., "Summarize in 5 bullets", "Create a 3-step action plan")

Return in JSON format:
{{
  "clean_title": "Polished Lesson Title",
  "short_summary": "Brief summary for lesson cards",
  "full_description": "Detailed multi-paragraph description of what students will learn in this lesson. Make it engaging and informative.",
  "outcomes": [
    "Outcome 1",
    "Outcome 2",
    "Outcome 3"
  ],
  "coach_actions": [
    "Action 1",
    "Action 2",
    "Action 3"
  ]
}}

Only return valid JSON, no additional text."""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert course creator. Always return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500
        )
        _log_openai_usage(
            feature='lesson_metadata',
            response=response,
            tenant=tenant,
            course=course,
            lesson=lesson,
            model_name='gpt-4o-mini',
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Clean up response
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
            response_text = response_text.strip()
        if response_text.endswith('```'):
            response_text = response_text.rsplit('```', 1)[0].strip()
        
        # Parse JSON
        try:
            metadata = json.loads(response_text)
            return {
                'clean_title': metadata.get('clean_title', lesson_title),
                'short_summary': metadata.get('short_summary', ''),
                'full_description': metadata.get('full_description', lesson_description),
                'outcomes': metadata.get('outcomes', []),
                'coach_actions': metadata.get('coach_actions', [])
            }
        except json.JSONDecodeError:
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                metadata = json.loads(json_match.group())
                return {
                    'clean_title': metadata.get('clean_title', lesson_title),
                    'short_summary': metadata.get('short_summary', ''),
                    'full_description': metadata.get('full_description', lesson_description),
                    'outcomes': metadata.get('outcomes', []),
                    'coach_actions': metadata.get('coach_actions', [])
                }
            # Fallback to basic values
            return {
                'clean_title': lesson_title,
                'short_summary': f"Learn key concepts from {lesson_title}",
                'full_description': lesson_description,
                'outcomes': [],
                'coach_actions': []
            }
    except Exception as e:
        # Return fallback values if generation fails
        return {
            'clean_title': lesson_title,
            'short_summary': f"Learn key concepts from {lesson_title}",
            'full_description': lesson_description,
            'outcomes': [],
            'coach_actions': []
        }


def generate_ai_lesson_content(client, lesson_title, lesson_description, course_name, course_type, tenant=None, course=None, lesson=None, blueprint_context=''):
    """Generate detailed lesson content using AI (Editor.js blocks)"""
    extra = f"\n{blueprint_context}\n" if blueprint_context else ''
    prompt = f"""You are an expert course creator. Create comprehensive lesson content for the following lesson:

Course: {course_name}
Course Type: {course_type}
Lesson Title: {lesson_title}
Lesson Description: {lesson_description}
{extra}
Generate detailed lesson content that includes:
1. An engaging introduction paragraph
2. Key learning objectives (as headers)
3. Main content sections with explanations
4. Practical examples or tips
5. A summary or conclusion

Return the content in JSON format with Editor.js compatible blocks:
{{
  "content": [
    {{
      "type": "header",
      "text": "Section Title",
      "level": 2
    }},
    {{
      "type": "paragraph",
      "text": "Paragraph text here"
    }},
    {{
      "type": "list",
      "style": "unordered",
      "items": ["Item 1", "Item 2", "Item 3"]
    }},
    {{
      "type": "quote",
      "text": "Important quote or tip",
      "caption": "Optional caption"
    }}
  ]
}}

Make the content educational, practical, and engaging. Include at least 5-8 content blocks.
Only return valid JSON, no additional text."""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert course creator. Always return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        _log_openai_usage(
            feature='lesson_content',
            response=response,
            tenant=tenant,
            course=course,
            lesson=lesson,
            model_name='gpt-4o-mini',
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Clean up response
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
            response_text = response_text.strip()
        if response_text.endswith('```'):
            response_text = response_text.rsplit('```', 1)[0].strip()
        
        # Parse JSON
        try:
            content_data = json.loads(response_text)
            return content_data.get('content', [])
        except json.JSONDecodeError:
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                content_data = json.loads(json_match.group())
                return content_data.get('content', [])
            return []
    except Exception as e:
        # Return empty content if generation fails
        return []


def generate_ai_course_structure(course_name, description, course_type='sprint', coach_name='Sprint Coach', tenant=None, course=None, blueprint=None):
    """Generate complete course structure (modules and lessons) using AI"""
    if not OPENAI_AVAILABLE:
        raise Exception('OpenAI is not available. Please install the openai package.')
    
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise Exception('OPENAI_API_KEY not found in environment variables.')
    
    try:
        client = OpenAI(api_key=api_key)
        blueprint_extra = _blueprint_structure_prompt_section(blueprint) if blueprint else ''
        
        # Create prompt for AI
        prompt = f"""You are an expert course creator. Based on the following course information, generate a complete course structure with modules and lessons.

Course Name: {course_name}
Course Type: {course_type}
Coach Name: {coach_name}
Description: {description}
{blueprint_extra}
Generate a comprehensive course structure with:
1. 3-6 modules (logical groupings of lessons)
2. 3-8 lessons per module (total 12-30 lessons)
3. Each lesson should have a clear title and description
4. Lessons should progress logically from basics to advanced concepts
5. Make it practical and actionable

Return the structure in JSON format:
{{
  "modules": [
    {{
      "name": "Module Name",
      "description": "Brief module description",
      "order": 1,
      "lessons": [
        {{
          "title": "Lesson Title",
          "description": "Detailed lesson description explaining what students will learn",
          "order": 1
        }}
      ]
    }}
  ]
}}

Only return valid JSON, no additional text."""
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert course creator. Always return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=4000
        )
        _log_openai_usage(
            feature='course_structure',
            response=response,
            tenant=tenant,
            course=course,
            model_name='gpt-4o-mini',
        )
        
        # Parse response
        response_text = response.choices[0].message.content.strip()
        
        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
            response_text = response_text.strip()
        if response_text.endswith('```'):
            response_text = response_text.rsplit('```', 1)[0].strip()
        
        # Parse JSON
        try:
            course_data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                course_data = json.loads(json_match.group())
            else:
                raise Exception('Failed to parse AI response as JSON.')
        
        return course_data, client
        
    except Exception as e:
        raise Exception(f'AI generation failed: {str(e)}')


TRAINING_WEBHOOK_URL = 'https://katalyst-crm2.fly.dev/webhook/425e8e67-2aa6-4c50-b67f-0162e2496b51'


def _extract_lesson_text_for_chatbot(lesson):
    """Extract text content from lesson for chatbot training (transcript replacement for AI-generated lessons)"""
    parts = []
    if lesson.ai_full_description:
        parts.append(lesson.ai_full_description)
    elif lesson.description:
        parts.append(lesson.description)
    if lesson.ai_short_summary:
        parts.append(lesson.ai_short_summary)
    # Extract text from Editor.js content blocks
    content = lesson.content if isinstance(lesson.content, dict) else {}
    for block in content.get('blocks', []):
        data = block.get('data', {})
        if block.get('type') == 'paragraph' and data.get('text'):
            parts.append(data['text'])
        elif block.get('type') == 'header' and data.get('text'):
            parts.append(data['text'])
        elif block.get('type') == 'list':
            for item in data.get('items', []):
                if item:
                    parts.append(f"• {item}")
        elif block.get('type') == 'quote' and data.get('text'):
            parts.append(data['text'])
    return '\n\n'.join(p.strip() for p in parts if p and p.strip()) or lesson.title


def _send_lesson_to_chatbot_webhook(lesson):
    """Send lesson content to training webhook for AI chatbot. Returns True on success, False on failure."""
    transcript = _extract_lesson_text_for_chatbot(lesson)
    if not transcript:
        return False
    payload = {
        'transcript': transcript,
        'lesson_id': lesson.id,
        'lesson_title': lesson.title,
        'course_name': lesson.course.name,
        'lesson_slug': lesson.slug,
    }
    try:
        response = requests.post(TRAINING_WEBHOOK_URL, json=payload, timeout=30, headers={'Content-Type': 'application/json'})
        if response.status_code == 200:
            data = response.json()
            webhook_id = data.get('chatbot_webhook_id') or data.get('webhook_id') or data.get('id')
            if webhook_id:
                lesson.ai_chatbot_webhook_id = str(webhook_id)
            lesson.ai_chatbot_training_status = 'trained'
            lesson.ai_chatbot_trained_at = timezone.now()
            lesson.ai_chatbot_enabled = True
            lesson.ai_chatbot_training_error = ''
            lesson.save()
            return True
        else:
            lesson.ai_chatbot_training_status = 'failed'
            lesson.ai_chatbot_training_error = f"Webhook returned {response.status_code}: {response.text[:200]}"
            lesson.save()
            return False
    except Exception as e:
        lesson.ai_chatbot_training_status = 'failed'
        lesson.ai_chatbot_training_error = str(e)
        lesson.save()
        return False


def _get_ai_gen_cache_key(course_id):
    return f'ai_gen_{course_id}'


def _update_ai_gen_progress(course_id, course_name, status, progress=0, total=0, current='', error=None):
    """Update AI generation progress in cache (15 min TTL)"""
    data = {
        'status': status,
        'progress': progress,
        'total': total,
        'current': current,
        'course_name': course_name,
        'error': error,
    }
    cache.set(_get_ai_gen_cache_key(course_id), data, timeout=900)  # 15 min


def _generate_course_ai_content(course_id, course_name, description, course_type, coach_name):
    """Background function to generate AI course content"""
    try:
        from django.db import connection
        # Close any existing database connections before starting thread
        connection.close()
        
        _update_ai_gen_progress(course_id, course_name, 'generating_structure', progress=5, current='Generating course structure...')
        
        # Re-fetch course to ensure we have latest data
        course = Course.objects.get(id=course_id)
        blueprint = course.creation_blueprint if isinstance(course.creation_blueprint, dict) else {}
        lesson_blueprint_ctx = _blueprint_lesson_context_block(blueprint)
        seed_lessons = blueprint.get('seed_lessons') if isinstance(blueprint.get('seed_lessons'), list) else []
        modules_data = []

        if seed_lessons:
            if not OPENAI_AVAILABLE:
                raise Exception('OpenAI is not available. Please install the openai package.')
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise Exception('OPENAI_API_KEY not found in environment variables.')
            ai_client = OpenAI(api_key=api_key)
            modules_data = [{
                'name': 'Provided Lessons',
                'description': 'Lessons generated from the creator-provided lesson inputs.',
                'order': 1,
                'lessons': [
                    {
                        'title': item.get('title', 'Untitled Lesson'),
                        'description': item.get('source', ''),
                        'video_link': item.get('video_link', ''),
                        'order': idx + 1,
                    }
                    for idx, item in enumerate(seed_lessons)
                ],
            }]
        else:
            # Generate course structure with AI
            course_structure, ai_client = generate_ai_course_structure(
                course_name=course_name,
                description=description,
                course_type=course_type,
                coach_name=coach_name,
                tenant=course.tenant,
                course=course,
                blueprint=blueprint,
            )
            modules_data = course_structure.get('modules', [])
        total_items = sum(1 + len(m.get('lessons', [])) for m in modules_data)  # each module + each lesson
        if total_items == 0:
            total_items = 1
        items_done = 0
        
        _update_ai_gen_progress(course_id, course_name, 'creating_content', progress=15, total=total_items, current='Creating modules and lessons...')
        
        # Create modules and lessons
        modules_created = 0
        lessons_created = 0
        
        for module_data in modules_data:
            module = Module.objects.create(
                tenant=course.tenant,
                course=course,
                name=module_data.get('name', 'Untitled Module'),
                description=module_data.get('description', ''),
                order=module_data.get('order', 0)
            )
            modules_created += 1
            items_done += 1
            pct = min(95, 15 + int(80 * items_done / total_items))
            _update_ai_gen_progress(course_id, course_name, 'creating_content', progress=pct, total=total_items, current=f'Creating: {module.name}')
            
            # Create lessons for this module
            for lesson_data in module_data.get('lessons', []):
                lesson_title = lesson_data.get('title', 'Untitled Lesson')
                lesson_description = lesson_data.get('description', '')
                lesson_video_link = (lesson_data.get('video_link') or '').strip()
                if lesson_video_link:
                    lesson_description = f"{lesson_description}\n\nVideo reference: {lesson_video_link}"
                lesson_slug = generate_slug(lesson_title)
                
                # Ensure lesson slug is unique within course
                base_lesson_slug = lesson_slug
                lesson_counter = 1
                while Lesson.objects.filter(course=course, slug=lesson_slug).exists():
                    lesson_slug = f"{base_lesson_slug}-{lesson_counter}"
                    lesson_counter += 1
                
                # Generate all AI lesson metadata (title, summary, description, outcomes, coach actions)
                lesson_metadata = generate_ai_lesson_metadata(
                    client=ai_client,
                    lesson_title=lesson_title,
                    lesson_description=lesson_description,
                    course_name=course_name,
                    course_type=course_type,
                    tenant=course.tenant,
                    course=course,
                    blueprint_context=lesson_blueprint_ctx,
                )
                
                # Generate lesson content blocks using AI (Editor.js format)
                lesson_content_sections = generate_ai_lesson_content(
                    client=ai_client,
                    lesson_title=lesson_title,
                    lesson_description=lesson_description,
                    course_name=course_name,
                    course_type=course_type,
                    tenant=course.tenant,
                    course=course,
                    blueprint_context=lesson_blueprint_ctx,
                )
                
                # Convert content sections to Editor.js format
                lesson_content = create_editorjs_content(lesson_content_sections) if lesson_content_sections else {}
                
                lesson = Lesson.objects.create(
                    tenant=course.tenant,
                    course=course,
                    module=module,
                    title=lesson_title,
                    slug=lesson_slug,
                    description=lesson_description,
                    video_url=lesson_video_link,
                    order=lesson_data.get('order', 0),
                    working_title=lesson_title,
                    # AI-generated metadata fields
                    ai_clean_title=lesson_metadata.get('clean_title', lesson_title),
                    ai_short_summary=lesson_metadata.get('short_summary', ''),
                    ai_full_description=lesson_metadata.get('full_description', lesson_description),
                    ai_outcomes=lesson_metadata.get('outcomes', []),
                    ai_coach_actions=lesson_metadata.get('coach_actions', []),
                    # Editor.js content blocks
                    content=lesson_content,
                    ai_generation_status='generated'
                )
                lessons_created += 1
                # Auto-generate quiz for this lesson
                try:
                    quiz, _ = LessonQuiz.objects.get_or_create(
                        lesson=lesson,
                        defaults={
                            'tenant': lesson.tenant,
                            'title': f'{lesson_title} Quiz',
                            'passing_score': 70,
                            'is_required': True
                        },
                    )
                    qc = generate_ai_quiz(lesson, quiz, num_questions=5)
                    if qc > 0:
                        print(f'[Background] Quiz created for lesson: {lesson_title[:50]} ({qc} questions)')
                except Exception as eq:
                    print(f'[Background] Quiz generation failed for {lesson_title[:50]}: {eq}')
                # Auto-send to chatbot training webhook so AI learns from each lesson
                if _send_lesson_to_chatbot_webhook(lesson):
                    print(f'[Background] Chatbot trained for lesson: {lesson_title[:50]}')
                else:
                    print(f'[Background] Chatbot training failed for lesson: {lesson_title[:50]}')
                items_done += 1
                pct = min(90, 15 + int(75 * items_done / total_items))
                _update_ai_gen_progress(course_id, course_name, 'creating_content', progress=pct, total=total_items, current=f'Lesson: {lesson_title[:50]}')
        
        # Create final exam with AI-generated questions
        _update_ai_gen_progress(course_id, course_name, 'creating_content', progress=92, total=total_items, current='Creating final exam...')
        try:
            exam, created = Exam.objects.get_or_create(
                course=course,
                defaults={
                    'tenant': course.tenant,
                    'title': f'Final Exam - {course_name}',
                    'description': f'Comprehensive exam covering all concepts from {course_name}. Complete all lessons before attempting.',
                    'passing_score': 70,
                    'max_attempts': 3,
                    'time_limit_minutes': 60,
                },
            )
            num_exam_q = min(25, max(15, lessons_created * 2))
            exam_qc = generate_ai_exam(course, exam, num_questions=num_exam_q)
            if exam_qc > 0:
                print(f'[Background] Final exam created for "{course_name}": {exam_qc} questions')
        except Exception as ex:
            print(f'[Background] Exam generation failed for "{course_name}": {ex}')
        
        _update_ai_gen_progress(course_id, course_name, 'completed', progress=100, total=total_items, current='Complete!')
        print(f'[Background] Successfully generated AI content for course "{course_name}": {modules_created} modules, {lessons_created} lessons')
        
    except Exception as e:
        _update_ai_gen_progress(course_id, course_name, 'failed', progress=0, error=str(e))
        print(f'[Background] Error generating AI content for course "{course_name}": {str(e)}')
        import traceback
        traceback.print_exc()


def _remove_course_from_session(request, course_id):
    """Remove a single course from the ai_generating_courses list"""
    courses_list = request.session.get('ai_generating_courses', [])
    if not isinstance(courses_list, list):
        request.session['ai_generating_courses'] = []
    else:
        request.session['ai_generating_courses'] = [
            c for c in courses_list
            if isinstance(c, dict) and c.get('id') != course_id
        ]
    request.session.modified = True


@staff_member_required
def api_ai_generation_status(request, course_id):
    """JSON endpoint for polling AI course generation progress"""
    data = cache.get(_get_ai_gen_cache_key(course_id))
    if data is None:
        # In multi-worker deployments using local-memory cache, one worker might not
        # see in-memory progress from another worker. If the course is still tracked
        # in session, keep the widget alive and keep polling.
        courses_list = request.session.get('ai_generating_courses', [])
        in_session = any(
            isinstance(item, dict) and int(item.get('id') or 0) == int(course_id)
            for item in (courses_list or [])
        )
        if in_session:
            return JsonResponse({
                'status': 'starting',
                'progress': 3,
                'current': 'Queued... waiting for worker status',
            })
        _remove_course_from_session(request, course_id)
        return JsonResponse({'status': 'unknown', 'progress': 0})
    if data.get('status') in ('completed', 'failed'):
        _remove_course_from_session(request, course_id)
    return JsonResponse(data)


@staff_member_required
@require_http_methods(["POST"])
def dashboard_generate_lesson_draft(request):
    """Generate a complete AI lesson package from title + source text."""
    if not OPENAI_AVAILABLE:
        return JsonResponse({
            'success': False,
            'error': 'OpenAI package is not installed on this server.',
        }, status=500)

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return JsonResponse({
            'success': False,
            'error': 'OPENAI_API_KEY is missing. Configure it to use lesson generation.',
        }, status=500)

    lesson_title = (request.POST.get('lesson_title') or '').strip()
    source_text = (request.POST.get('lesson_source') or '').strip()
    video_link = (request.POST.get('lesson_video_link') or '').strip()
    course_context = (request.POST.get('course_context') or '').strip() or 'Standalone lesson'

    if not lesson_title:
        return JsonResponse({'success': False, 'error': 'Lesson title is required.'}, status=400)
    if not source_text:
        return JsonResponse({'success': False, 'error': 'Lesson description or transcription is required.'}, status=400)

    tenant = _get_dashboard_tenant(request)
    if tenant is None:
        return JsonResponse({'success': False, 'error': 'Tenant context is required.'}, status=400)

    source_for_ai = source_text
    if video_link:
        source_for_ai = f"{source_for_ai}\n\nVideo reference link: {video_link}"

    try:
        client = OpenAI(api_key=api_key)
        metadata = generate_ai_lesson_metadata(
            client=client,
            lesson_title=lesson_title,
            lesson_description=source_for_ai,
            course_name=course_context[:200],
            course_type='sprint',
            tenant=tenant,
            course=None,
            lesson=None,
            blueprint_context='Generated from dashboard Lesson Generator quick tool.',
        )
        content_sections = generate_ai_lesson_content(
            client=client,
            lesson_title=lesson_title,
            lesson_description=source_for_ai,
            course_name=course_context[:200],
            course_type='sprint',
            tenant=tenant,
            course=None,
            lesson=None,
            blueprint_context='Generate practical, immediately usable standalone lesson notes.',
        )
        content_data = create_editorjs_content(content_sections)

        return JsonResponse({
            'success': True,
            'lesson': {
                'clean_title': metadata.get('clean_title') or lesson_title,
                'short_summary': metadata.get('short_summary') or '',
                'full_description': metadata.get('full_description') or source_text,
                'outcomes': metadata.get('outcomes') or [],
                'coach_actions': metadata.get('coach_actions') or [],
                'content': content_data,
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Lesson generation failed: {str(e)}',
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def dashboard_create_course_from_lessons(request):
    """Create a course from Lesson Generator inputs and start AI background generation."""
    tenant = _get_dashboard_tenant(request)
    if tenant is None:
        return JsonResponse({'success': False, 'error': 'Tenant context is required.'}, status=400)

    course_title = (request.POST.get('course_title') or '').strip()
    seed_lessons = _parse_seed_lessons(request.POST.get('lessons_json'))
    if not course_title:
        return JsonResponse({'success': False, 'error': 'Course title is required.'}, status=400)
    if not seed_lessons:
        return JsonResponse({'success': False, 'error': 'Add at least one lesson with title and description.'}, status=400)

    slug = generate_slug(course_title or 'course')
    if len(slug) > 200:
        slug = slug[:200].rstrip('-') or 'course'
    base_slug = slug
    counter = 1
    while Course.objects.filter(tenant=tenant, slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    first_titles = [item.get('title', '').strip() for item in seed_lessons[:3] if item.get('title')]
    short_description = (
        f"AI-generated from provided lesson inputs ({len(seed_lessons)} lessons)."
        + (f" Includes: {', '.join(first_titles)}." if first_titles else '')
    )[:1000]
    description = (
        f"Course source: lesson-by-lesson creator inputs.\n\n"
        f"Total provided lessons: {len(seed_lessons)}"
    )
    course_type = 'sprint'
    coach_name = 'Sprint Coach'

    course = Course.objects.create(
        tenant=tenant,
        name=course_title,
        slug=slug,
        short_description=short_description,
        description=description,
        course_type=course_type,
        status='active',
        coach_name=coach_name,
        creation_blueprint={'seed_lessons': seed_lessons},
        price=None,
        enrollment_method='open',
    )

    courses_list = request.session.get('ai_generating_courses', [])
    if not isinstance(courses_list, list):
        courses_list = []
    courses_list.append({'id': course.id, 'name': course.name})
    request.session['ai_generating_courses'] = courses_list
    request.session.modified = True

    _update_ai_gen_progress(course.id, course.name, 'starting', progress=0, current='Starting...')
    thread = threading.Thread(
        target=_generate_course_ai_content,
        args=(course.id, course.name, description, course_type, coach_name),
        daemon=True
    )
    thread.start()

    return JsonResponse({
        'success': True,
        'course_id': course.id,
        'course_name': course.name,
        'redirect_url': '/dashboard/courses/',
    })


def _append_seed_lessons_ai(course_id, seed_lessons, module_id=None):
    """Background append of AI-generated lessons into an existing course."""
    try:
        from django.db import connection
        connection.close()

        course = Course.objects.get(id=course_id)
        blueprint = course.creation_blueprint if isinstance(course.creation_blueprint, dict) else {}
        lesson_blueprint_ctx = _blueprint_lesson_context_block(blueprint)
        target_module = None
        if module_id:
            target_module = Module.objects.filter(id=module_id, course=course).first()
        if target_module is None:
            # Sensible default: if course already has modules, append into first module
            target_module = course.modules.order_by('order', 'id').first()

        if not OPENAI_AVAILABLE:
            raise Exception('OpenAI is not available. Please install the openai package.')
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise Exception('OPENAI_API_KEY not found in environment variables.')
        ai_client = OpenAI(api_key=api_key)

        total_items = max(1, len(seed_lessons))
        _update_ai_gen_progress(
            course.id,
            course.name,
            'creating_content',
            progress=15,
            total=total_items,
            current='Adding AI lessons to existing course...',
        )

        if target_module:
            max_order = Lesson.objects.filter(course=course, module=target_module).aggregate(models.Max('order'))['order__max'] or 0
        else:
            max_order = Lesson.objects.filter(course=course).aggregate(models.Max('order'))['order__max'] or 0
        next_order = max_order + 1

        for idx, item in enumerate(seed_lessons):
            lesson_title = (item.get('title') or '').strip() or f'Lesson {next_order}'
            lesson_description = (item.get('source') or '').strip()
            lesson_video_link = (item.get('video_link') or '').strip()
            lesson_description_for_ai = lesson_description
            if lesson_video_link:
                lesson_description_for_ai = f"{lesson_description_for_ai}\n\nVideo reference: {lesson_video_link}"

            lesson_slug = generate_slug(lesson_title)
            base_lesson_slug = lesson_slug
            lesson_counter = 1
            while Lesson.objects.filter(course=course, slug=lesson_slug).exists():
                lesson_slug = f"{base_lesson_slug}-{lesson_counter}"
                lesson_counter += 1

            lesson_metadata = generate_ai_lesson_metadata(
                client=ai_client,
                lesson_title=lesson_title,
                lesson_description=lesson_description_for_ai,
                course_name=course.name,
                course_type=course.course_type,
                tenant=course.tenant,
                course=course,
                blueprint_context=lesson_blueprint_ctx,
            )
            lesson_content_sections = generate_ai_lesson_content(
                client=ai_client,
                lesson_title=lesson_title,
                lesson_description=lesson_description_for_ai,
                course_name=course.name,
                course_type=course.course_type,
                tenant=course.tenant,
                course=course,
                blueprint_context=lesson_blueprint_ctx,
            )
            lesson_content = create_editorjs_content(lesson_content_sections) if lesson_content_sections else {}

            lesson = Lesson.objects.create(
                tenant=course.tenant,
                course=course,
                module=target_module,
                title=lesson_title,
                slug=lesson_slug,
                description=lesson_description_for_ai,
                video_url=lesson_video_link,
                order=next_order,
                working_title=lesson_title,
                ai_clean_title=lesson_metadata.get('clean_title', lesson_title),
                ai_short_summary=lesson_metadata.get('short_summary', ''),
                ai_full_description=lesson_metadata.get('full_description', lesson_description_for_ai),
                ai_outcomes=lesson_metadata.get('outcomes', []),
                ai_coach_actions=lesson_metadata.get('coach_actions', []),
                content=lesson_content,
                ai_generation_status='generated',
            )

            try:
                quiz, _ = LessonQuiz.objects.get_or_create(
                    lesson=lesson,
                    defaults={
                        'tenant': lesson.tenant,
                        'title': f'{lesson_title} Quiz',
                        'passing_score': 70,
                        'is_required': True,
                    },
                )
                generate_ai_quiz(lesson, quiz, num_questions=5)
            except Exception as eq:
                print(f'[Background] Quiz generation failed for {lesson_title[:50]}: {eq}')

            if _send_lesson_to_chatbot_webhook(lesson):
                print(f'[Background] Chatbot trained for appended lesson: {lesson_title[:50]}')

            next_order += 1
            pct = min(95, 15 + int(80 * (idx + 1) / total_items))
            _update_ai_gen_progress(
                course.id,
                course.name,
                'creating_content',
                progress=pct,
                total=total_items,
                current=f'Added lesson: {lesson_title[:50]}',
            )

        _update_ai_gen_progress(course.id, course.name, 'completed', progress=100, total=total_items, current='Complete!')
    except Exception as e:
        _update_ai_gen_progress(course_id, f'Course #{course_id}', 'failed', progress=0, error=str(e))
        print(f'[Background] Error appending seed lessons for course #{course_id}: {str(e)}')


@staff_member_required
@require_http_methods(["POST"])
def dashboard_course_add_seed_lessons(request, course_slug):
    """Append multiple AI-generated lessons to an existing course."""
    tenant = _get_dashboard_tenant(request)
    if request.user.is_superuser:
        course = get_object_or_404(Course, slug=course_slug)
    else:
        if tenant is None:
            return JsonResponse({'success': False, 'error': 'Tenant context is required.'}, status=400)
        course = get_object_or_404(Course, slug=course_slug, tenant=tenant)

    seed_lessons = _parse_seed_lessons(request.POST.get('lessons_json'))
    if not seed_lessons:
        return JsonResponse({'success': False, 'error': 'Add at least one lesson with title and description.'}, status=400)

    module_id_raw = (request.POST.get('module_id') or '').strip()
    module_id = None
    if module_id_raw:
        try:
            module_id = int(module_id_raw)
        except ValueError:
            module_id = None

    courses_list = request.session.get('ai_generating_courses', [])
    if not isinstance(courses_list, list):
        courses_list = []
    if not any(isinstance(item, dict) and int(item.get('id') or 0) == int(course.id) for item in courses_list):
        courses_list.append({'id': course.id, 'name': course.name})
    request.session['ai_generating_courses'] = courses_list
    request.session.modified = True

    _update_ai_gen_progress(course.id, course.name, 'starting', progress=3, current='Queued lesson generation...')
    thread = threading.Thread(
        target=_append_seed_lessons_ai,
        args=(course.id, seed_lessons, module_id),
        daemon=True,
    )
    thread.start()

    return JsonResponse({
        'success': True,
        'course_id': course.id,
        'redirect_url': f'/dashboard/courses/{course.slug}/lessons/',
        'message': f'Started generating {len(seed_lessons)} lesson(s) for {course.name}.',
    })


@staff_member_required
def dashboard_add_course(request):
    """Add new course with optional AI generation"""
    tenant = _get_dashboard_tenant(request)
    if tenant is None:
        messages.error(request, 'Tenant context is required to create courses.')
        return redirect('dashboard_home')

    show_onboarding = False
    if request.GET.get('onboarding') == '1':
        show_onboarding = True
    elif request.session.get('highlight_course_creation_wizard'):
        show_onboarding = True
        del request.session['highlight_course_creation_wizard']
        request.session.modified = True

    if request.method == 'POST':
        show_onboarding = True
        blueprint = _parse_course_creation_blueprint(request.POST)
        seed_lessons = _parse_seed_lessons(request.POST.get('cf_seed_lessons_json'))
        name = (request.POST.get('name') or '').strip()
        if not name and blueprint.get('topic'):
            name = blueprint['topic'][:200]
        slug = generate_slug(name or 'course')
        if len(slug) > 200:
            slug = slug[:200].rstrip('-') or 'course'
        short_description = (request.POST.get('short_description') or '').strip()
        description = (request.POST.get('description') or '').strip()
        course_type = request.POST.get('course_type', 'sprint')
        status = request.POST.get('status', 'active')
        coach_name = request.POST.get('coach_name', 'Sprint Coach')
        use_ai = request.POST.get('use_ai') == 'on'
        raw_price = request.POST.get('price', '').strip()
        try:
            price = round(float(raw_price), 2) if raw_price else None
            if price is not None and price <= 0:
                price = None
        except (ValueError, TypeError):
            price = None
        enrollment_method = 'purchase' if price else request.POST.get('enrollment_method', 'open')

        ctx = {
            'course_formats': COURSEFORGE_FORMAT_CHOICES,
            'knowledge_levels': COURSEFORGE_LEVEL_CHOICES,
            'show_onboarding': show_onboarding,
        }

        if use_ai:
            quick_ai = request.POST.get('quick_ai') == '1'
            bp_errors = _validate_blueprint_for_ai(blueprint)
            forge_ok = not bool(bp_errors)
            legacy_ok = bool(name and short_description and description)

            if quick_ai:
                if not legacy_ok:
                    messages.error(
                        request,
                        'Quick AI requires course title, short description, and full description (step 2).',
                    )
                    return render(request, 'dashboard/add_course.html', ctx)
                blueprint_to_save = {}
            elif forge_ok:
                if not name:
                    messages.error(
                        request,
                        'Course title is required (step 2), or leave it blank to use your topic as the title.',
                    )
                    return render(request, 'dashboard/add_course.html', ctx)
                if not short_description:
                    short_description = _default_short_description_from_blueprint(blueprint)
                structured = _compose_description_from_blueprint(blueprint)
                if description:
                    description = f"{description.strip()}\n\n---\n\n{structured}"
                else:
                    description = structured
                blueprint_to_save = blueprint
            elif legacy_ok:
                # Classic three-field AI flow (same as pre-wizard): no blueprint, user description only
                blueprint_to_save = {}
            else:
                for err in bp_errors:
                    messages.error(request, err)
                messages.info(
                    request,
                    'Tip: use Quick AI on step 1 for the classic flow (title + descriptions only), '
                    'or fill the guided steps above.',
                )
                return render(request, 'dashboard/add_course.html', ctx)

            if seed_lessons:
                blueprint_to_save = blueprint_to_save or {}
                blueprint_to_save['seed_lessons'] = seed_lessons
        else:
            if not name or not short_description or not description:
                messages.error(request, 'Course name, short description, and full description are required when AI generation is off.')
                return render(request, 'dashboard/add_course.html', ctx)
            blueprint_to_save = {}

        # Ensure slug is unique
        base_slug = slug
        counter = 1
        while Course.objects.filter(tenant=tenant, slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        # Create course
        course = Course.objects.create(
            tenant=tenant,
            name=name,
            slug=slug,
            short_description=short_description[:1000],
            description=description,
            course_type=course_type,
            status=status,
            coach_name=coach_name,
            creation_blueprint=blueprint_to_save,
            price=price,
            enrollment_method=enrollment_method,
        )

        # Generate course structure with AI if requested (in background)
        if use_ai and description:
            # Append to list so floating widget can show stacked progress for multiple courses
            courses_list = request.session.get('ai_generating_courses', [])
            if not isinstance(courses_list, list):
                courses_list = []
            courses_list.append({'id': course.id, 'name': course.name})
            request.session['ai_generating_courses'] = courses_list
            request.session.modified = True
            # Initial progress before thread starts
            _update_ai_gen_progress(course.id, course.name, 'starting', progress=0, current='Starting...')
            thread = threading.Thread(
                target=_generate_course_ai_content,
                args=(course.id, name, description, course_type, coach_name),
                daemon=True
            )
            thread.start()
        else:
            messages.success(request, f'Course "{course.name}" has been created successfully.')

        return redirect('dashboard_courses')

    return render(request, 'dashboard/add_course.html', {
        'course_formats': COURSEFORGE_FORMAT_CHOICES,
        'knowledge_levels': COURSEFORGE_LEVEL_CHOICES,
        'show_onboarding': show_onboarding,
    })


@staff_member_required
def dashboard_lessons(request):
    """List all lessons across all courses"""
    tenant = _get_dashboard_tenant(request)
    lessons = Lesson.objects.select_related('course', 'module').order_by('course__name', 'module__order', 'order', 'id')
    if not request.user.is_superuser:
        if tenant is None:
            messages.error(request, 'Tenant context is required.')
            return redirect('dashboard_courses')
        lessons = lessons.filter(tenant=tenant)
    
    # Filtering
    status_filter = request.GET.get('status', 'all')
    if status_filter != 'all':
        lessons = lessons.filter(ai_generation_status=status_filter)
    
    course_filter = request.GET.get('course', '')
    if course_filter:
        lessons = lessons.filter(course_id=course_filter)
    
    courses = Course.objects.all() if request.user.is_superuser else Course.objects.filter(tenant=tenant)
    
    return render(request, 'dashboard/lessons.html', {
        'lessons': lessons,
        'courses': courses,
        'status_filter': status_filter,
        'course_filter': course_filter,
    })


@staff_member_required
@require_http_methods(["POST"])
def dashboard_delete_lesson(request, lesson_id):
    """Delete a lesson"""
    tenant = _get_dashboard_tenant(request)
    if request.user.is_superuser:
        lesson = get_object_or_404(Lesson, id=lesson_id)
    else:
        if tenant is None:
            messages.error(request, 'Tenant context is required.')
            return redirect('dashboard_lessons')
        lesson = get_object_or_404(Lesson, id=lesson_id, tenant=tenant)
    lesson_title = lesson.title
    course_slug = lesson.course.slug if lesson.course else None
    
    try:
        lesson.delete()
        messages.success(request, f'Lesson "{lesson_title}" has been deleted successfully.')
    except Exception as e:
        messages.error(request, f'Error deleting lesson: {str(e)}')
    
    # Redirect back to lessons list or course lessons if we have course info
    if course_slug:
        return redirect('dashboard_course_lessons', course_slug=course_slug)
    return redirect('dashboard_lessons')


@staff_member_required
def dashboard_upload_quiz(request):
    """Upload quiz from CSV/PDF file or generate with AI"""
    courses = Course.objects.all()
    lessons = Lesson.objects.select_related('course').order_by('-created_at')
    
    if request.method == 'POST':
        lesson_id = request.POST.get('lesson_id')
        generation_method = request.POST.get('generation_method', 'upload')  # 'upload' or 'ai'
        
        if not lesson_id:
            messages.error(request, 'Please select a lesson.')
            return render(request, 'dashboard/upload_quiz.html', {
                'courses': courses,
                'lessons': lessons,
                'openai_available': OPENAI_AVAILABLE,
            })
        
        lesson = get_object_or_404(Lesson, id=lesson_id)
        
        try:
            # Get or create quiz
            quiz, created = LessonQuiz.objects.get_or_create(
                lesson=lesson,
                defaults={
                    'tenant': lesson.tenant,
                    'title': f'{lesson.title} Quiz',
                    'passing_score': 70,
                },
            )
            
            questions_created = 0
            
            if generation_method == 'ai':
                # Generate quiz using AI
                num_questions = int(request.POST.get('num_questions', 5))
                questions_created = generate_ai_quiz(lesson, quiz, num_questions)
            else:
                # Upload from file
                uploaded_file = request.FILES.get('quiz_file')
                if not uploaded_file:
                    messages.error(request, 'Please select a file to upload.')
                    return render(request, 'dashboard/upload_quiz.html', {
                        'courses': courses,
                        'lessons': lessons,
                        'openai_available': OPENAI_AVAILABLE,
                    })
                
                file_extension = uploaded_file.name.split('.')[-1].lower()
                
                if file_extension == 'csv':
                    questions_created = parse_csv_quiz(uploaded_file, quiz)
                elif file_extension == 'pdf':
                    if not PDF_AVAILABLE:
                        messages.error(request, 'PDF parsing is not available. Please install PyMuPDF.')
                        return render(request, 'dashboard/upload_quiz.html', {
                            'courses': courses,
                            'lessons': lessons,
                            'openai_available': OPENAI_AVAILABLE,
                        })
                    questions_created = parse_pdf_quiz(uploaded_file, quiz)
                else:
                    messages.error(request, f'Unsupported file format: {file_extension}. Please upload a CSV or PDF file.')
                    return render(request, 'dashboard/upload_quiz.html', {
                        'courses': courses,
                        'lessons': lessons,
                        'openai_available': OPENAI_AVAILABLE,
                    })
            
            if questions_created > 0:
                messages.success(request, f'Successfully created {questions_created} quiz question(s) for "{lesson.title}".')
                return redirect('dashboard_lesson_quiz', lesson_id=lesson.id)
            else:
                messages.warning(request, 'No questions were created. Please check your file format or lesson content.')
        
        except Exception as e:
            messages.error(request, f'Error processing: {str(e)}')
    
    return render(request, 'dashboard/upload_quiz.html', {
        'courses': courses,
        'lessons': lessons,
        'openai_available': OPENAI_AVAILABLE,
    })


def parse_csv_quiz(uploaded_file, quiz):
    """Parse CSV file and create quiz questions"""
    # Read the file
    file_content = uploaded_file.read().decode('utf-8')
    csv_reader = csv.DictReader(io.StringIO(file_content))
    
    questions_created = 0
    max_order = quiz.questions.aggregate(models.Max('order'))['order__max'] or 0
    
    for row_num, row in enumerate(csv_reader, start=1):
        try:
            # Expected CSV format: question, option_a, option_b, option_c, option_d, correct_answer
            question_text = row.get('question', '').strip()
            if not question_text:
                continue
            
            option_a = row.get('option_a', '').strip()
            option_b = row.get('option_b', '').strip()
            option_c = row.get('option_c', '').strip()
            option_d = row.get('option_d', '').strip()
            correct_answer = row.get('correct_answer', 'A').strip().upper()
            
            if not option_a or not option_b:
                continue
            
            # Validate correct_answer
            if correct_answer not in ['A', 'B', 'C', 'D']:
                correct_answer = 'A'
            
            # Create question
            LessonQuizQuestion.objects.create(
                quiz=quiz,
                text=question_text,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c if option_c else '',
                option_d=option_d if option_d else '',
                correct_option=correct_answer,
                order=max_order + row_num,
            )
            questions_created += 1
        except Exception as e:
            # Skip rows with errors but continue processing
            continue
    
    return questions_created


def generate_ai_quiz(lesson, quiz, num_questions=5):
    """Generate quiz questions using AI based on lesson content"""
    if not OPENAI_AVAILABLE:
        raise Exception('OpenAI is not available. Please install the openai package.')
    
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise Exception('OPENAI_API_KEY not found in environment variables.')
    
    try:
        client = OpenAI(api_key=api_key)
        
        # Gather lesson content for AI context
        lesson_content = []
        if lesson.title:
            lesson_content.append(f"Lesson Title: {lesson.title}")
        if lesson.description:
            lesson_content.append(f"Description: {lesson.description}")
        if lesson.transcription:
            lesson_content.append(f"Transcription: {lesson.transcription[:2000]}")  # Limit transcription length
        if lesson.ai_full_description:
            lesson_content.append(f"Full Description: {lesson.ai_full_description}")
        
        if not lesson_content:
            raise Exception('Lesson does not have enough content for AI generation. Please add a description or transcription.')
        
        content_text = "\n\n".join(lesson_content)
        
        # Create prompt for AI
        prompt = f"""Based on the following lesson content, generate {num_questions} multiple-choice quiz questions.

Lesson Content:
{content_text}

Generate {num_questions} quiz questions with the following format:
- Each question should test understanding of key concepts from the lesson
- Each question should have 4 options (A, B, C, D)
- One option should be clearly correct
- The other options should be plausible but incorrect
- Questions should vary in difficulty

Return the questions in JSON format:
{{
  "questions": [
    {{
      "question": "Question text here",
      "option_a": "Option A text",
      "option_b": "Option B text",
      "option_c": "Option C text",
      "option_d": "Option D text",
      "correct_answer": "A"
    }}
  ]
}}

Only return valid JSON, no additional text."""
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates educational quiz questions. Always return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        _log_openai_usage(
            feature='lesson_quiz',
            response=response,
            tenant=lesson.tenant,
            course=lesson.course,
            lesson=lesson,
            model_name='gpt-4o-mini',
        )
        
        # Parse response
        response_text = response.choices[0].message.content.strip()
        
        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
            response_text = response_text.strip()
        if response_text.endswith('```'):
            response_text = response_text.rsplit('```', 1)[0].strip()
        
        # Parse JSON
        try:
            quiz_data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                quiz_data = json.loads(json_match.group())
            else:
                raise Exception('Failed to parse AI response as JSON.')
        
        # Create quiz questions
        questions_created = 0
        max_order = quiz.questions.aggregate(models.Max('order'))['order__max'] or 0
        
        for idx, q_data in enumerate(quiz_data.get('questions', []), start=1):
            try:
                question_text = q_data.get('question', '').strip()
                option_a = q_data.get('option_a', '').strip()
                option_b = q_data.get('option_b', '').strip()
                option_c = q_data.get('option_c', '').strip()
                option_d = q_data.get('option_d', '').strip()
                correct_answer = q_data.get('correct_answer', 'A').strip().upper()
                
                if not question_text or not option_a or not option_b:
                    continue
                
                if correct_answer not in ['A', 'B', 'C', 'D']:
                    correct_answer = 'A'
                
                LessonQuizQuestion.objects.create(
                    quiz=quiz,
                    text=question_text,
                    option_a=option_a,
                    option_b=option_b,
                    option_c=option_c if option_c else '',
                    option_d=option_d if option_d else '',
                    correct_option=correct_answer,
                    order=max_order + idx,
                )
                questions_created += 1
            except Exception as e:
                continue
        
        return questions_created
    
    except Exception as e:
        raise Exception(f'AI generation failed: {str(e)}')


def generate_ai_exam(course, exam, num_questions=20):
    """Generate final exam questions using AI based on full course content."""
    if not OPENAI_AVAILABLE:
        raise Exception('OpenAI is not available.')
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise Exception('OPENAI_API_KEY not found.')
    lessons = course.lessons.select_related('module').order_by('module__order', 'order')
    lesson_content = []
    lesson_content.append(f"Course: {course.name}")
    lesson_content.append(f"Description: {course.description[:1500]}")
    for lesson in lessons:
        block = [f"Lesson: {lesson.title}"]
        if lesson.ai_full_description:
            block.append(lesson.ai_full_description[:800])
        elif lesson.description:
            block.append(lesson.description[:800])
        content = lesson.content if isinstance(lesson.content, dict) else {}
        for b in content.get('blocks', [])[:5]:
            d = b.get('data', {})
            if b.get('type') == 'paragraph' and d.get('text'):
                block.append(d['text'][:300])
        lesson_content.append('\n'.join(block))
    content_text = '\n\n---\n\n'.join(lesson_content)
    prompt = f"""Based on this entire course content, generate {num_questions} multiple-choice final exam questions.

Course Content:
{content_text}

Generate {num_questions} questions that test understanding across the whole course. Each question should have 4 options (A, B, C, D), one correct answer. Return JSON only:
{{
  "questions": [
    {{"question": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "correct_answer": "A"}}
  ]
}}"""
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You create educational exam questions. Return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4000,
        )
        _log_openai_usage(
            feature='course_exam',
            response=response,
            tenant=course.tenant,
            course=course,
            model_name='gpt-4o-mini',
        )
        text = response.choices[0].message.content.strip()
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
            text = text.strip()
        data = json.loads(text)
        created = 0
        for idx, q in enumerate(data.get('questions', []), 1):
            qt = q.get('question', '').strip()
            a, b = q.get('option_a', '').strip(), q.get('option_b', '').strip()
            if not qt or not a or not b:
                continue
            corr = (q.get('correct_answer', 'A') or 'A').strip().upper()
            if corr not in ('A', 'B', 'C', 'D'):
                corr = 'A'
            ExamQuestion.objects.create(
                exam=exam,
                text=qt,
                option_a=a,
                option_b=b,
                option_c=q.get('option_c', '').strip() or '',
                option_d=q.get('option_d', '').strip() or '',
                correct_option=corr,
                order=idx,
            )
            created += 1
        return created
    except Exception as e:
        raise Exception(f'AI exam generation failed: {str(e)}')


def parse_pdf_quiz(uploaded_file, quiz):
    """Parse PDF file and create quiz questions"""
    # Read PDF content
    pdf_bytes = uploaded_file.read()
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    text_content = ""
    for page in pdf_doc:
        text_content += page.get_text()
    
    pdf_doc.close()
    
    # Try to parse questions from PDF text
    # Expected format: Questions should be numbered (1., 2., etc.) with options A, B, C, D
    questions_created = 0
    max_order = quiz.questions.aggregate(models.Max('order'))['order__max'] or 0
    
    # Split by question numbers (1., 2., etc.)
    question_pattern = r'(\d+\.\s+.*?)(?=\d+\.|$)'
    questions_text = re.findall(question_pattern, text_content, re.DOTALL | re.IGNORECASE)
    
    for idx, question_block in enumerate(questions_text, start=1):
        try:
            lines = [line.strip() for line in question_block.split('\n') if line.strip()]
            if len(lines) < 3:  # Need at least question + 2 options
                continue
            
            question_text = lines[0].lstrip('0123456789. ').strip()
            if not question_text:
                continue
            
            # Extract options (looking for A., B., C., D. patterns)
            options = {}
            current_option = None
            option_text = []
            
            for line in lines[1:]:
                # Check if line starts with option letter
                option_match = re.match(r'^([A-D])[\.\)]\s*(.*)$', line, re.IGNORECASE)
                if option_match:
                    # Save previous option if exists
                    if current_option:
                        options[current_option] = ' '.join(option_text).strip()
                    current_option = option_match.group(1).upper()
                    option_text = [option_match.group(2)]
                elif current_option:
                    option_text.append(line)
            
            # Save last option
            if current_option:
                options[current_option] = ' '.join(option_text).strip()
            
            # Need at least A and B options
            if 'A' not in options or 'B' not in options:
                continue
            
            # Determine correct answer (look for "Answer:" or "Correct:" patterns)
            correct_answer = 'A'  # Default
            for line in lines:
                answer_match = re.search(r'(?:answer|correct)[:\s]+([A-D])', line, re.IGNORECASE)
                if answer_match:
                    correct_answer = answer_match.group(1).upper()
                    break
            
            # Create question
            LessonQuizQuestion.objects.create(
                quiz=quiz,
                text=question_text,
                option_a=options.get('A', ''),
                option_b=options.get('B', ''),
                option_c=options.get('C', ''),
                option_d=options.get('D', ''),
                correct_option=correct_answer if correct_answer in ['A', 'B', 'C', 'D'] else 'A',
                order=max_order + idx,
            )
            questions_created += 1
        except Exception as e:
            # Skip questions with errors
            continue
    
    return questions_created


@staff_member_required
def dashboard_add_lesson(request):
    """Add new lesson - redirects to creator flow"""
    course_id = request.GET.get('course')
    if course_id:
        course = get_object_or_404(Course, id=course_id)
        return redirect('add_lesson', course_slug=course.slug)
    
    courses = Course.objects.all()
    return render(request, 'dashboard/select_course.html', {
        'courses': courses,
    })


@staff_member_required
def dashboard_edit_lesson(request, lesson_id):
    """Edit lesson - redirects to AI generation page"""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    return redirect('generate_lesson_ai', course_slug=lesson.course.slug, lesson_id=lesson.id)


@staff_member_required
def dashboard_student_progress(request):
    """Student progress overview - all students"""
    # Get filter parameters
    course_filter = request.GET.get('course', '')
    search_query = request.GET.get('search', '')
    
    # Get all enrollments
    enrollments = CourseEnrollment.objects.select_related('user', 'course').all()
    
    # Apply filters
    if course_filter:
        enrollments = enrollments.filter(course_id=course_filter)
    
    if search_query:
        enrollments = enrollments.filter(
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(course__name__icontains=search_query)
        )
    
    # Calculate progress for each enrollment
    enrollment_data = []
    for enrollment in enrollments:
        total_lessons = enrollment.course.lessons.count()
        completed_lessons = UserProgress.objects.filter(
            user=enrollment.user,
            lesson__course=enrollment.course,
            completed=True
        ).count()
        
        progress_percentage = int((completed_lessons / total_lessons * 100)) if total_lessons > 0 else 0
        
        # Get certification status
        try:
            cert = Certification.objects.get(user=enrollment.user, course=enrollment.course)
            cert_status = cert.get_status_display()
        except Certification.DoesNotExist:
            cert_status = 'Not Eligible' if progress_percentage < 100 else 'Eligible'
        
        enrollment_data.append({
            'enrollment': enrollment,
            'total_lessons': total_lessons,
            'completed_lessons': completed_lessons,
            'progress_percentage': progress_percentage,
            'cert_status': cert_status,
        })
    
    courses = Course.objects.all()
    
    return render(request, 'dashboard/student_progress.html', {
        'enrollment_data': enrollment_data,
        'courses': courses,
        'course_filter': course_filter,
        'search_query': search_query,
    })


@staff_member_required
def dashboard_student_detail(request, user_id, course_slug=None):
    """Detailed student progress view"""
    user = get_object_or_404(User, id=user_id)
    
    if course_slug:
        course = get_object_or_404(Course, slug=course_slug)
        courses = [course]
    else:
        # Get all courses the user is enrolled in
        courses = Course.objects.filter(enrollments__user=user).distinct()
    
    course_data = []
    for course in courses:
        enrollment = CourseEnrollment.objects.filter(user=user, course=course).first()
        
        # Get all lessons with progress
        lessons = course.lessons.order_by('order', 'id')
        lesson_progress = []
        
        for lesson in lessons:
            progress = UserProgress.objects.filter(user=user, lesson=lesson).first()
            lesson_progress.append({
                'lesson': lesson,
                'progress': progress,
                'watch_percentage': progress.video_watch_percentage if progress else 0,
                'status': progress.status if progress else 'not_started',
                'completed': progress.completed if progress else False,
            })
        
        # Get exam attempts
        exam_attempts = []
        try:
            exam = Exam.objects.get(course=course)
            exam_attempts = ExamAttempt.objects.filter(user=user, exam=exam).order_by('-started_at')
        except Exam.DoesNotExist:
            pass
        
        # Get certification
        try:
            certification = Certification.objects.get(user=user, course=course)
        except Certification.DoesNotExist:
            certification = None
        
        course_data.append({
            'course': course,
            'enrollment': enrollment,
            'lesson_progress': lesson_progress,
            'exam_attempts': exam_attempts,
            'certification': certification,
        })
    
    # Get all course access records for this student
    from .models import CourseAccess
    course_accesses = CourseAccess.objects.filter(user=user).select_related('course', 'bundle_purchase', 'cohort', 'granted_by', 'revoked_by').order_by('-granted_at')
    
    # Get bundles and cohorts for access management
    from .models import Bundle, Cohort
    bundles = Bundle.objects.filter(is_active=True)
    cohorts = Cohort.objects.filter(is_active=True)
    all_courses = Course.objects.filter(status='active')
    
    return render(request, 'dashboard/student_detail.html', {
        'student': user,
        'course_data': course_data,
        'course_accesses': course_accesses,
        'bundles': bundles,
        'cohorts': cohorts,
        'courses': all_courses,
    })


@staff_member_required
def dashboard_course_progress(request, course_slug):
    """View all student progress for a specific course"""
    course = get_object_or_404(Course, slug=course_slug)
    
    # Get all enrollments for this course
    enrollments = CourseEnrollment.objects.filter(course=course).select_related('user')
    
    # Calculate progress for each student
    student_progress = []
    for enrollment in enrollments:
        total_lessons = course.lessons.count()
        completed_lessons = UserProgress.objects.filter(
            user=enrollment.user,
            lesson__course=course,
            completed=True
        ).count()
        
        # Get average video watch percentage
        avg_watch = UserProgress.objects.filter(
            user=enrollment.user,
            lesson__course=course
        ).aggregate(avg=Avg('video_watch_percentage'))['avg'] or 0
        
        # Get exam attempts
        exam_attempts_count = 0
        passed_exam = False
        try:
            exam = Exam.objects.get(course=course)
            exam_attempts = ExamAttempt.objects.filter(user=enrollment.user, exam=exam)
            exam_attempts_count = exam_attempts.count()
            passed_exam = exam_attempts.filter(passed=True).exists()
        except Exam.DoesNotExist:
            pass
        
        # Get certification status
        try:
            cert = Certification.objects.get(user=enrollment.user, course=course)
            cert_status = cert.get_status_display()
        except Certification.DoesNotExist:
            cert_status = 'Not Eligible' if completed_lessons < total_lessons else 'Eligible'
        
        student_progress.append({
            'user': enrollment.user,
            'enrollment': enrollment,
            'total_lessons': total_lessons,
            'completed_lessons': completed_lessons,
            'progress_percentage': int((completed_lessons / total_lessons * 100)) if total_lessons > 0 else 0,
            'avg_watch_percentage': round(avg_watch, 1),
            'exam_attempts': exam_attempts_count,
            'passed_exam': passed_exam,
            'cert_status': cert_status,
        })
    
    # Sort by progress percentage (descending)
    student_progress.sort(key=lambda x: x['progress_percentage'], reverse=True)
    
    return render(request, 'dashboard/course_progress.html', {
        'course': course,
        'student_progress': student_progress,
    })


# ========== ACCESS MANAGEMENT VIEWS ==========

@staff_member_required
@require_http_methods(["POST"])
def grant_course_access_view(request, user_id):
    """Grant course access to a student"""
    user = get_object_or_404(User, id=user_id)
    from .utils.access import grant_course_access
    from django.utils import timezone
    from datetime import timedelta
    
    course_id = request.POST.get('course_id')
    access_type = request.POST.get('access_type', 'manual')
    expires_in_days = request.POST.get('expires_in_days', '')
    notes = request.POST.get('notes', '')
    
    if not course_id:
        return JsonResponse({'success': False, 'error': 'Course ID required'}, status=400)
    
    course = get_object_or_404(Course, id=course_id)
    
    # Calculate expiration
    expires_at = None
    if expires_in_days:
        try:
            days = int(expires_in_days)
            expires_at = timezone.now() + timedelta(days=days)
        except ValueError:
            pass
    
    # Grant access
    access = grant_course_access(
        user=user,
        course=course,
        access_type=access_type,
        granted_by=request.user,
        expires_at=expires_at,
        notes=notes
    )
    
    return JsonResponse({
        'success': True,
        'message': f'Access granted to {course.name}',
        'access_id': access.id
    })


@staff_member_required
@require_http_methods(["POST"])
def revoke_course_access_view(request, user_id):
    """Revoke course access from a student"""
    user = get_object_or_404(User, id=user_id)
    from .utils.access import revoke_course_access
    
    course_id = request.POST.get('course_id')
    reason = request.POST.get('reason', '')
    notes = request.POST.get('notes', '')
    
    if not course_id:
        return JsonResponse({'success': False, 'error': 'Course ID required'}, status=400)
    
    course = get_object_or_404(Course, id=course_id)
    
    # Revoke access
    access = revoke_course_access(
        user=user,
        course=course,
        revoked_by=request.user,
        reason=reason,
        notes=notes
    )
    
    if access:
        return JsonResponse({
            'success': True,
            'message': f'Access revoked for {course.name}'
        })
    else:
        return JsonResponse({
            'success': False,
            'error': 'No active access found to revoke'
        }, status=400)


@staff_member_required
@require_http_methods(["POST"])
def grant_bundle_access_view(request, user_id):
    """Grant bundle access to a student"""
    user = get_object_or_404(User, id=user_id)
    from .utils.access import grant_bundle_access
    
    bundle_id = request.POST.get('bundle_id')
    purchase_id = request.POST.get('purchase_id', '')
    notes = request.POST.get('notes', '')
    
    if not bundle_id:
        return JsonResponse({'success': False, 'error': 'Bundle ID required'}, status=400)
    
    bundle = get_object_or_404(Bundle, id=bundle_id)
    
    # Create bundle purchase
    bundle_purchase = BundlePurchase.objects.create(
        user=user,
        bundle=bundle,
        purchase_id=purchase_id,
        notes=notes
    )
    
    # Grant access to all courses in bundle
    granted_accesses = grant_bundle_access(user, bundle_purchase)
    
    return JsonResponse({
        'success': True,
        'message': f'Bundle access granted - {len(granted_accesses)} courses unlocked',
        'bundle_purchase_id': bundle_purchase.id
    })


@staff_member_required
@require_http_methods(["POST"])
def add_to_cohort_view(request, user_id):
    """Add student to a cohort"""
    user = get_object_or_404(User, id=user_id)
    
    cohort_id = request.POST.get('cohort_id')
    if not cohort_id:
        return JsonResponse({'success': False, 'error': 'Cohort ID required'}, status=400)
    
    cohort = get_object_or_404(Cohort, id=cohort_id)
    
    # Add to cohort
    member, created = CohortMember.objects.get_or_create(
        user=user,
        cohort=cohort,
        defaults={'tenant': cohort.tenant}
    )
    
    if created:
        # Grant access to courses associated with cohort (if any)
        # Note: This requires adding a many-to-many relationship between Cohort and Course
        # For now, we'll just add them to the cohort
        message = f'Added to cohort: {cohort.name}'
    else:
        message = f'Already in cohort: {cohort.name}'
    
    return JsonResponse({
        'success': True,
        'message': message
    })


@staff_member_required
def bulk_access_management(request):
    """Bulk access management page"""
    # Get all active courses, bundles, and cohorts
    courses = Course.objects.filter(status='active')
    bundles = Bundle.objects.filter(is_active=True)
    cohorts = Cohort.objects.filter(is_active=True)
    
    # Get all users (for selection)
    users = User.objects.all().order_by('username')
    
    return render(request, 'dashboard/bulk_access.html', {
        'courses': courses,
        'bundles': bundles,
        'cohorts': cohorts,
        'users': users,
    })


@staff_member_required
@require_http_methods(["POST"])
def bulk_grant_access_view(request):
    """Bulk grant course access to multiple students"""
    from .utils.access import grant_course_access
    from django.utils import timezone
    from datetime import timedelta
    
    user_ids = request.POST.getlist('user_ids[]')
    course_ids = request.POST.getlist('course_ids[]')
    access_type = request.POST.get('access_type', 'manual')
    expires_in_days = request.POST.get('expires_in_days', '')
    notes = request.POST.get('notes', '')
    
    if not user_ids or not course_ids:
        return JsonResponse({'success': False, 'error': 'Users and courses required'}, status=400)
    
    # Calculate expiration
    expires_at = None
    if expires_in_days:
        try:
            days = int(expires_in_days)
            expires_at = timezone.now() + timedelta(days=days)
        except ValueError:
            pass
    
    granted_count = 0
    for user_id in user_ids:
        try:
            user = User.objects.get(id=user_id)
            for course_id in course_ids:
                try:
                    course = Course.objects.get(id=course_id)
                    # Check if access already exists
                    existing = CourseAccess.objects.filter(
                        user=user,
                        course=course,
                        status='unlocked'
                    ).first()
                    if not existing:
                        grant_course_access(
                            user=user,
                            course=course,
                            access_type=access_type,
                            granted_by=request.user,
                            expires_at=expires_at,
                            notes=notes
                        )
                        granted_count += 1
                except Course.DoesNotExist:
                    continue
        except User.DoesNotExist:
            continue
    
    return JsonResponse({
        'success': True,
        'message': f'Granted {granted_count} access records',
        'granted_count': granted_count
    })


@staff_member_required
def dashboard_analytics(request):
    """Comprehensive analytics dashboard"""
    from datetime import timedelta
    
    # Date ranges
    now = timezone.now()
    last_7_days = now - timedelta(days=7)
    last_30_days = now - timedelta(days=30)
    last_90_days = now - timedelta(days=90)
    
    # Student Analytics
    total_students = User.objects.filter(is_staff=False, is_superuser=False).count()
    active_students = User.objects.filter(
        is_staff=False, is_superuser=False,
        last_login__gte=last_30_days
    ).count()
    new_students_7d = User.objects.filter(
        is_staff=False, is_superuser=False,
        date_joined__gte=last_7_days
    ).count()
    new_students_30d = User.objects.filter(
        is_staff=False, is_superuser=False,
        date_joined__gte=last_30_days
    ).count()
    inactive_students = User.objects.filter(
        is_staff=False, is_superuser=False,
        last_login__lt=last_90_days
    ).count()
    
    # Enrollment Analytics
    total_enrollments = CourseEnrollment.objects.count()
    enrollments_7d = CourseEnrollment.objects.filter(enrolled_at__gte=last_7_days).count()
    enrollments_30d = CourseEnrollment.objects.filter(enrolled_at__gte=last_30_days).count()
    
    # Access Analytics
    total_accesses = CourseAccess.objects.filter(status='unlocked').count()
    expired_accesses = CourseAccess.objects.filter(status='expired').count()
    pending_accesses = CourseAccess.objects.filter(status='pending').count()
    
    # Progress Analytics
    total_progress = UserProgress.objects.count()
    completed_lessons = UserProgress.objects.filter(completed=True).count()
    progress_7d = UserProgress.objects.filter(last_accessed__gte=last_7_days).count()
    completion_rate = (completed_lessons / total_progress * 100) if total_progress > 0 else 0
    
    # Certification Analytics
    total_certifications = Certification.objects.count()
    certifications_7d = Certification.objects.filter(
        issued_at__gte=last_7_days
    ).count() if Certification.objects.filter(issued_at__isnull=False).exists() else 0
    certifications_30d = Certification.objects.filter(
        issued_at__gte=last_30_days
    ).count() if Certification.objects.filter(issued_at__isnull=False).exists() else 0
    
    # Course Performance Detailed
    course_performance_detailed = []
    for course in Course.objects.all():
        enrollments = CourseEnrollment.objects.filter(course=course).count()
        accesses = CourseAccess.objects.filter(course=course, status='unlocked').count()
        total_students_course = enrollments + accesses
        
        total_lessons_course = course.lessons.count()
        completed = UserProgress.objects.filter(
            lesson__course=course,
            completed=True
        ).count()
        total_possible = total_lessons_course * total_students_course
        course_completion_rate = (completed / total_possible * 100) if total_possible > 0 else 0
        
        certifications_course = Certification.objects.filter(course=course, status='passed').count()
        
        # Recent activity
        recent_enrollments = CourseEnrollment.objects.filter(
            course=course,
            enrolled_at__gte=last_7_days
        ).count()
        
        course_performance_detailed.append({
            'course': course,
            'total_students': total_students_course,
            'completion_rate': min(course_completion_rate, 100),
            'certifications': certifications_course,
            'lessons': total_lessons_course,
            'recent_enrollments': recent_enrollments,
            'completed_lessons': completed,
        })
    
    # Sort by total students
    course_performance_detailed.sort(key=lambda x: x['total_students'], reverse=True)
    
    # Enrollment trend (last 30 days)
    enrollment_trend = []
    for i in range(30, 0, -1):
        date = now - timedelta(days=i)
        count = CourseEnrollment.objects.filter(
            enrolled_at__date=date.date()
        ).count()
        enrollment_trend.append({
            'date': date.strftime('%m/%d'),
            'count': count
        })
    
    # Certification trend (last 30 days)
    certification_trend = []
    if Certification.objects.filter(issued_at__isnull=False).exists():
        for i in range(30, 0, -1):
            date = now - timedelta(days=i)
            count = Certification.objects.filter(
                issued_at__date=date.date()
            ).count()
            certification_trend.append({
                'date': date.strftime('%m/%d'),
                'count': count
            })
    
    # Top performing courses
    top_courses = sorted(course_performance_detailed, key=lambda x: x['total_students'], reverse=True)[:5]
    
    # Most active students
    active_students_list = User.objects.filter(
        is_staff=False, is_superuser=False
    ).annotate(
        progress_count=Count('progress', filter=Q(progress__last_accessed__gte=last_7_days))
    ).filter(progress_count__gt=0).order_by('-progress_count')[:10]
    
    # Additional Phase 1 Analytics
    
    # Students with zero progress
    students_with_progress = UserProgress.objects.values_list('user_id', flat=True).distinct()
    students_zero_progress = User.objects.filter(
        is_staff=False, is_superuser=False
    ).exclude(id__in=students_with_progress).count()
    
    # Students who completed at least one course
    students_with_completions = UserProgress.objects.filter(
        completed=True
    ).values_list('user_id', flat=True).distinct().count()
    
    # Average lessons completed per student
    total_lessons_completed = UserProgress.objects.filter(completed=True).count()
    avg_lessons_per_student = round(total_lessons_completed / total_students, 1) if total_students > 0 else 0
    
    # Course completion rates by course type
    course_type_stats = {}
    for course_type, _ in Course.COURSE_TYPES:
        courses_of_type = Course.objects.filter(course_type=course_type)
        total_enrollments_type = CourseEnrollment.objects.filter(course__in=courses_of_type).count()
        total_accesses_type = CourseAccess.objects.filter(course__in=courses_of_type, status='unlocked').count()
        total_students_type = total_enrollments_type + total_accesses_type
        
        total_lessons_type = sum(c.lessons.count() for c in courses_of_type)
        completed_lessons_type = UserProgress.objects.filter(
            lesson__course__in=courses_of_type,
            completed=True
        ).count()
        completion_rate_type = (completed_lessons_type / (total_lessons_type * total_students_type * 100)) if total_students_type > 0 and total_lessons_type > 0 else 0
        
        course_type_stats[course_type] = {
            'total_courses': courses_of_type.count(),
            'total_students': total_students_type,
            'completion_rate': min(completion_rate_type * 100, 100),
        }
    
    # Certification rate (certifications / eligible students)
    students_with_all_lessons = []
    for course in Course.objects.all():
        total_lessons = course.lessons.count()
        if total_lessons > 0:
            enrollments = CourseEnrollment.objects.filter(course=course)
            accesses = CourseAccess.objects.filter(course=course, status='unlocked')
            for enrollment in enrollments:
                completed = UserProgress.objects.filter(
                    user=enrollment.user,
                    lesson__course=course,
                    completed=True
                ).count()
                if completed >= total_lessons:
                    students_with_all_lessons.append((enrollment.user.id, course.id))
            for access in accesses:
                completed = UserProgress.objects.filter(
                    user=access.user,
                    lesson__course=course,
                    completed=True
                ).count()
                if completed >= total_lessons:
                    students_with_all_lessons.append((access.user.id, course.id))
    
    eligible_students_count = len(set(students_with_all_lessons))
    certification_rate = (total_certifications / eligible_students_count * 100) if eligible_students_count > 0 else 0
    
    # Trophy distribution
    trophy_distribution = {
        'bronze': 0,  # 1 certification
        'silver': 0,  # 3 certifications
        'gold': 0,    # 5 certifications
        'platinum': 0, # 8 certifications
        'diamond': 0,  # 12 certifications
        'ultimate': 0  # 20 certifications
    }
    for user in User.objects.filter(is_staff=False, is_superuser=False):
        cert_count = Certification.objects.filter(user=user, status='passed').count()
        if cert_count >= 20:
            trophy_distribution['ultimate'] += 1
        elif cert_count >= 12:
            trophy_distribution['diamond'] += 1
        elif cert_count >= 8:
            trophy_distribution['platinum'] += 1
        elif cert_count >= 5:
            trophy_distribution['gold'] += 1
        elif cert_count >= 3:
            trophy_distribution['silver'] += 1
        elif cert_count >= 1:
            trophy_distribution['bronze'] += 1
    
    # Exam & Quiz Analytics
    total_exam_attempts = ExamAttempt.objects.count()
    passed_exams = ExamAttempt.objects.filter(passed=True).count()
    exam_pass_rate = (passed_exams / total_exam_attempts * 100) if total_exam_attempts > 0 else 0
    avg_exam_score = ExamAttempt.objects.aggregate(Avg('score'))['score__avg'] or 0
    
    total_quiz_attempts = LessonQuizAttempt.objects.count()
    passed_quizzes = LessonQuizAttempt.objects.filter(passed=True).count()
    quiz_pass_rate = (passed_quizzes / total_quiz_attempts * 100) if total_quiz_attempts > 0 else 0
    avg_quiz_score = LessonQuizAttempt.objects.aggregate(Avg('score'))['score__avg'] or 0
    
    # Access Source Analytics
    access_by_method = {
        'enrollment': CourseEnrollment.objects.count(),
        'course_access': CourseAccess.objects.filter(status='unlocked').count(),
        'bundle': BundlePurchase.objects.count(),
        'cohort': CohortMember.objects.count(),
    }
    
    # Drop-off analysis (students who started but didn't complete)
    students_who_started = set()
    students_who_completed = set()
    for course in Course.objects.all():
        enrollments = CourseEnrollment.objects.filter(course=course)
        accesses = CourseAccess.objects.filter(course=course, status='unlocked')
        total_lessons = course.lessons.count()
        
        for enrollment in enrollments:
            students_who_started.add(enrollment.user.id)
            completed = UserProgress.objects.filter(
                user=enrollment.user,
                lesson__course=course,
                completed=True
            ).count()
            if completed >= total_lessons and total_lessons > 0:
                students_who_completed.add(enrollment.user.id)
        
        for access in accesses:
            students_who_started.add(access.user.id)
            completed = UserProgress.objects.filter(
                user=access.user,
                lesson__course=course,
                completed=True
            ).count()
            if completed >= total_lessons and total_lessons > 0:
                students_who_completed.add(access.user.id)
    
    drop_off_count = len(students_who_started) - len(students_who_completed)
    drop_off_rate = (drop_off_count / len(students_who_started) * 100) if len(students_who_started) > 0 else 0
    
    return render(request, 'dashboard/analytics.html', {
        # Student metrics
        'total_students': total_students,
        'active_students': active_students,
        'new_students_7d': new_students_7d,
        'new_students_30d': new_students_30d,
        'inactive_students': inactive_students,
        
        # Enrollment metrics
        'total_enrollments': total_enrollments,
        'enrollments_7d': enrollments_7d,
        'enrollments_30d': enrollments_30d,
        
        # Access metrics
        'total_accesses': total_accesses,
        'expired_accesses': expired_accesses,
        'pending_accesses': pending_accesses,
        
        # Progress metrics
        'total_progress': total_progress,
        'completed_lessons': completed_lessons,
        'progress_7d': progress_7d,
        'completion_rate': round(completion_rate, 1),
        
        # Certification metrics
        'total_certifications': total_certifications,
        'certifications_7d': certifications_7d,
        'certifications_30d': certifications_30d,
        
        # Detailed data
        'course_performance': course_performance_detailed,
        'enrollment_trend': enrollment_trend,
        'certification_trend': certification_trend,
        'top_courses': top_courses,
        'active_students_list': active_students_list,
        
        # Additional Phase 1 Analytics
        'students_zero_progress': students_zero_progress,
        'students_with_completions': students_with_completions,
        'avg_lessons_per_student': avg_lessons_per_student,
        'course_type_stats': course_type_stats,
        'certification_rate': round(certification_rate, 1),
        'trophy_distribution': trophy_distribution,
        'total_exam_attempts': total_exam_attempts,
        'passed_exams': passed_exams,
        'exam_pass_rate': round(exam_pass_rate, 1),
        'avg_exam_score': round(avg_exam_score, 1),
        'total_quiz_attempts': total_quiz_attempts,
        'passed_quizzes': passed_quizzes,
        'quiz_pass_rate': round(quiz_pass_rate, 1),
        'avg_quiz_score': round(avg_quiz_score, 1),
        'access_by_method': access_by_method,
        'drop_off_count': drop_off_count,
        'drop_off_rate': round(drop_off_rate, 1),
        'eligible_students_count': eligible_students_count,
    })


# Helper functions (imported from views.py or defined here)
def generate_slug(text):
    """Generate URL-friendly slug from text"""
    import unicodedata
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


# ========== BUNDLE MANAGEMENT ==========

@staff_member_required
def dashboard_bundles(request):
    """List all bundles"""
    bundles = Bundle.objects.annotate(
        course_count=Count('courses'),
        purchase_count=Count('purchases')
    ).order_by('-created_at')
    
    return render(request, 'dashboard/bundles.html', {
        'bundles': bundles,
    })


@staff_member_required
def dashboard_add_bundle(request):
    """Create a new bundle"""
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        bundle_type = request.POST.get('bundle_type', 'fixed')
        price = request.POST.get('price', '') or None
        is_active = request.POST.get('is_active') == 'on'
        max_course_selections = request.POST.get('max_course_selections', '') or None
        course_ids = request.POST.getlist('courses')
        
        if not name:
            messages.error(request, 'Bundle name is required')
            return redirect('dashboard_add_bundle')
        
        # Generate slug from name
        default_tenant = get_default_tenant()
        slug = generate_slug(name)
        # Ensure slug is unique
        base_slug = slug
        counter = 1
        while Bundle.objects.filter(tenant=default_tenant, slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        bundle = Bundle.objects.create(
            tenant=default_tenant,
            name=name,
            slug=slug,
            description=description,
            bundle_type=bundle_type,
            price=float(price) if price else None,
            is_active=is_active,
            max_course_selections=int(max_course_selections) if max_course_selections else None
        )
        
        # Add courses
        if course_ids:
            courses = Course.objects.filter(id__in=course_ids)
            bundle.courses.set(courses)
        
        messages.success(request, f'Bundle "{bundle.name}" created successfully!')
        return redirect('dashboard_bundles')
    
    courses = Course.objects.filter(status='active').order_by('name')
    return render(request, 'dashboard/add_bundle.html', {
        'courses': courses,
    })


@staff_member_required
def dashboard_edit_bundle(request, bundle_id):
    """Edit an existing bundle"""
    bundle = get_object_or_404(Bundle, id=bundle_id)
    
    if request.method == 'POST':
        bundle.name = request.POST.get('name')
        bundle.description = request.POST.get('description', '')
        bundle.bundle_type = request.POST.get('bundle_type', 'fixed')
        price = request.POST.get('price', '') or None
        bundle.is_active = request.POST.get('is_active') == 'on'
        max_course_selections = request.POST.get('max_course_selections', '') or None
        course_ids = request.POST.getlist('courses')
        
        if not bundle.name:
            messages.error(request, 'Bundle name is required')
            return redirect('dashboard_edit_bundle', bundle_id=bundle_id)
        
        # Update slug if name changed
        new_slug = generate_slug(bundle.name)
        if new_slug != bundle.slug:
            base_slug = new_slug
            counter = 1
            while Bundle.objects.filter(slug=new_slug).exclude(id=bundle.id).exists():
                new_slug = f"{base_slug}-{counter}"
                counter += 1
            bundle.slug = new_slug
        
        bundle.price = float(price) if price else None
        bundle.max_course_selections = int(max_course_selections) if max_course_selections else None
        bundle.save()
        
        # Update courses
        if course_ids:
            courses = Course.objects.filter(id__in=course_ids)
            bundle.courses.set(courses)
        else:
            bundle.courses.clear()
        
        messages.success(request, f'Bundle "{bundle.name}" updated successfully!')
        return redirect('dashboard_bundles')
    
    courses = Course.objects.filter(status='active').order_by('name')
    selected_course_ids = bundle.courses.values_list('id', flat=True)
    
    return render(request, 'dashboard/edit_bundle.html', {
        'bundle': bundle,
        'courses': courses,
        'selected_course_ids': selected_course_ids,
    })


@staff_member_required
@require_http_methods(["POST"])
def dashboard_delete_bundle(request, bundle_id):
    """Delete a bundle"""
    bundle = get_object_or_404(Bundle, id=bundle_id)
    bundle_name = bundle.name
    
    # Check if bundle has purchases
    purchase_count = bundle.purchases.count()
    if purchase_count > 0:
        messages.error(request, f'Cannot delete bundle "{bundle_name}" because it has {purchase_count} purchase(s).')
        return redirect('dashboard_bundles')
    
    bundle.delete()
    messages.success(request, f'Bundle "{bundle_name}" deleted successfully!')
    return redirect('dashboard_bundles')


def _get_dashboard_tenant(request):
    """Resolve active tenant for tenant-admin dashboard context."""
    tenant = getattr(request, 'tenant', None)
    if tenant is not None:
        if request.user.is_superuser:
            request.session['superadmin_tenant_id'] = tenant.id
        return tenant

    # Superadmins can select a tenant once and keep that context across
    # dashboard navigation on platform hosts (where request.tenant is None).
    if request.user.is_superuser:
        tenant_query = (request.GET.get('tenant') or '').strip().lower()
        if tenant_query == 'clear':
            request.session.pop('superadmin_tenant_id', None)
            return None
        if tenant_query:
            selected = Tenant.objects.filter(slug=tenant_query, is_archived=False).first()
            if selected:
                request.session['superadmin_tenant_id'] = selected.id
                return selected

        selected_id = request.session.get('superadmin_tenant_id')
        if selected_id:
            selected = Tenant.objects.filter(id=selected_id, is_archived=False).first()
            if selected:
                return selected
            request.session.pop('superadmin_tenant_id', None)

    # Legacy fallback for old host-based access.
    membership = TenantMembership.objects.filter(
        user=request.user,
        role='tenant_admin',
        is_active=True
    ).select_related('tenant').first()
    return membership.tenant if membership else None


@staff_member_required
def dashboard_domain_settings(request):
    """Tenant admin domain management page."""
    is_superadmin = bool(request.user.is_superuser)
    tenant = _get_dashboard_tenant(request)
    if tenant is None and not is_superadmin:
        messages.error(request, 'Tenant context is required to manage domains.')
        return redirect('dashboard_home')

    if tenant is not None:
        ensure_temporary_domain(tenant)

    if request.method == 'POST':
        if tenant is None:
            messages.error(request, 'Select a tenant context before adding a custom domain.')
            return redirect('dashboard_domain_settings')
        domain = normalize_domain(request.POST.get('domain'))
        if not domain:
            messages.error(request, 'Please enter a valid domain.')
            return redirect('dashboard_domain_settings')
        if TenantDomain.objects.filter(domain=domain).exists():
            messages.error(request, f'Domain "{domain}" is already connected.')
            return redirect('dashboard_domain_settings')

        TenantDomain.objects.create(
            tenant=tenant,
            domain=domain,
            is_temporary=False,
            is_primary=False,
            is_verified=False,
            verification_notes='Pending DNS verification',
        )
        messages.success(request, f'Domain "{domain}" added. Complete DNS setup and verify.')
        return redirect('dashboard_domain_settings')

    domains = TenantDomain.objects.filter(tenant=tenant).order_by('-is_primary', 'domain') if tenant else TenantDomain.objects.none()
    config = None
    if tenant:
        config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    primary_domain = domains.filter(is_primary=True).first() if tenant else None
    temporary_domain = domains.filter(is_temporary=True).first() if tenant else None
    referral_signup_url = ''
    referred_tenants = Tenant.objects.none()
    if tenant and tenant.referral_code:
        referral_signup_url = f"{request.scheme}://{request.get_host()}/start-academy/?ref={tenant.referral_code}"
        referred_tenants = Tenant.objects.filter(referred_by=tenant).order_by('-created_at')
    all_tenant_domains = (
        TenantDomain.objects.select_related('tenant').order_by('tenant__name', '-is_primary', 'domain')
        if is_superadmin else TenantDomain.objects.none()
    )
    return render(request, 'dashboard/domain_settings.html', {
        'tenant': tenant,
        'is_superadmin': is_superadmin,
        'tenant_config': config,
        'domains': domains,
        'all_tenant_domains': all_tenant_domains,
        'primary_domain': primary_domain,
        'temporary_domain': temporary_domain,
        'platform_base_domain': get_platform_base_domain(),
        'referral_signup_url': referral_signup_url,
        'referred_tenants': referred_tenants,
    })


@staff_member_required
@require_http_methods(["POST"])
def dashboard_verify_domain(request, domain_id):
    """Mark a tenant domain as verified (manual verify for now)."""
    tenant = _get_dashboard_tenant(request)
    if tenant is None:
        messages.error(request, 'Tenant context is required.')
        return redirect('dashboard_home')
    domain = get_object_or_404(TenantDomain, id=domain_id, tenant=tenant)
    domain.is_verified = True
    domain.verification_notes = 'Verified by tenant admin'
    domain.save(update_fields=['is_verified', 'verification_notes', 'updated_at'])
    messages.success(request, f'Domain "{domain.domain}" verified.')
    return redirect('dashboard_domain_settings')


@staff_member_required
@require_http_methods(["POST"])
def dashboard_make_primary_domain(request, domain_id):
    """Set a verified domain as primary."""
    tenant = _get_dashboard_tenant(request)
    if tenant is None:
        messages.error(request, 'Tenant context is required.')
        return redirect('dashboard_home')
    domain = get_object_or_404(TenantDomain, id=domain_id, tenant=tenant)
    if not domain.is_verified:
        messages.error(request, 'Domain must be verified before setting as primary.')
        return redirect('dashboard_domain_settings')
    TenantDomain.objects.filter(tenant=tenant).update(is_primary=False)
    domain.is_primary = True
    domain.save(update_fields=['is_primary', 'updated_at'])
    if not domain.is_temporary:
        tenant.custom_domain = domain.domain
        tenant.save(update_fields=['custom_domain'])
    messages.success(request, f'"{domain.domain}" is now your primary domain.')
    return redirect('dashboard_domain_settings')


@staff_member_required
def dashboard_branding_settings(request):
    """Tenant admin branding editor for copy shown across portal pages."""
    tenant = _get_dashboard_tenant(request)
    if tenant is None:
        messages.error(request, 'Tenant context is required to manage branding.')
        return redirect('dashboard_home')

    ensure_tenant_branding(tenant)
    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    current_branding = get_tenant_branding(tenant)
    features = config.features or {}
    custom_pages = features.get('custom_pages') or {}

    if request.method == 'POST':
        updated = dict(current_branding)
        theme_mode = (request.POST.get('theme_mode') or current_branding.get('theme_mode') or 'dark').strip().lower()
        if theme_mode not in ('dark', 'light'):
            theme_mode = 'dark'
        accent_primary = (request.POST.get('accent_primary') or current_branding.get('accent_primary') or '#00f0ff').strip().lower()
        accent_secondary = (request.POST.get('accent_secondary') or current_branding.get('accent_secondary') or '#a855f7').strip().lower()
        if not _is_valid_hex_color(accent_primary):
            messages.error(request, 'Primary accent color must be a valid hex color (example: #00f0ff).')
            return redirect('dashboard_branding_settings')
        if not _is_valid_hex_color(accent_secondary):
            messages.error(request, 'Secondary accent color must be a valid hex color (example: #a855f7).')
            return redirect('dashboard_branding_settings')
        updated.update({
            'brand_name': (request.POST.get('brand_name') or current_branding.get('brand_name', '')).strip(),
            'brand_short_name': (request.POST.get('brand_short_name') or current_branding.get('brand_short_name', '')).strip(),
            'theme_mode': theme_mode,
            'accent_primary': accent_primary,
            'accent_secondary': accent_secondary,
            'headline_line1': (request.POST.get('headline_line1') or current_branding.get('headline_line1', '')).strip(),
            'headline_line2': (request.POST.get('headline_line2') or current_branding.get('headline_line2', '')).strip(),
            'headline_line3': (request.POST.get('headline_line3') or current_branding.get('headline_line3', '')).strip(),
            'hero_description': (request.POST.get('hero_description') or current_branding.get('hero_description', '')).strip(),
            'feature_1_title': (request.POST.get('feature_1_title') or current_branding.get('feature_1_title', '')).strip(),
            'feature_1_sub': (request.POST.get('feature_1_sub') or current_branding.get('feature_1_sub', '')).strip(),
            'feature_2_title': (request.POST.get('feature_2_title') or current_branding.get('feature_2_title', '')).strip(),
            'feature_2_sub': (request.POST.get('feature_2_sub') or current_branding.get('feature_2_sub', '')).strip(),
            'feature_3_title': (request.POST.get('feature_3_title') or current_branding.get('feature_3_title', '')).strip(),
            'feature_3_sub': (request.POST.get('feature_3_sub') or current_branding.get('feature_3_sub', '')).strip(),
            'register_title': (request.POST.get('register_title') or current_branding.get('register_title', '')).strip(),
            'register_subtitle': (request.POST.get('register_subtitle') or current_branding.get('register_subtitle', '')).strip(),
            'login_welcome': (request.POST.get('login_welcome') or current_branding.get('login_welcome', '')).strip(),
            'login_form_tagline': (request.POST.get('login_form_tagline') or current_branding.get('login_form_tagline', '')).strip(),
            'footer_copy': (request.POST.get('footer_copy') or current_branding.get('footer_copy', '')).strip(),
        })

        if not updated['brand_name']:
            messages.error(request, 'Brand name is required.')
            return redirect('dashboard_branding_settings')

        landing_mode = (request.POST.get('landing_mode') or custom_pages.get('landing_mode') or 'default').strip()
        custom_pages['landing_mode'] = 'custom' if landing_mode == 'custom' else 'default'
        signup_mode = (request.POST.get('signup_mode') or custom_pages.get('signup_mode') or 'default').strip()
        custom_pages['signup_mode'] = 'custom' if signup_mode == 'custom' else 'default'
        login_mode = (request.POST.get('login_mode') or custom_pages.get('login_mode') or 'default').strip()
        custom_pages['login_mode'] = 'custom' if login_mode == 'custom' else 'default'

        uploaded_html = request.FILES.get('landing_html_file')
        html_text = (request.POST.get('landing_html') or '').strip()
        if uploaded_html:
            try:
                html_text = uploaded_html.read().decode('utf-8', errors='ignore')
            except Exception:
                html_text = ''

        existing_html = (custom_pages.get('landing_html') or '').strip()
        clear_html = request.POST.get('clear_landing_html') == '1'
        signup_html_text = (request.POST.get('signup_html') or '').strip()
        clear_signup_html = request.POST.get('clear_signup_html') == '1'
        existing_signup_html = (custom_pages.get('signup_html') or '').strip()
        login_html_text = (request.POST.get('login_html') or '').strip()
        clear_login_html = request.POST.get('clear_login_html') == '1'
        existing_login_html = (custom_pages.get('login_html') or '').strip()
        if landing_mode == 'custom' and not html_text and not existing_html and not clear_html:
            messages.error(
                request,
                'Custom landing is enabled but no HTML is provided yet. Upload/paste HTML or switch to default mode.'
            )
            return redirect('dashboard_branding_settings')
        if signup_mode == 'custom' and not signup_html_text and not existing_signup_html and not clear_signup_html:
            messages.error(
                request,
                'Custom sign-up page is enabled but no HTML is provided yet. Paste HTML or switch to default mode.'
            )
            return redirect('dashboard_branding_settings')
        if login_mode == 'custom' and not login_html_text and not existing_login_html and not clear_login_html:
            messages.error(
                request,
                'Custom login page is enabled but no HTML is provided yet. Paste HTML or switch to default mode.'
            )
            return redirect('dashboard_branding_settings')

        if html_text:
            custom_pages['landing_html'] = _sanitize_uploaded_html(html_text)
            # If admin provided HTML, auto-enable custom mode to avoid confusion.
            custom_pages['landing_mode'] = 'custom'
        if clear_html:
            custom_pages.pop('landing_html', None)
            if landing_mode == 'custom':
                custom_pages['landing_mode'] = 'default'
                messages.info(request, 'Custom HTML was cleared, so landing mode was switched back to default.')
        if signup_html_text:
            custom_pages['signup_html'] = _sanitize_uploaded_html(signup_html_text)
            custom_pages['signup_mode'] = 'custom'
        if clear_signup_html:
            custom_pages.pop('signup_html', None)
            if signup_mode == 'custom':
                custom_pages['signup_mode'] = 'default'
                messages.info(request, 'Sign-up custom HTML was cleared, so sign-up mode was switched to default.')
        if login_html_text:
            custom_pages['login_html'] = _sanitize_uploaded_html(login_html_text)
            custom_pages['login_mode'] = 'custom'
        if clear_login_html:
            custom_pages.pop('login_html', None)
            if login_mode == 'custom':
                custom_pages['login_mode'] = 'default'
                messages.info(request, 'Login custom HTML was cleared, so login mode was switched to default.')

        if request.POST.get('remove_logo') == '1':
            if tenant.logo:
                tenant.logo.delete(save=False)
                tenant.logo = None
                tenant.save(update_fields=['logo', 'updated_at'])
            updated['logo_url'] = ''

        logo_url_input = (request.POST.get('logo_url') or '').strip()
        if logo_url_input:
            if not _is_valid_logo_url(logo_url_input):
                messages.error(request, 'Please enter a valid logo URL (http or https).')
                return redirect('dashboard_branding_settings')
            updated['logo_url'] = logo_url_input
            if tenant.logo:
                tenant.logo.delete(save=False)
                tenant.logo = None
                tenant.save(update_fields=['logo', 'updated_at'])

        logo_file = request.FILES.get('logo_file')
        if logo_file and logo_url_input:
            messages.info(request, 'External logo URL was provided, so uploaded logo file was skipped.')
        if logo_file and not logo_url_input:
            logo_url = _upload_tenant_logo_webp_to_cloudinary(tenant, logo_file)
            if logo_url:
                updated['logo_url'] = logo_url
                # Clear local file pointer when cloud URL is now canonical.
                if tenant.logo:
                    tenant.logo.delete(save=False)
                    tenant.logo = None
                    tenant.save(update_fields=['logo', 'updated_at'])
            else:
                tenant.logo = logo_file
                tenant.save(update_fields=['logo', 'updated_at'])
                updated['logo_url'] = tenant.logo.url if tenant.logo else updated.get('logo_url', '')

        certificate_template_file = request.FILES.get('certificate_template_file')
        clear_certificate_template = request.POST.get('clear_certificate_template') == '1'
        if clear_certificate_template and not certificate_template_file:
            updated['certificate_template_url'] = ''
            messages.info(request, 'Custom certificate template removed. Default template will be used.')
        if certificate_template_file:
            certificate_template_name = (getattr(certificate_template_file, 'name', '') or '').lower()
            if not certificate_template_name.endswith('.pdf'):
                messages.error(request, 'Certificate template must be a PDF file.')
                return redirect('dashboard_branding_settings')
            certificate_template_url = _upload_tenant_certificate_template_to_cloudinary(tenant, certificate_template_file)
            if not certificate_template_url:
                messages.error(request, 'Could not upload certificate template. Please try again.')
                return redirect('dashboard_branding_settings')
            updated['certificate_template_url'] = certificate_template_url

        features['branding'] = updated
        features['custom_pages'] = custom_pages
        config.features = features
        config.save(update_fields=['features', 'updated_at'])
        mode_message = 'custom HTML' if custom_pages.get('landing_mode') == 'custom' else 'default template'
        html_len = len((custom_pages.get('landing_html') or '').strip())
        messages.success(request, f'Branding updated successfully. Landing mode: {mode_message}. HTML size: {html_len} chars.')
        return redirect('dashboard_branding_settings')

    return render(request, 'dashboard/branding_settings.html', {
        'tenant': tenant,
        'branding': current_branding,
        'custom_pages': custom_pages,
        'landing_mode': custom_pages.get('landing_mode', 'default'),
        'landing_html': custom_pages.get('landing_html', ''),
        'signup_mode': custom_pages.get('signup_mode', 'default'),
        'signup_html': custom_pages.get('signup_html', ''),
        'login_mode': custom_pages.get('login_mode', 'default'),
        'login_html': custom_pages.get('login_html', ''),
        'landing_html_sample': LANDING_HTML_SAMPLE,
        'signup_html_sample': SIGNUP_HTML_SAMPLE,
        'login_html_sample': LOGIN_HTML_SAMPLE,
        'certificate_template_sample_url': f"{settings.STATIC_URL}certificates/KATALYST_Certificate.pdf",
    })

