"""AI translation generation with structure-preserving Editor.js handling."""
import copy
import json
import logging
import os

logger = logging.getLogger(__name__)

_STRING_BATCH_SIZE = 35

LANGUAGE_PROMPT_NAMES = {
    'it': 'Italian',
    'fil': 'Filipino (Tagalog)',
    'tl': 'Filipino (Tagalog)',
}


def language_name_for_prompt(code):
    from myApp.utils.localization import normalize_language_code
    normalized = normalize_language_code(code)
    return LANGUAGE_PROMPT_NAMES.get(normalized, normalized.upper())


def _collect_editorjs_strings(blocks):
    strings = []
    refs = []

    for bi, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            continue
        btype = block.get('type')
        data = block.get('data') if isinstance(block.get('data'), dict) else {}
        if btype in ('paragraph', 'header', 'quote'):
            text = data.get('text')
            if text:
                strings.append(str(text))
                refs.append((bi, 'text', None))
        elif btype == 'list':
            for ii, item in enumerate(data.get('items') or []):
                if isinstance(item, dict):
                    raw = item.get('content', '')
                else:
                    raw = item
                strings.append(str(raw))
                refs.append((bi, 'items', ii))
        caption = data.get('caption')
        if caption:
            strings.append(str(caption))
            refs.append((bi, 'caption', None))

    return strings, refs


def _inject_editorjs_strings(blocks, refs, translated_strings):
    result = copy.deepcopy(blocks)
    for (bi, field, item_index), translated in zip(refs, translated_strings):
        block = result[bi]
        data = block.setdefault('data', {})
        if field == 'text':
            data['text'] = translated
        elif field == 'caption':
            data['caption'] = translated
        elif field == 'items':
            items = list(data.get('items') or [])
            if item_index is not None and item_index < len(items):
                if isinstance(items[item_index], dict):
                    items[item_index] = dict(items[item_index])
                    items[item_index]['content'] = translated
                else:
                    items[item_index] = translated
                data['items'] = items
    return result


def content_quality_ok(source_content, translated_content):
    src_blocks = (source_content or {}).get('blocks', []) if isinstance(source_content, dict) else []
    tr_blocks = (translated_content or {}).get('blocks', []) if isinstance(translated_content, dict) else []
    if len(tr_blocks) != len(src_blocks):
        return False
    for block in tr_blocks:
        if isinstance(block, str):
            return False
        if not isinstance(block, dict) or not block.get('type'):
            return False
    return True


def _parse_json_response(response_text):
    text = (response_text or '').strip()
    if text.startswith('```'):
        text = text.split('```', 1)[1]
        if text.startswith('json'):
            text = text[4:]
        text = text.strip()
    if text.endswith('```'):
        text = text.rsplit('```', 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _output_token_budget(text):
    """Reserve enough completion tokens for long translated strings."""
    char_len = len(text or '')
    return min(max(2000, char_len // 2 + 500), 16000)


def _get_openai_client():
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured.')
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def _translate_string_batch(client, strings, language_code, tenant=None, course=None, lesson=None):
    if not strings:
        return []
    from myApp.dashboard_views import _log_openai_usage

    lang_name = language_name_for_prompt(language_code)
    system = (
        f'Translate each string in the JSON array into {lang_name}. '
        'Return a JSON object with key "strings": an array of translated strings '
        'in the exact same order and length as the input. '
        'Translate every string completely. Do not skip, merge, or summarize.'
    )
    user_payload = json.dumps({'strings': strings}, ensure_ascii=False)

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_payload},
        ],
        temperature=0.2,
        response_format={'type': 'json_object'},
        max_tokens=4000,
    )
    _log_openai_usage(
        feature='lesson_translation',
        response=response,
        tenant=tenant,
        course=course,
        lesson=lesson,
        model_name='gpt-4o-mini',
    )
    data = _parse_json_response(response.choices[0].message.content)
    translated = data.get('strings', [])
    if not isinstance(translated, list) or len(translated) != len(strings):
        raise ValueError('Translation batch returned wrong string count.')
    return translated


