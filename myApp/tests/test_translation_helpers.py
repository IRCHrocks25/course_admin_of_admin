"""Tests for structure-preserving Editor.js translation helpers."""
from django.test import SimpleTestCase

from myApp.utils.translation import (
    _collect_editorjs_strings,
    _inject_editorjs_strings,
    content_quality_ok,
)


class EditorJsTranslationHelpersTest(SimpleTestCase):
    def test_collect_and_inject_preserves_block_structure(self):
        blocks = [
            {'id': '1', 'type': 'paragraph', 'data': {'text': 'Hello'}},
            {'id': '2', 'type': 'header', 'data': {'text': 'Title', 'level': 2}},
            {'id': '3', 'type': 'list', 'data': {'style': 'unordered', 'items': ['One', 'Two']}},
        ]
        strings, refs = _collect_editorjs_strings(blocks)
        self.assertEqual(len(strings), 4)
        translated = ['Ciao', 'Titolo', 'Uno', 'Due']
        result = _inject_editorjs_strings(blocks, refs, translated)
        self.assertEqual(result[0]['type'], 'paragraph')
        self.assertEqual(result[0]['id'], '1')
        self.assertEqual(result[0]['data']['text'], 'Ciao')
        self.assertEqual(result[2]['data']['items'][1], 'Due')

    def test_content_quality_ok_rejects_corrupted_blocks(self):
        source = {'blocks': [{'type': 'paragraph', 'data': {'text': 'A'}}]}
        good = {'blocks': [{'type': 'paragraph', 'data': {'text': 'B'}}]}
        bad = {'blocks': ['raw string']}
        self.assertTrue(content_quality_ok(source, good))
        self.assertFalse(content_quality_ok(source, bad))
