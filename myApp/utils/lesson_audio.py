"""
Lesson audio narration pipeline (OpenAI TTS -> Cloudinary).

Pipeline:
    Lesson text -> chunk (<=4000 chars) -> OpenAI TTS (mp3 per chunk)
    -> ffmpeg concat (byte-concat fallback) -> Cloudinary upload
    -> lesson.audio_url

All entry points should call generate_lesson_audio_async(lesson) so lesson
creation / HTTP responses are never blocked. Nothing in this module raises:
failures land in lesson.audio_status / lesson.audio_error.
"""
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from decimal import Decimal

from django.db import close_old_connections
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

# OpenAI TTS rejects inputs > 4096 characters; stay safely under.
_MAX_CHUNK_CHARS = 4000

# Billing: OpenAI tts-1 is $15 per 1M input characters.
_DEFAULT_TTS_RATE_PER_MILLION = '15'


def build_lesson_narration_text(lesson):
    """
    Build the plain-text narration script for a lesson.

    Concatenates: title, outcomes, description, and Editor.js content blocks
    (paragraph / header / list / quote). Returns '' if there is nothing
    narratable.
    """
    sections = []

    title = (lesson.ai_clean_title or lesson.title or '').strip()
    if title:
        sections.append(title)

    outcomes = lesson.ai_outcomes if isinstance(lesson.ai_outcomes, list) else []
    outcome_lines = [strip_tags(str(o)).strip().rstrip('.') for o in outcomes if strip_tags(str(o)).strip()]
    if outcome_lines:
        sections.append('This lesson will produce: ' + '. '.join(outcome_lines) + '.')

    description = strip_tags(lesson.ai_full_description or lesson.description or '').strip()
    if description:
        sections.append(description)

    content = lesson.content if isinstance(lesson.content, dict) else {}
    for block in content.get('blocks', []) or []:
        if not isinstance(block, dict):
            continue
        block_type = block.get('type')
        data = block.get('data') if isinstance(block.get('data'), dict) else {}
        if block_type in ('paragraph', 'header'):
            text = strip_tags(data.get('text', '')).strip()
            if text:
                sections.append(text)
        elif block_type == 'list':
            items = data.get('items') if isinstance(data.get('items'), list) else []
            lines = []
            for item in items:
                # Editor.js list items can be strings or {content: ...} dicts
                raw = item.get('content', '') if isinstance(item, dict) else str(item)
                text = strip_tags(raw).strip()
                if text:
                    lines.append(text)
            if lines:
                sections.append('. '.join(lines) + '.')
        elif block_type == 'quote':
            text = strip_tags(data.get('text', '')).strip()
            if text:
                sections.append(f'Quote: {text}')

    narration = '\n\n'.join(sections)
    # Normalize whitespace: collapse runs of spaces/tabs, cap blank lines at 2
    narration = re.sub(r'[ \t]+', ' ', narration)
    narration = re.sub(r'\n{3,}', '\n\n', narration)
    return narration.strip()


