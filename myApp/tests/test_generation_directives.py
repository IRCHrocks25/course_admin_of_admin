"""Tests for generation directives, seed parsing, and module grouping."""
import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from myApp.dashboard_views import (
    _blueprint_structure_prompt_section,
    _lesson_hero_iceberg_key,
    _normalize_modules_to_lesson_count,
    _overall_ai_generation_status,
    _parse_seed_lessons,
    _seed_modules_from_lessons,
    generate_ai_lesson_content,
    generate_ai_lesson_metadata,
)
from myApp.utils.generation_directives import (
    coerce_optional_bool,
    effective_generate_quiz,
    parse_generation_directives,
)
from myApp.utils.prompts import (
    LessonGenerationSettings,
    build_course_structure_prompt,
    build_image_brief_meta_prompt,
    build_lesson_content_prompt,
    build_lesson_image_prompt,
    build_lesson_metadata_prompt,
    target_lesson_count,
)


class GenerationDirectivesTests(SimpleTestCase):
    def test_detects_no_quiz_phrases(self):
        for phrase in (
            'Do not generate a quiz',
            'NO QUIZ please',
            'skip quiz for this lesson',
            "don't generate quiz",
            'Quiz: Off',
        ):
            d = parse_generation_directives('Title', phrase)
            self.assertTrue(d.skip_quiz, phrase)

    def test_detects_no_exercise(self):
        d = parse_generation_directives('', 'Do not generate an exercise. No exercise needed.')
        self.assertTrue(d.skip_exercise)
        self.assertFalse(d.skip_quiz)

    def test_explicit_override_wins(self):
        self.assertTrue(effective_generate_quiz('x', 'no quiz', explicit=True))
        self.assertFalse(effective_generate_quiz('x', 'normal source', explicit=False))
        self.assertFalse(effective_generate_quiz('x', 'skip quiz', explicit=None))

    def test_coerce_optional_bool(self):
        self.assertTrue(coerce_optional_bool('true'))
        self.assertFalse(coerce_optional_bool('off'))
        self.assertIsNone(coerce_optional_bool(None))
        self.assertIsNone(coerce_optional_bool('maybe'))


class SeedParseAndModulesTests(SimpleTestCase):
    def test_parse_honors_generate_quiz_false(self):
        raw = json.dumps([
            {'title': 'A', 'source': 'body', 'generate_quiz': False, 'module_name': 'Intro'},
            {'title': 'B', 'source': 'no quiz here', 'module_name': 'Intro'},
            {'title': 'C', 'source': 'normal', 'module_name': 'Advanced'},
        ])
        cleaned = _parse_seed_lessons(raw)
        self.assertEqual(len(cleaned), 3)
        self.assertFalse(cleaned[0]['generate_quiz'])
        self.assertFalse(cleaned[1]['generate_quiz'])
        self.assertTrue(cleaned[2]['generate_quiz'])
        self.assertEqual(cleaned[0]['module_name'], 'Intro')

    def test_module_grouping_order(self):
        seeds = [
            {'title': '1', 'source': 'a', 'module_name': 'B', 'generate_quiz': True, 'skip_exercise': False},
            {'title': '2', 'source': 'b', 'module_name': 'A', 'generate_quiz': True, 'skip_exercise': False},
            {'title': '3', 'source': 'c', 'module_name': 'B', 'generate_quiz': False, 'skip_exercise': False},
            {'title': '4', 'source': 'd', 'module_name': '', 'generate_quiz': True, 'skip_exercise': False},
        ]
        modules = _seed_modules_from_lessons(seeds)
        self.assertEqual([m['name'] for m in modules], ['B', 'A', 'Provided Lessons'])
        self.assertEqual(len(modules[0]['lessons']), 2)
        self.assertFalse(modules[0]['lessons'][1]['generate_quiz'])


