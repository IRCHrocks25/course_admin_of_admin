"""Convert an uploaded video to WebM (VP9/Opus) before Iceberg upload."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

CONVERT_TIMEOUT_SECONDS = 180

_VP9_ARGS = [
    '-c:v', 'libvpx-vp9',
    '-deadline', 'realtime',
    '-cpu-used', '8',
    '-crf', '36',
    '-b:v', '0',
    '-row-mt', '1',
    '-c:a', 'libopus',
    '-b:a', '96k',
    '-ac', '2',
]

_VP8_ARGS = [
    '-c:v', 'libvpx',
    '-deadline', 'realtime',
    '-cpu-used', '8',
    '-b:v', '1M',
    '-c:a', 'libopus',
    '-b:a', '96k',
    '-ac', '2',
]


def convert_to_webm(src_path: str, dst_path: str) -> None:
    """Write a WebM file at dst_path from src_path. Raises RuntimeError on failure."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Video conversion needs ffmpeg on the server.')

    if not src_path or not os.path.isfile(src_path):
        raise RuntimeError('The uploaded video could not be read.')

    if (os.path.splitext(src_path)[1] or '').lower() == '.webm':
        shutil.copyfile(src_path, dst_path)
        return

    last_error = ''
    for codec_args in (_VP9_ARGS, _VP8_ARGS):
        cmd = [ffmpeg, '-y', '-i', src_path, '-map', '0:v:0', '-map', '0:a?', *codec_args, dst_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=CONVERT_TIMEOUT_SECONDS)
            if os.path.isfile(dst_path) and os.path.getsize(dst_path) > 0:
                return
        except subprocess.TimeoutExpired:
            last_error = 'Conversion timed out. Try a shorter clip.'
            break
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or b'').decode('utf-8', errors='replace')[-240:]
            last_error = err or str(exc)
            logger.warning('ffmpeg webm convert failed: %s', last_error)
        except OSError as exc:
            last_error = str(exc)
            break

    raise RuntimeError(last_error or 'Could not convert that video to WebM.')