def _chunk_text(text, max_chars=_MAX_CHUNK_CHARS):
    """Split text into chunks under max_chars, preferring paragraph then sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = []
    for para in text.split('\n\n'):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            paragraphs.append(para)
        else:
            # Split oversized paragraphs on sentence boundaries
            current = ''
            for sentence in re.split(r'(?<=[.!?])\s+', para):
                if current and len(current) + len(sentence) + 1 > max_chars:
                    paragraphs.append(current)
                    current = sentence
                else:
                    current = f'{current} {sentence}'.strip() if current else sentence
                # A single sentence longer than max_chars: hard-split it
                while len(current) > max_chars:
                    paragraphs.append(current[:max_chars])
                    current = current[max_chars:]
            if current:
                paragraphs.append(current)

    # Pack paragraphs into chunks without exceeding max_chars
    chunks = []
    current = ''
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f'{current}\n\n{para}' if current else para
    if current:
        chunks.append(current)
    return chunks


def _tts_chunk(client, text, model, voice):
    """Generate MP3 bytes for one text chunk via OpenAI TTS."""
    resp = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        response_format='mp3',
    )
    audio_bytes = getattr(resp, 'content', None)
    if not audio_bytes:
        audio_bytes = resp.read()
    return audio_bytes


def _concat_mp3_chunks(chunk_paths, out_path):
    """
    Concatenate MP3 chunk files into out_path with ffmpeg. Falls back to raw
    byte concatenation (MP3 frames are self-contained, so this stays playable)
    when ffmpeg is unavailable or fails.
    """
    if len(chunk_paths) == 1:
        shutil.copyfile(chunk_paths[0], out_path)
        return

    if shutil.which('ffmpeg'):
        concat_list = out_path + '.txt'
        try:
            with open(concat_list, 'w', encoding='utf-8') as fh:
                for path in chunk_paths:
                    escaped = path.replace('\\', '/').replace("'", "'\\''")
                    fh.write(f"file '{escaped}'\n")
            subprocess.run(
                ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_list,
                 '-c', 'copy', out_path, '-y'],
                check=True, capture_output=True,
            )
            return
        except Exception as e:
            logger.warning('ffmpeg concat failed, falling back to byte concat: %s', e)
        finally:
            try:
                os.remove(concat_list)
            except OSError:
                pass

    with open(out_path, 'wb') as out:
        for path in chunk_paths:
            with open(path, 'rb') as chunk:
                shutil.copyfileobj(chunk, out)


def _probe_duration_seconds(mp3_path):
    """Return MP3 duration in whole seconds via ffprobe, or 0 if unavailable."""
    if not shutil.which('ffprobe'):
        return 0
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', mp3_path],
            check=True, capture_output=True, text=True,
        )
        return int(float(result.stdout.strip()))
    except Exception:
        return 0


def _upload_audio(mp3_path, lesson):
    """
    Upload the narration MP3 to Iceberg; return the public URL or ''.

    Falls back to Cloudinary only when Iceberg is not configured, so audio
    generation still works in environments without Iceberg credentials.
    """
    from myApp.utils import iceberg

    if iceberg.is_configured():
        key = f"lesson_audio/lesson_{lesson.id}_{lesson.slug or 'audio'}.mp3"
        with open(mp3_path, 'rb') as fh:
            return iceberg.upload_fileobj(fh, key, 'audio/mpeg')

    logger.warning('Iceberg not configured; uploading lesson %s audio to Cloudinary', lesson.id)
    import cloudinary.uploader

    # Cloudinary stores audio under the "video" resource type.
    upload_result = cloudinary.uploader.upload(
        mp3_path,
        folder='lesson_audio',
        public_id=f"lesson_{lesson.id}_{lesson.slug or 'audio'}",
        resource_type='video',
        overwrite=True,
        format='mp3',
    )
    return (upload_result.get('secure_url') or '').strip()


def _log_tts_usage(lesson, model_name, char_count):
    """Log TTS spend to AIUsageLog using character count as the billing proxy."""
    try:
        from myApp.models import AIUsageLog

        close_old_connections()
        rate = Decimal(os.getenv('OPENAI_RATE_TTS_PER_MILLION', _DEFAULT_TTS_RATE_PER_MILLION))
        AIUsageLog.objects.create(
            tenant=lesson.tenant,
            course=lesson.course,
            lesson=lesson,
            provider='openai',
            feature='lesson_audio',
            model_name=model_name,
            request_id='',
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=char_count,
            input_rate_per_million=rate,
            output_rate_per_million=0,
            cost_usd=(Decimal(char_count) / Decimal(1_000_000)) * rate,
        )
    except Exception:
        pass  # cost logging must not break audio generation


def generate_lesson_audio(lesson):
    """
    Generate MP3 narration for a lesson and store it on lesson.audio_url.

    Returns the audio URL, or '' when generation was skipped or failed.
    Never raises — callers are never blocked by narration problems.
    """
    def _fail(message):
        # Reconnect if the remote DB dropped the connection during long TTS calls.
        close_old_connections()
        lesson.audio_status = 'failed'
        lesson.audio_error = str(message)[:1000]
        lesson.save(update_fields=['audio_status', 'audio_error'])
        logger.warning('Audio generation failed for lesson %s: %s', getattr(lesson, 'id', '?'), message)
        return ''

    def _skip(message):
        close_old_connections()
        lesson.audio_status = 'skipped'
        lesson.audio_error = str(message)[:1000]
        lesson.save(update_fields=['audio_status', 'audio_error'])
        logger.info('Audio generation skipped for lesson %s: %s', getattr(lesson, 'id', '?'), message)
        return ''

    try:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return _skip('OPENAI_API_KEY is not configured.')
        try:
            from openai import OpenAI
        except ImportError:
            return _skip('openai package is not installed.')

        narration = build_lesson_narration_text(lesson)
        if not narration:
            return _fail('Lesson has no narratable text content.')

        close_old_connections()
        lesson.audio_status = 'processing'
        lesson.audio_error = ''
        lesson.save(update_fields=['audio_status', 'audio_error'])

        client = OpenAI(api_key=api_key)
        model = os.getenv('OPENAI_TTS_MODEL', 'tts-1')
        voice = os.getenv('OPENAI_TTS_VOICE', 'nova')
        chunks = _chunk_text(narration)

        with tempfile.TemporaryDirectory(prefix='lesson_audio_') as tmpdir:
            chunk_paths = []
            for idx, chunk in enumerate(chunks):
                audio_bytes = _tts_chunk(client, chunk, model, voice)
                if not audio_bytes:
                    return _fail(f'OpenAI TTS returned no audio for chunk {idx}.')
                path = os.path.join(tmpdir, f'chunk_{idx:03d}.mp3')
                with open(path, 'wb') as fh:
                    fh.write(audio_bytes)
                chunk_paths.append(path)

            out_path = os.path.join(tmpdir, 'lesson.mp3')
            _concat_mp3_chunks(chunk_paths, out_path)
            duration = _probe_duration_seconds(out_path)

            audio_url = _upload_audio(out_path, lesson)
            if not audio_url:
                return _fail('Audio upload returned no URL (check Iceberg/Cloudinary config and logs).')

        # TTS + upload can take minutes; the remote DB may have dropped the
        # idle connection in the meantime. Reconnect before saving.
        close_old_connections()
        lesson.audio_url = audio_url
        lesson.audio_duration_seconds = duration
        lesson.audio_status = 'completed'
        lesson.audio_error = ''
        lesson.save(update_fields=['audio_url', 'audio_duration_seconds', 'audio_status', 'audio_error'])

        _log_tts_usage(lesson, model, len(narration))
        logger.info('Audio generated for lesson %s (%s chars, %s chunks)', lesson.id, len(narration), len(chunks))
        return audio_url

    except Exception as e:
        try:
            return _fail(e)
        except Exception:
            logger.exception('Audio generation hard-failed for lesson %s', getattr(lesson, 'id', '?'))
            return ''


def generate_lesson_audio_async(lesson):
    """
    Generate lesson narration in a daemon thread so the caller never blocks.

    Marks the lesson 'processing' immediately for UI feedback, then re-fetches
    it inside the thread on a fresh DB connection.
    """
    lesson.audio_status = 'processing'
    lesson.audio_error = ''
    lesson.save(update_fields=['audio_status', 'audio_error'])

    lesson_id = lesson.id

    def _worker():
        from django.db import connection
        # Drop the connection inherited from the request thread; Django will
        # open a fresh one for this thread on first query.
        connection.close()
        try:
            from myApp.models import Lesson
            fresh_lesson = Lesson.objects.get(id=lesson_id)
            generate_lesson_audio(fresh_lesson)
        except Exception:
            logger.exception('Async audio generation crashed for lesson %s', lesson_id)

    thread = threading.Thread(target=_worker, daemon=True, name=f'lesson-audio-{lesson_id}')
    thread.start()
    return thread