def translate_editorjs_content(source_content, language_code, tenant=None, course=None, lesson=None):
    """Deep-copy blocks, translate strings in batches, inject back."""
    source = source_content if isinstance(source_content, dict) else {}
    blocks = source.get('blocks', []) if isinstance(source.get('blocks'), list) else []
    if not blocks:
        return {'blocks': [], 'version': source.get('version') or '2.28.2'}

    strings, refs = _collect_editorjs_strings(blocks)
    if not strings:
        return copy.deepcopy(source)

    client = _get_openai_client()
    translated_all = []
    for start in range(0, len(strings), _STRING_BATCH_SIZE):
        batch = strings[start:start + _STRING_BATCH_SIZE]
        translated_all.extend(
            _translate_string_batch(client, batch, language_code, tenant=tenant, course=course, lesson=lesson)
        )

    translated_blocks = _inject_editorjs_strings(blocks, refs, translated_all)
    translated_content = {
        'blocks': translated_blocks,
        'version': source.get('version') or '2.28.2',
        'time': source.get('time'),
    }
    if not content_quality_ok(source, translated_content):
        raise ValueError('Editor.js translation failed quality check.')
    return translated_content


def _translate_single_string(
    client, text, language_code, tenant=None, course=None, lesson=None, feature='lesson_translation',
):
    from myApp.dashboard_views import _log_openai_usage

    value = str(text or '')
    if not value.strip():
        return value

    lang_name = language_name_for_prompt(language_code)
    system = (
        f'Translate the text into {lang_name}. '
        'Return a JSON object with key "text" containing the full translation. '
        'Translate completely without summarizing or omitting content.'
    )
    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': value},
        ],
        temperature=0.2,
        response_format={'type': 'json_object'},
        max_tokens=_output_token_budget(value),
    )
    _log_openai_usage(
        feature=feature,
        response=response,
        tenant=tenant,
        course=course,
        lesson=lesson,
        model_name='gpt-4o-mini',
    )
    data = _parse_json_response(response.choices[0].message.content)
    translated = data.get('text', '')
    return translated if isinstance(translated, str) and translated.strip() else value


def _translate_metadata_json(client, payload, language_code, tenant=None, course=None, lesson=None, feature='lesson_translation'):
    """Translate metadata field-by-field to avoid truncated JSON on long descriptions."""
    result = {}
    for key, value in payload.items():
        if isinstance(value, str):
            result[key] = _translate_single_string(
                client, value, language_code,
                tenant=tenant, course=course, lesson=lesson, feature=feature,
            )
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            if value:
                result[key] = _translate_string_batch(
                    client, value, language_code,
                    tenant=tenant, course=course, lesson=lesson,
                )
            else:
                result[key] = []
        else:
            result[key] = value
    return result


def generate_lesson_translation(lesson, language_code):
    """Generate draft LessonTranslation using structure-preserving pipeline."""
    from myApp.models import LessonTranslation
    from myApp.utils.localization import normalize_language_code

    language_code = normalize_language_code(language_code)
    tenant = lesson.tenant
    course = lesson.course
    client = _get_openai_client()

    metadata_payload = {
        'title': lesson.ai_clean_title or lesson.title or '',
        'short_summary': lesson.ai_short_summary or '',
        'full_description': lesson.ai_full_description or lesson.description or '',
        'outcomes': lesson.get_outcomes_list(),
        'coach_actions': lesson.get_coach_actions_list(),
    }
    metadata = _translate_metadata_json(
        client, metadata_payload, language_code,
        tenant=tenant, course=course, lesson=lesson,
    )

    source_content = lesson.content if isinstance(lesson.content, dict) else {'blocks': []}
    translated_content = translate_editorjs_content(
        source_content, language_code,
        tenant=tenant, course=course, lesson=lesson,
    )

    translation, _ = LessonTranslation.objects.update_or_create(
        lesson=lesson,
        language_code=language_code,
        defaults={
            'title': metadata.get('title', ''),
            'ai_clean_title': metadata.get('title', ''),
            'ai_short_summary': metadata.get('short_summary', ''),
            'ai_full_description': metadata.get('full_description', ''),
            'description': metadata.get('full_description', ''),
            'ai_outcomes': metadata.get('outcomes', []),
            'ai_coach_actions': metadata.get('coach_actions', []),
            'content': translated_content,
            'status': 'draft',
            'translation_source': 'ai',
        },
    )
    return translation


