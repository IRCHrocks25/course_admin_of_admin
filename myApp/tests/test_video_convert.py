"""Tests for lesson-note WebM conversion."""
import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from myApp.utils.video import convert_to_webm


class ConvertToWebmTests(SimpleTestCase):
    def test_copies_existing_webm_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'clip.webm')
            dst = os.path.join(tmp, 'out.webm')
            with open(src, 'wb') as fh:
                fh.write(b'WEBMFAKE')
            convert_to_webm(src, dst)
            with open(dst, 'rb') as fh:
                self.assertEqual(fh.read(), b'WEBMFAKE')

    def test_missing_ffmpeg_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'clip.mp4')
            dst = os.path.join(tmp, 'out.webm')
            with open(src, 'wb') as fh:
                fh.write(b'not-a-video')
            with mock.patch('myApp.utils.video.shutil.which', return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    convert_to_webm(src, dst)
            self.assertIn('ffmpeg', str(ctx.exception).lower())
