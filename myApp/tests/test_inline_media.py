"""Tests for inline note image/video helpers and student article enrichment."""
from django.test import SimpleTestCase

from myApp.utils.inline_media import (
    enrich_video_block,
    is_direct_video_file,
    normalize_inline_video_embed,
)
from myApp.utils.lesson_blocks import prepare_lesson_article
from myApp.management.commands.split_nested_lesson_headers import _split_points


class InlineMediaNormalizeTests(SimpleTestCase):
    def test_vimeo_watch_to_player(self):
        self.assertEqual(
            normalize_inline_video_embed('https://vimeo.com/123456789'),
            'https://player.vimeo.com/video/123456789',
        )

    def test_youtube_watch_to_embed(self):
        self.assertEqual(
            normalize_inline_video_embed('https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
        )

    def test_drive_file_to_preview(self):
        self.assertEqual(
            normalize_inline_video_embed('https://drive.google.com/file/d/ABC123xyz/view'),
            'https://drive.google.com/file/d/ABC123xyz/preview',
        )

    def test_rejects_javascript_scheme(self):
        self.assertEqual(normalize_inline_video_embed('javascript:alert(1)'), '')

    def test_rejects_data_scheme(self):
        self.assertEqual(normalize_inline_video_embed('data:text/html,<script>'), '')

    def test_enrich_video_block(self):
        block = enrich_video_block({
            'type': 'video',
            'data': {'url': 'https://vimeo.com/42', 'caption': 'Demo'},
        })
        self.assertEqual(block['data']['embed_url'], 'https://player.vimeo.com/video/42')
        self.assertEqual(block['data']['file_url'], '')

    def test_direct_file_uses_video_tag_not_iframe(self):
        self.assertTrue(is_direct_video_file('https://cdn.example.com/clip.webm'))
        self.assertTrue(is_direct_video_file(
            'https://cdn.katalyst-crm.com/objects/d36bfb91-84a8-d032-c158-f6eecdabc573',
        ))
        block = enrich_video_block({
            'type': 'video',
            'data': {
                'url': 'https://cdn.katalyst-crm.com/objects/d36bfb91-84a8-d032-c158-f6eecdabc573',
                'source': 'upload',
            },
        })
        self.assertEqual(block['data']['file_url'], block['data']['url'])
        self.assertEqual(block['data']['embed_url'], '')


class PrepareLessonArticleVideoTests(SimpleTestCase):
    def test_enriches_video_block_embed_url(self):
        article = prepare_lesson_article({
            'blocks': [
                {'type': 'header', 'data': {'text': 'Forward Gait', 'level': 2}},
                {'type': 'video', 'data': {'url': 'https://vimeo.com/999', 'caption': 'Demo'}},
            ]
        })
        video = next(b for b in article['blocks'] if b['type'] == 'video')
        self.assertEqual(video['data']['embed_url'], 'https://player.vimeo.com/video/999')
        self.assertEqual(video['data']['caption'], 'Demo')

    def test_drops_unsafe_video_embed(self):
        article = prepare_lesson_article({
            'blocks': [
                {'type': 'video', 'data': {'url': 'javascript:alert(1)'}},
            ]
        })
        video = article['blocks'][0]
        self.assertEqual(video['data']['embed_url'], '')


class SplitNestedHeaderHelpersTests(SimpleTestCase):
    def test_split_points_finds_nested_headers(self):
        blocks = [
            {'type': 'paragraph', 'data': {'text': 'Intro'}},
            {'type': 'header', 'data': {'text': '4.3.1 Forward Gait', 'level': 2}},
            {'type': 'paragraph', 'data': {'text': 'Fwd'}},
            {'type': 'header', 'data': {'text': '4.3.2 Retro Gait', 'level': 2}},
            {'type': 'paragraph', 'data': {'text': 'Back'}},
        ]
        points = _split_points(blocks)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0], (1, '4.3.1', 'Forward Gait'))
        self.assertEqual(points[1], (3, '4.3.2', 'Retro Gait'))

    def test_split_chunks_cover_full_content(self):
        blocks = [
            {'type': 'paragraph', 'data': {'text': 'Overview'}},
            {'type': 'header', 'data': {'text': '4.3.1 Forward Gait', 'level': 2}},
            {'type': 'paragraph', 'data': {'text': 'Forward copy'}},
            {'type': 'header', 'data': {'text': '4.3.2 Retro Gait', 'level': 2}},
            {'type': 'paragraph', 'data': {'text': 'Retro copy'}},
            {'type': 'header', 'data': {'text': '4.3.3 Lateral Gait', 'level': 2}},
            {'type': 'paragraph', 'data': {'text': 'Lateral copy'}},
        ]
        points = _split_points(blocks)
        remaining = blocks[: points[0][0]]
        chunks = []
        for i, (start, key, suffix) in enumerate(points):
            end = points[i + 1][0] if i + 1 < len(points) else len(blocks)
            title = f'{key} {suffix}'.strip()
            chunks.append((title, blocks[start:end]))
        self.assertEqual([b['data']['text'] for b in remaining], ['Overview'])
        self.assertEqual(
            [t for t, _ in chunks],
            ['4.3.1 Forward Gait', '4.3.2 Retro Gait', '4.3.3 Lateral Gait'],
        )
        self.assertEqual(chunks[0][1][1]['data']['text'], 'Forward copy')