class FieldStatusHelperTests(SimpleTestCase):
    def test_overall_status(self):
        self.assertEqual(_overall_ai_generation_status({'metadata': 'ok', 'content': 'ok'}), 'generated')
        self.assertEqual(_overall_ai_generation_status({'metadata': 'ok', 'content': 'failed'}), 'partial')
        self.assertEqual(_overall_ai_generation_status({'metadata': 'failed', 'content': 'failed'}), 'pending')


class PromptSkipClauseTests(SimpleTestCase):
    def test_content_prompt_mentions_no_quiz(self):
        settings = LessonGenerationSettings(generate_quiz=False, skip_exercise=True)
        prompt = build_lesson_content_prompt(
            inputs={
                'course_name': 'C',
                'course_type': 'sprint',
                'lesson_title': 'T',
                'lesson_description': 'D',
            },
            settings=settings,
        )
        self.assertIn('Do not invent quiz', prompt)
        self.assertIn('Do not invent exercises', prompt)

    def test_source_beats_mismatched_title(self):
        settings = LessonGenerationSettings()
        source = (
            'Density is mass per unit volume. Specific gravity is the ratio of '
            'a body\'s weight density to water. Hydrotherapy pools operate at '
            '33.5-35.5 degrees Celsius.'
        )
        inputs = {
            'course_name': 'How to make a caramel macchiato',
            'course_type': 'sprint',
            'lesson_title': 'Crafting the Perfect Caramel Macchiato',
            'lesson_description': source,
        }
        content = build_lesson_content_prompt(inputs=inputs, settings=settings)
        metadata = build_lesson_metadata_prompt(inputs=inputs, settings=settings)
        for prompt in (content, metadata):
            self.assertIn('SOURCE MATERIAL', prompt)
            self.assertIn('33.5-35.5 degrees Celsius', prompt)
            self.assertIn('IGNORE the title/course topic', prompt)
            self.assertIn('labels only', prompt)
            self.assertIn('do not invent a new subject', prompt.lower())
        self.assertIn('If the working title names a DIFFERENT subject', metadata)

    def test_image_prompts_use_source_not_title(self):
        source = (
            'Density is mass per unit volume. Hydrotherapy pools operate at '
            '33.5-35.5 degrees Celsius.'
        )
        brief = build_image_brief_meta_prompt(
            course_name='How to make a caramel macchiato',
            course_category='',
            course_topic='',
            lesson_title='Crafting the Perfect Caramel Macchiato',
            lesson_summary='',
            lesson_description=source,
            lesson_outcomes=['Explain specific gravity'],
            source_text=source,
        )
        fallback = build_lesson_image_prompt(
            clean_title='Crafting the Perfect Caramel Macchiato',
            short_summary='',
            source_text=source,
        )
        for prompt in (brief, fallback):
            self.assertIn('SOURCE', prompt)
            self.assertIn('Hydrotherapy pools', prompt)
            self.assertTrue(
                'label only' in prompt.lower() or 'labels only' in prompt.lower(),
                prompt,
            )
        self.assertIn('IGNORE the title/course topic', brief)

    def test_classic_structure_uses_description_and_exact_count(self):
        source = (
            'Density is mass per unit volume. Hydrotherapy pools operate at '
            '33.5-35.5 degrees Celsius.'
        )
        blueprint = {
            'topic': 'How to make a caramel macchiato',
            'total_classes': 6,
            'generation_settings': {
                'reading_level': 'foundational',
                'length': 'short',
                'depth': 'overview',
            },
        }
        prompt = build_course_structure_prompt(
            course_name='How to make a caramel macchiato',
            description=source,
            blueprint=blueprint,
            blueprint_extra=_blueprint_structure_prompt_section(blueprint),
        )
        self.assertIn('SOURCE BRIEF', prompt)
        self.assertIn('Hydrotherapy pools', prompt)
        self.assertIn('EXACTLY 6 lessons', prompt)
        self.assertIn('Do not use a 12-30 default', prompt)
        self.assertNotIn('total 12-30 lessons', prompt)
        self.assertIn('Lesson length — produce 4-6 content blocks', prompt)
        self.assertEqual(target_lesson_count(blueprint), 6)
        self.assertEqual(target_lesson_count({'total_classes': 80}), 80)

    def test_structure_extras_work_without_topic(self):
        extra = _blueprint_structure_prompt_section({
            'total_classes': 8,
            'class_length': '30_min',
            'generation_settings': {'length': 'short'},
        })
        self.assertIn('EXACTLY 8 lessons', extra)
        self.assertTrue(extra)

    def test_normalize_trims_extra_lessons(self):
        modules = [
            {'name': 'A', 'lessons': [{'title': '1'}, {'title': '2'}, {'title': '3'}]},
            {'name': 'B', 'lessons': [{'title': '4'}, {'title': '5'}]},
        ]
        trimmed = _normalize_modules_to_lesson_count(modules, 4)
        titles = [lesson['title'] for module in trimmed for lesson in module['lessons']]
        self.assertEqual(titles, ['1', '2', '3', '4'])