def generate_course_translation(course, language_code):
    from myApp.models import CourseTranslation
    from myApp.utils.localization import normalize_language_code

    language_code = normalize_language_code(language_code)
    client = _get_openai_client()
    payload = {
        'name': course.name or '',
        'description': course.description or '',
        'short_description': course.short_description or '',
    }
    metadata = _translate_metadata_json(
        client, payload, language_code,
        tenant=course.tenant, course=course, feature='course_translation',
    )
    translation, _ = CourseTranslation.objects.update_or_create(
        course=course,
        language_code=language_code,
        defaults={
            'name': metadata.get('name', ''),
            'description': metadata.get('description', ''),
            'short_description': metadata.get('short_description', ''),
            'status': 'draft',
            'translation_source': 'ai',
        },
    )
    return translation


def generate_module_translations_for_course(course, language_code):
    from myApp.models import ModuleTranslation
    from myApp.utils.localization import normalize_language_code

    language_code = normalize_language_code(language_code)
    client = _get_openai_client()
    results = []
    for module in course.modules.all():
        payload = {'name': module.name or '', 'description': module.description or ''}
        metadata = _translate_metadata_json(
            client, payload, language_code,
            tenant=course.tenant, course=course, feature='module_translation',
        )
        translation, _ = ModuleTranslation.objects.update_or_create(
            module=module,
            language_code=language_code,
            defaults={
                'name': metadata.get('name', ''),
                'description': metadata.get('description', ''),
                'status': 'draft',
                'translation_source': 'ai',
            },
        )
        results.append(translation)
    return results


def generate_quiz_question_translations(lesson, language_code):
    from myApp.models import LessonQuizQuestionTranslation
    from myApp.utils.localization import normalize_language_code

    language_code = normalize_language_code(language_code)
    try:
        quiz = lesson.quiz
    except Exception:
        return []

    client = _get_openai_client()
    results = []
    for question in quiz.questions.all():
        payload = {
            'text': question.text,
            'option_a': question.option_a,
            'option_b': question.option_b,
            'option_c': question.option_c,
            'option_d': question.option_d,
        }
        metadata = _translate_metadata_json(
            client, payload, language_code,
            tenant=lesson.tenant, course=lesson.course, lesson=lesson,
            feature='quiz_translation',
        )
        translation, _ = LessonQuizQuestionTranslation.objects.update_or_create(
            question=question,
            language_code=language_code,
            defaults={
                'text': metadata.get('text', ''),
                'option_a': metadata.get('option_a', ''),
                'option_b': metadata.get('option_b', ''),
                'option_c': metadata.get('option_c', ''),
                'option_d': metadata.get('option_d', ''),
                'status': 'draft',
                'translation_source': 'ai',
            },
        )
        results.append(translation)
    return results


def publish_course_translations_for_language(course, language_code):
    from myApp.models import (
        CourseTranslation,
        LessonTranslation,
        ModuleTranslation,
        LessonQuizQuestionTranslation,
    )
    from myApp.utils.localization import normalize_language_code

    language_code = normalize_language_code(language_code)
    CourseTranslation.objects.filter(course=course, language_code=language_code).update(status='published')
    ModuleTranslation.objects.filter(module__course=course, language_code=language_code).update(status='published')
    LessonTranslation.objects.filter(lesson__course=course, language_code=language_code).update(status='published')
    LessonQuizQuestionTranslation.objects.filter(
        question__quiz__lesson__course=course,
        language_code=language_code,
    ).update(status='published')


def publish_lesson_translation(lesson, language_code):
    from myApp.models import LessonTranslation, LessonQuizQuestionTranslation
    from myApp.utils.localization import normalize_language_code

    language_code = normalize_language_code(language_code)
    LessonTranslation.objects.filter(lesson=lesson, language_code=language_code).update(status='published')
    LessonQuizQuestionTranslation.objects.filter(
        question__quiz__lesson=lesson,
        language_code=language_code,
    ).update(status='published')
