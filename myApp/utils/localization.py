"""Read-time localization: language resolution and entity overlays."""
from types import SimpleNamespace

from django.contrib.auth.models import User

from myApp.models import (
    TenantConfig,
    UserProfile,
    LessonTranslation,
    CourseTranslation,
    ModuleTranslation,
    LessonQuizTranslation,
    LessonQuizQuestionTranslation,
)

SUPPORTED_LANGUAGES = {
    'en': 'English',
    'it': 'Italiano',
    'fil': 'Filipino',
    'es': 'Español',
}

DEFAULT_LANGUAGE_CONFIG = {
    'enabled': ['en'],
    'default': 'en',
    'show_language_switcher': False,
}


def normalize_language_code(code):
    raw = (code or '').strip().lower()
    if raw == 'tl':
        return 'fil'
    return raw


def get_language_label(code):
    return SUPPORTED_LANGUAGES.get(normalize_language_code(code), (code or '').upper())


def _normalize_language_config(raw):
    if not isinstance(raw, dict):
        return dict(DEFAULT_LANGUAGE_CONFIG)
    enabled = raw.get('enabled') or ['en']
    if not isinstance(enabled, list):
        enabled = ['en']
    enabled = [normalize_language_code(code) for code in enabled if str(code).strip()]
    if 'en' not in enabled:
        enabled = ['en'] + enabled
    default = normalize_language_code(raw.get('default') or 'en')
    if default not in enabled:
        default = 'en'
    show_switcher = raw.get('show_language_switcher')
    if show_switcher is None:
        show_switcher = raw.get('allow_student_switch', len(enabled) > 1)
    return {
        'enabled': enabled,
        'default': default,
        'show_language_switcher': bool(show_switcher) and len(enabled) > 1,
    }


def get_tenant_language_config(tenant):
    if tenant is None:
        return dict(DEFAULT_LANGUAGE_CONFIG)
    try:
        config = TenantConfig.objects.get(tenant=tenant)
    except TenantConfig.DoesNotExist:
        return dict(DEFAULT_LANGUAGE_CONFIG)
    features = config.features or {}
    raw = features.get('languages') or features.get('lesson_languages') or {}
    return _normalize_language_config(raw)


def get_tenant_lesson_languages(tenant):
    """Backward-compatible alias."""
    cfg = get_tenant_language_config(tenant)
    return {
        'enabled': cfg['enabled'],
        'default': cfg['default'],
        'allow_student_switch': cfg['show_language_switcher'],
    }


def save_tenant_language_config(tenant, language_config):
    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    features = dict(config.features or {})
    normalized = _normalize_language_config(language_config)
    features['languages'] = normalized
    features['lesson_languages'] = {
        'enabled': normalized['enabled'],
        'default': normalized['default'],
        'allow_student_switch': normalized['show_language_switcher'],
    }
    config.features = features
    config.save(update_fields=['features', 'updated_at'])
    return normalized


def save_tenant_lesson_languages(tenant, lesson_languages):
    return save_tenant_language_config(tenant, lesson_languages)


def django_code_for_language(code):
    code = normalize_language_code(code)
    if code == 'en':
        return 'en-us'
    return code


def _is_translation_visible(status, admin_preview=False):
    if admin_preview:
        return True
    return status in ('published', 'approved')


class LocalizedProxy:
    def __init__(self, source, **overrides):
        self._source = source
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._source, name)


def get_user_preferred_language(user):
    if not user or not user.is_authenticated:
        return ''
    try:
        return normalize_language_code(user.profile.preferred_language)
    except UserProfile.DoesNotExist:
        return ''


def get_request_language(request, tenant=None):
    """Priority: ?lang= → cookie → user profile → tenant default."""
    tenant = tenant or getattr(request, 'tenant', None)
    config = get_tenant_language_config(tenant)
    enabled = config['enabled']
    default = config['default']

    lang_param = normalize_language_code(request.GET.get('lang'))
    if lang_param:
        resolved = lang_param if lang_param in enabled else default
        request.session['preferred_language'] = resolved
        return resolved

    cookie_lang = normalize_language_code(request.COOKIES.get('lang'))
    if cookie_lang and cookie_lang in enabled:
        return cookie_lang

    profile_lang = get_user_preferred_language(getattr(request, 'user', None))
    if profile_lang and profile_lang in enabled:
        return profile_lang

    session_lang = normalize_language_code(request.session.get('preferred_language'))
    if session_lang and session_lang in enabled:
        return session_lang

    return default


def resolve_request_language(request, tenant):
    return get_request_language(request, tenant)


