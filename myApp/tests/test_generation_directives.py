"""Tests for generation directives, seed parsing, and module grouping."""
import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from myApp.dashboard_views import (
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
from myApp.utils.prompts import LessonGenerationSettings, build_lesson_content_prompt


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
