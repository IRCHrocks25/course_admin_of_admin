from ..models import TenantConfig


def _trim(text, max_len=120):
    text = (text or '').strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + '...'


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
        return {
            'brand_name': 'CourseForge',
            'brand_short_name': 'CourseForge',
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
        }

    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    features = config.features or {}
    branding = features.get('branding') or {}
    defaults = build_default_branding(tenant)
    merged = {**defaults, **branding}
    return merged


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