def show_language_switcher(tenant, config=None):
    config = config or get_tenant_language_config(tenant)
    switcher = config.get('show_language_switcher')
    if switcher is None:
        switcher = config.get('allow_student_switch')
    return bool(switcher) and len(config.get('enabled') or []) > 1


def attach_localization_context(request, tenant=None):
    tenant = tenant or getattr(request, 'tenant', None)
    config = get_tenant_language_config(tenant)
    current = get_request_language(request, tenant)
    enabled = [
        {'code': code, 'label': get_language_label(code)}
        for code in config['enabled']
    ]
    return {
        'current_language': current,
        'active_language': current,
        'enabled_languages': config['enabled'],
        'enabled_language_choices': enabled,
        'show_language_switcher': show_language_switcher(tenant, config),
        'language_labels': SUPPORTED_LANGUAGES,
    }


def _pick_text(translated, base):
    value = (translated or '').strip()
    return value if value else (base or '')


def _pick_list(translated, base):
    if isinstance(translated, list) and translated:
        return translated
    if isinstance(base, list):
        return base
    return []


def _content_blocks(content):
    if isinstance(content, dict):
        blocks = content.get('blocks')
        if isinstance(blocks, list):
            return blocks
    return []


def _pick_content(translated_content, base_content):
    trans_blocks = _content_blocks(translated_content)
    if trans_blocks:
        base = translated_content if isinstance(translated_content, dict) else {}
        return {
            'blocks': trans_blocks,
            'version': base.get('version') or (base_content or {}).get('version') or '2.28.2',
            'time': base.get('time') or (base_content or {}).get('time'),
        }
    base = base_content if isinstance(base_content, dict) else {}
    return {
        'blocks': _content_blocks(base),
        'version': base.get('version') or '2.28.2',
        'time': base.get('time'),
    }


def _get_lesson_translation(lesson, language_code, admin_preview=False):
    language_code = normalize_language_code(language_code)
    if not language_code or language_code == 'en':
        return None
    try:
        translation = lesson.translations.get(language_code=language_code)
    except LessonTranslation.DoesNotExist:
        return None
    if not _is_translation_visible(translation.status, admin_preview=admin_preview):
        return None
    return translation


def resolve_lesson(lesson, language_code='en', *, admin_preview=False):
    language_code = normalize_language_code(language_code)
    base_title = lesson.ai_clean_title or lesson.title
    base_description = lesson.ai_full_description or lesson.description
    base_content = lesson.content if isinstance(lesson.content, dict) else {'blocks': []}
    translation = _get_lesson_translation(lesson, language_code, admin_preview=admin_preview)

    if translation:
        title = _pick_text(translation.title or translation.ai_clean_title, base_title)
        description = _pick_text(translation.ai_full_description or translation.description, base_description)
        content = _pick_content(translation.content, base_content)
        outcomes = _pick_list(translation.get_outcomes_list(), lesson.get_outcomes_list())
        coach_actions = _pick_list(translation.get_coach_actions_list(), lesson.get_coach_actions_list())
        short_summary = _pick_text(translation.ai_short_summary, lesson.ai_short_summary)
        clean_title = _pick_text(translation.ai_clean_title, lesson.ai_clean_title or base_title)
        audio_url = _pick_text(translation.audio_url, lesson.audio_url)
        is_translated = True
    else:
        title = base_title
        description = base_description
        content = _pick_content(None, base_content)
        outcomes = lesson.get_outcomes_list()
        coach_actions = lesson.get_coach_actions_list()
        short_summary = lesson.ai_short_summary
        clean_title = lesson.ai_clean_title or base_title
        audio_url = lesson.audio_url
        is_translated = False

    proxy = LocalizedProxy(
        lesson,
        title=title,
        description=description,
        ai_clean_title=clean_title,
        ai_short_summary=short_summary,
        ai_full_description=description,
        ai_outcomes=outcomes,
        ai_coach_actions=coach_actions,
        content=content,
        audio_url=audio_url,
        is_translated=is_translated,
        language_code=language_code,
    )

    def get_outcomes_list():
        return outcomes

    def get_coach_actions_list():
        return coach_actions

    proxy.get_outcomes_list = get_outcomes_list
    proxy.get_coach_actions_list = get_coach_actions_list
    return proxy


resolve_lesson_display = resolve_lesson