class LessonHeroIcebergTests(SimpleTestCase):
    def test_hero_key_is_stable_webp_path(self):
        lesson = MagicMock()
        lesson.id = 42
        lesson.slug = 'How To Brew'
        self.assertEqual(
            _lesson_hero_iceberg_key(lesson),
            'lesson_hero_images/lesson_42_howtobrew.webp',
        )

    def test_generate_ai_lesson_image_uploads_to_iceberg(self):
        from myApp.dashboard_views import generate_ai_lesson_image

        lesson = MagicMock()
        lesson.id = 7
        lesson.slug = 'demo'
        lesson.title = 'Demo'
        lesson.ai_clean_title = 'Demo'
        lesson.ai_short_summary = 'Summary'
        lesson.tenant = MagicMock()
        lesson.course = MagicMock()
        lesson.ai_hero_image_url = ''
        lesson.save = MagicMock()

        client = MagicMock()
        response = MagicMock()
        response.data = [MagicMock()]
        # Minimal valid 1x1 PNG
        import base64
        png_b64 = (
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
        )
        response.data[0].b64_json = png_b64
        client.images.generate.return_value = response

        with patch('myApp.dashboard_views.generate_image_brief', return_value='A hero banner'), \
             patch('myApp.utils.iceberg.is_configured', return_value=True), \
             patch('myApp.utils.iceberg.upload_bytes', return_value='https://cdn.example/t1/lesson_hero_images/lesson_7_demo.webp') as upload_bytes, \
             patch('myApp.dashboard_views.AIUsageLog') as usage_log:
            usage_log.objects.create = MagicMock()
            url = generate_ai_lesson_image(client, lesson, MagicMock())

        self.assertTrue(url.startswith('https://cdn.example/'))
        upload_bytes.assert_called_once()
        args, kwargs = upload_bytes.call_args
        self.assertEqual(args[1], 'lesson_hero_images/lesson_7_demo.webp')
        self.assertEqual(args[2], 'image/webp')
        lesson.save.assert_called()


class StructuredAiResultTests(SimpleTestCase):
    def test_metadata_failure_is_not_silent_success(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError('boom')
        result = generate_ai_lesson_metadata(
            client=client,
            lesson_title='T',
            lesson_description='D',
            course_name='C',
            course_type='sprint',
        )
        self.assertFalse(result['ok'])
        self.assertIn('boom', result['error'] or '')

    def test_content_empty_is_failure(self):
        client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '{"content": []}'
        response.usage = None
        client.chat.completions.create.return_value = response
        with patch('myApp.dashboard_views._log_openai_usage'):
            result = generate_ai_lesson_content(
                client=client,
                lesson_title='T',
                lesson_description='D',
                course_name='C',
                course_type='sprint',
            )
        self.assertFalse(result['ok'])
