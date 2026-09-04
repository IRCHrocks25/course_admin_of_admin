"""Unit tests for lesson video-script flatten / normalize / HTML / worker gate."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from myApp.utils.video_script import (
    SOURCE_MAX_CHARS,
    build_video_script_prompt,
    flatten_lesson_source,
    normalize_video_script,
    render_script_html,
    script_display_title,
    script_doc_title,
    truncate_source,
)


def _lesson(content=None, rough_notes=''):
    return SimpleNamespace(content=content if content is not None else {}, rough_notes=rough_notes)


class FlattenLessonSourceTests(SimpleTestCase):
    def test_flattens_editorjs_blocks(self):
        lesson = _lesson({
            'blocks': [
                {'type': 'header', 'data': {'text': 'Safety first'}},
                {'type': 'paragraph', 'data': {'text': 'Wear <b>gloves</b>.'}},
                {'type': 'list', 'data': {'items': ['Step one', {'content': 'Step two'}]}},
                {'type': 'quote', 'data': {'text': 'Stay calm', 'caption': 'Coach'}},
                {'type': 'table', 'data': {'content': [['A', 'B'], ['1', '2']]}},
            ]
        })
        text = flatten_lesson_source(lesson)
        self.assertIn('Safety first', text)
        self.assertIn('Wear gloves.', text)
        self.assertIn('- Step one', text)
        self.assertIn('- Step two', text)
        self.assertIn('Stay calm — Coach', text)
        self.assertIn('A | B', text)

    def test_flattens_checklist(self):
        lesson = _lesson({
            'blocks': [
                {'type': 'checklist', 'data': {'items': [
                    {'text': 'Gloves on', 'checked': True},
                    {'content': 'Thermometer ready', 'checked': False},
                ]}},
            ]
        })
        text = flatten_lesson_source(lesson)
        self.assertIn('[x] Gloves on', text)
        self.assertIn('[ ] Thermometer ready', text)

    def test_falls_back_to_rough_notes(self):
        lesson = _lesson({'blocks': []}, rough_notes='  Paste from SOP  ')
        self.assertEqual(flatten_lesson_source(lesson), 'Paste from SOP')

    def test_empty_when_both_missing(self):
        lesson = _lesson({}, rough_notes='')
        self.assertEqual(flatten_lesson_source(lesson), '')


class ScriptDisplayTitleTests(SimpleTestCase):
    def test_prefers_ai_clean_title_over_working_title(self):
        lesson = SimpleNamespace(
            title='How to make a caramel macchiato',
            ai_clean_title='Personal Development and Its Importance',
        )
        self.assertEqual(
            script_display_title(lesson),
            'Personal Development and Its Importance',
        )

    def test_falls_back_to_working_title(self):
        lesson = SimpleNamespace(title='Safety briefing', ai_clean_title='')
        self.assertEqual(script_display_title(lesson), 'Safety briefing')


class BuildVideoScriptPromptTests(SimpleTestCase):
    def test_treats_title_as_label_and_keeps_source_first(self):
        prompt = build_video_script_prompt(
            'Personal development is a lifelong journey.',
            'How to make a caramel macchiato',
            course_name='How to make a caramel macchiato',
        )
        source_at = prompt.index('Personal development is a lifelong journey.')
        self.assertIn('labels only', prompt.lower())
        self.assertIn('IGNORE the', prompt)
        self.assertLess(prompt.index('SOURCE START'), source_at)
        self.assertIn('How to make a caramel macchiato', prompt)


class TruncateSourceTests(SimpleTestCase):
    def test_keeps_head_and_tail(self):
        text = 'A' * 100 + 'MIDDLE' + 'Z' * 100
        out = truncate_source(text, max_chars=40)
        self.assertLessEqual(len(out), SOURCE_MAX_CHARS)
        self.assertTrue(out.startswith('A'))
        self.assertTrue(out.endswith('Z'))
        self.assertIn('shortened', out)


class NormalizeVideoScriptTests(SimpleTestCase):
    def test_caps_sections_and_shot_list(self):
        data = {
            'title': 'From model',
            'sections': [{'heading': f'S{i}', 'narration': f'n{i}'} for i in range(20)],
            'shot_list': [f'shot {i}' for i in range(15)],
            'hook': {'narration': 'open'},
            'close': {'narration': 'end'},
        }
        script = normalize_video_script(data, 'Fallback title')
        self.assertEqual(len(script['sections']), 12)
        self.assertEqual(len(script['shot_list']), 7)
        self.assertEqual(script['title'], 'From model')
        self.assertEqual(script['hook']['narration'], 'open')
        self.assertEqual(script['close']['narration'], 'end')
        self.assertEqual(script['duration'], 'about 5 minutes')

    def test_accepts_b_roll_aliases(self):
        script = normalize_video_script(
            {'hook': {'visual': 'Close-up of gloves'}, 'close': {'b-roll': 'Pack-out'}},
            'T',
        )
        self.assertEqual(script['hook']['b_roll'], 'Close-up of gloves')
        self.assertEqual(script['close']['b_roll'], 'Pack-out')


class RenderScriptHtmlTests(SimpleTestCase):
    def test_shooting_table_columns(self):
        script = normalize_video_script(
            {
                'hook': {
                    'time': '0:00–0:20',
                    'narration': 'Start here',
                    'on_screen': 'HOOK',
                    'b_roll': 'Wide shot',
                },
                'sections': [{
                    'time': '0:20–2:00',
                    'heading': 'WHY',
                    'narration': 'Because it matters',
                    'on_screen': 'WHY',
                    'b_roll': 'Close-up',
                }],
                'close': {
                    'time': '4:30–5:00',
                    'narration': 'Do this today',
                    'on_screen': 'ACTION',
                    'b_roll': 'Pack-out',
                },
                'shot_list': ['Pacing: Hold the glove close-up for two seconds'],
            },
            'Gloves On',
        )
        html = render_script_html(script, 'Gloves On')
        self.assertIn('Gloves On — Video Script', html)
        self.assertIn('Time', html)
        self.assertIn('Visual', html)
        self.assertIn('Narration (VO)', html)
        self.assertIn('On-Screen Text', html)
        self.assertIn('Start here', html)
        self.assertIn('Because it matters', html)
        self.assertIn('<b>Pacing:</b>', html)
        self.assertEqual(script_doc_title('Gloves On'), 'Gloves On — Video Script')


class MaybeSpawnVideoScriptTests(SimpleTestCase):
    @override_settings(GENERATE_LESSON_SCRIPTS=False)
    def test_skipped_when_disabled(self):
        from myApp.dashboard_views import _maybe_spawn_video_script

        with patch('myApp.dashboard_views._generate_and_upload_script') as spawn:
            result = _maybe_spawn_video_script(MagicMock(id=1), 'Course', 'folder')
        self.assertIsNone(result)
        spawn.assert_not_called()

    @override_settings(GENERATE_LESSON_SCRIPTS=True)
    def test_spawned_when_enabled(self):
        from myApp.dashboard_views import _maybe_spawn_video_script

        lesson = MagicMock(id=9)
        with patch('myApp.dashboard_views._generate_and_upload_script', return_value='thread') as spawn:
            result = _maybe_spawn_video_script(lesson, 'Course', 'folder')
        self.assertEqual(result, 'thread')
        spawn.assert_called_once_with(9, 'Course', 'folder')