def resolve_course(course, language_code='en', *, admin_preview=False):
    language_code = normalize_language_code(language_code)
    if not language_code or language_code == 'en':
        return course
    try:
        translation = course.translations.get(language_code=language_code)
    except CourseTranslation.DoesNotExist:
        return course
    if not _is_translation_visible(translation.status, admin_preview=admin_preview):
        return course
    return LocalizedProxy(
        course,
        name=_pick_text(translation.name, course.name),
        description=_pick_text(translation.description, course.description),
        short_description=_pick_text(translation.short_description, course.short_description),
        is_translated=True,
    )


def resolve_module(module, language_code='en', *, admin_preview=False):
    language_code = normalize_language_code(language_code)
    if not language_code or language_code == 'en':
        return module
    try:
        translation = module.translations.get(language_code=language_code)
    except ModuleTranslation.DoesNotExist:
        return module
    if not _is_translation_visible(translation.status, admin_preview=admin_preview):
        return module
    return LocalizedProxy(
        module,
        name=_pick_text(translation.name, module.name),
        description=_pick_text(translation.description, module.description),
        is_translated=True,
    )


def build_lesson_title_map(lessons, language_code='en', *, admin_preview=False):
    return {
        lesson.id: resolve_lesson(lesson, language_code, admin_preview=admin_preview).title
        for lesson in lessons
    }


def build_module_name_map(modules, language_code='en', *, admin_preview=False):
    return {
        module.id: resolve_module(module, language_code, admin_preview=admin_preview).name
        for module in modules
    }


def resolve_quiz_question(question, language_code='en', *, admin_preview=False):
    language_code = normalize_language_code(language_code)
    if not language_code or language_code == 'en':
        return question
    try:
        translation = question.translations.get(language_code=language_code)
    except LessonQuizQuestionTranslation.DoesNotExist:
        return question
    if not _is_translation_visible(translation.status, admin_preview=admin_preview):
        return question
    return LocalizedProxy(
        question,
        text=_pick_text(translation.text, question.text),
        option_a=_pick_text(translation.option_a, question.option_a),
        option_b=_pick_text(translation.option_b, question.option_b),
        option_c=_pick_text(translation.option_c, question.option_c),
        option_d=_pick_text(translation.option_d, question.option_d),
        is_translated=True,
    )


def resolve_quiz_questions(quiz, language_code='en', *, admin_preview=False):
    return [
        resolve_quiz_question(q, language_code, admin_preview=admin_preview)
        for q in quiz.questions.all()
    ]


def resolve_quiz_display(quiz, language_code='en', *, admin_preview=False):
    language_code = normalize_language_code(language_code)
    if not language_code or language_code == 'en':
        return SimpleNamespace(title=quiz.title, description=quiz.description, is_translated=False)
    try:
        translation = quiz.translations.get(language_code=language_code)
    except LessonQuizTranslation.DoesNotExist:
        translation = None
    if translation and _is_translation_visible(translation.status, admin_preview=admin_preview):
        return SimpleNamespace(
            title=_pick_text(translation.title, quiz.title),
            description=_pick_text(translation.description, quiz.description),
            is_translated=True,
        )
    return SimpleNamespace(title=quiz.title, description=quiz.description, is_translated=False)


def resolve_quiz_question_display(question, language_code='en', *, admin_preview=False):
    resolved = resolve_quiz_question(question, language_code, admin_preview=admin_preview)
    return SimpleNamespace(
        id=question.id,
        text=resolved.text,
        option_a=resolved.option_a,
        option_b=resolved.option_b,
        option_c=resolved.option_c,
        option_d=resolved.option_d,
        correct_option=question.correct_option,
        is_translated=getattr(resolved, 'is_translated', False),
    )


def get_translation_languages_for_tenant(tenant):
    config = get_tenant_language_config(tenant)
    return [code for code in config['enabled'] if code != 'en']


def extract_lesson_text_for_chatbot(lesson, language_code='en'):
    resolved = resolve_lesson(lesson, language_code)
    parts = [
        resolved.title,
        resolved.ai_full_description or resolved.description,
    ]
    for block in (resolved.content or {}).get('blocks', []):
        if not isinstance(block, dict):
            continue
        data = block.get('data') if isinstance(block.get('data'), dict) else {}
        text = data.get('text')
        if text:
            parts.append(str(text))
    return '\n\n'.join(p for p in parts if p)


def chatbot_answer_language_instruction(language_code):
    code = normalize_language_code(language_code)
    if not code or code == 'en':
        return ''
    label = get_language_label(code)
    if code == 'fil':
        label = 'Filipino (Tagalog)'
    return f'Answer in {label}.'


def set_user_preferred_language(user, language_code):
    language_code = normalize_language_code(language_code)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.preferred_language = language_code
    profile.save(update_fields=['preferred_language', 'updated_at'])
    return profile
