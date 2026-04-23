import re

from ..models import TenantConfig


HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _trim(text, max_len=120):
    text = (text or '').strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + '...'


def _normalize_hex_color(value, fallback):
    raw = (value or '').strip()
    if HEX_COLOR_RE.match(raw):
        return raw.lower()
    return fallback


def _hex_to_rgb(value):
    color = (value or '').strip().lstrip('#')
    if len(color) != 6:
        return (0, 0, 0)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(hex_color):
    r, g, b = _hex_to_rgb(hex_color)
    r_srgb, g_srgb, b_srgb = [v / 255 for v in (r, g, b)]

    def _linearize(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r_lin = _linearize(r_srgb)
    g_lin = _linearize(g_srgb)
    b_lin = _linearize(b_srgb)
    return (0.2126 * r_lin) + (0.7152 * g_lin) + (0.0722 * b_lin)


def _on_color_for_background(hex_color):
    # White text on darker accents, dark text on lighter accents.
    return '#ffffff' if _relative_luminance(hex_color) < 0.45 else '#0a0e27'


def _with_derived_accent_colors(branding):
    primary = branding.get('accent_primary', '#00f0ff')
    secondary = branding.get('accent_secondary', '#a855f7')
    primary_on = _on_color_for_background(primary)
    secondary_on = _on_color_for_background(secondary)

    p_lum = _relative_luminance(primary)
    s_lum = _relative_luminance(secondary)
    gradient_on = '#ffffff' if ((p_lum + s_lum) / 2) < 0.45 else '#0a0e27'

    return {
        **branding,
        'accent_primary_on': primary_on,
        'accent_secondary_on': secondary_on,
        'accent_gradient_on': gradient_on,
    }


def build_default_branding(tenant, profile=None):
    name = (tenant.name or 'Your Academy').strip()
    short_name = name if len(name) <= 28 else name[:28].rstrip() + '...'
    profile = profile or {}
    teach = _trim(profile.get('teach_topic') or 'their expertise', 80)
    audience = _trim(profile.get('target_audience') or 'their learners', 80)
    outcome = _trim(profile.get('outcome_promise') or 'clear, measurable results', 100)

    hero_description = (
        f'{name} helps {audience} master {teach} through structured learning that drives {outcome}.'
    )

    return {
        'brand_name': name,
        'brand_short_name': short_name,
        'theme_mode': 'dark',
        'accent_primary': '#00f0ff',
        'accent_secondary': '#a855f7',
        'logo_url': '',
        'certificate_template_url': '',
        'headline_line1': 'Train Smarter.',
        'headline_line2': 'Scale Faster.',
        'headline_line3': 'Win Bigger.',
        'hero_description': hero_description,
        'hero_badge': f'The learning platform for {audience}',
        'feature_1_title': 'Automatic Progress Tracking',
        'feature_1_sub': 'Resume exactly where you left off',
        'feature_2_title': 'Certifications + Milestones',
        'feature_2_sub': 'Proof of completion that matters',
        'feature_3_title': 'AI Chatbot Inside Lessons',
        'feature_3_sub': 'In-lesson support, zero friction',
        'section_features_title': f'Features built for {name}',
        'section_features_sub': f'Everything {audience} need to learn {teach} and deliver {outcome}.',
        'section_process_sub': f'{name} is built to get {audience} from onboarding to outcomes, fast.',
        'section_testimonials_title': f'Learners who trust {name}.',
        'cta_sub': f'Build training experiences that create {outcome}.',
        'hub_guest_title': f'Learn with {name}',
        'hub_guest_subtitle': f'Browse programs from {name} and start at your pace.',
        'hub_dashboard_subtitle': f'Track your learning progress inside {name}.',
        'login_welcome': f'Welcome to {name}',
        'login_form_tagline': f'Enter your credentials to access {name}.',
        'register_title': 'Create your account',
        'register_subtitle': f'You are registering under {name}.',
        'footer_tagline': f'{name} — learning designed for {outcome}.',
        'footer_copy': f'© 2026 {name}. All rights reserved.',
    }


def get_tenant_branding(tenant):
    if tenant is None:
        return _with_derived_accent_colors({
            'brand_name': 'CourseForge',
            'brand_short_name': 'CourseForge',
            'theme_mode': 'dark',
            'accent_primary': '#00f0ff',
            'accent_secondary': '#a855f7',
            'logo_url': '',
            'certificate_template_url': '',
            'headline_line1': 'Build your academy.',
            'headline_line2': 'Launch with confidence.',
            'headline_line3': 'Grow with leverage.',
            'hero_description': 'Create and run your white-label learning platform.',
            'feature_1_title': 'Automatic Progress Tracking',
            'feature_1_sub': 'Resume exactly where learners left off',
            'feature_2_title': 'Certifications + Milestones',
            'feature_2_sub': 'Recognize outcomes that matter',
            'feature_3_title': 'AI Chatbot Inside Lessons',
            'feature_3_sub': 'In-lesson support with less overhead',
            'footer_copy': '© 2026 CourseForge. All rights reserved.',
        })

    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    features = config.features or {}
    branding = features.get('branding') or {}
    defaults = build_default_branding(tenant)
    merged = {**defaults, **branding}
    merged['accent_primary'] = _normalize_hex_color(merged.get('accent_primary'), defaults['accent_primary'])
    merged['accent_secondary'] = _normalize_hex_color(merged.get('accent_secondary'), defaults['accent_secondary'])
    if not merged.get('logo_url') and getattr(tenant, 'logo', None):
        try:
            merged['logo_url'] = tenant.logo.url
        except Exception:
            merged['logo_url'] = ''
    return _with_derived_accent_colors(merged)


def ensure_tenant_branding(tenant):
    """Ensure tenant has editable branding defaults in TenantConfig.features."""
    if tenant is None:
        return
    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    features = config.features or {}
    profile = features.get('brand_profile') or {}
    if 'branding' not in features:
        features['branding'] = build_default_branding(tenant, profile=profile)
        config.features = features
        config.save(update_fields=['features', 'updated_at'])

