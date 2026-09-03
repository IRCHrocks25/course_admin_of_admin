"""
Faithful PDF → CourseForge structure.

Deterministic splitter:
- chapters become modules
- X.Y sections become parent lessons
- nested X.Y.Z sections become standalone sub-lessons (indented in the syllabus)
- section order is normalized so parents sort before their children
- text is copied verbatim; figures go to Iceberg; chapter quizzes become LessonQuiz rows
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

MIN_IMAGE_EDGE = 80

CHAPTER_INTRO_RE = re.compile(
    r'^INTRODUCTION\s*[-–—]\s*CHAPTER\s+(\d+)\b(.*)$',
    re.IGNORECASE,
)
CHAPTER_HEAD_RE = re.compile(
    r'^CHAPTER\s+(\d+)(?!\.\d+)(?:\s+(.+))?$',
    re.IGNORECASE,
)
SECTION_RE = re.compile(r'^(\d+)\.(\d+)(?:\.(\d+))?\s*(.*)$')
SECTION_NUMBER_ONLY_RE = re.compile(r'^(\d+)\.(\d+)(?:\.(\d+))?$')
NUMERIC_RANGE_RE = re.compile(r'^\d+\.\d+\s*[-–—]\s*\d+\.\d+')
RUNNING_HEADER_Y0 = 55.0
SUMMARY_RE = re.compile(
    r'^(?:CHAPTER(?:\s+\d+)?\s+SUMMARY|CHAPTER\s+SUMMARY(?:\s*[-–—]\s*CHAPTER\s+\d+)?)\s*$',
    re.IGNORECASE,
)
QUIZ_HEAD_RE = re.compile(r'^CHAPTER(?:\s+\d+)?\s+QUIZ\s*$', re.IGNORECASE)
CONCLUSION_RE = re.compile(
    r'^CONCLUSION(?:\s*[-–—]\s*CHAPTER\s+\d+)?\s*$',
    re.IGNORECASE,
)
TOC_LINE_RE = re.compile(r'^TABLE OF CONTENTS\b', re.IGNORECASE)
QUESTION_RE = re.compile(r'^Question\s+(\d+)\s*$', re.IGNORECASE)
OPTION_RE = re.compile(r'^([A-D])[\.\)]\s*(.*)$', re.IGNORECASE)
NUMBERED_OPTION_RE = re.compile(r'^([1-4])[\.\)]\s+(.*)$')
CORRECT_RE = re.compile(r'^(?:Correct\s+)?Answer\s*[:\-]\s*([A-D])\b', re.IGNORECASE)
_NUMBERED_OPTION_LETTER = {'1': 'A', '2': 'B', '3': 'C', '4': 'D'}
LEARNING_OBJ_RE = re.compile(r'^Learning Objectives\s*$', re.IGNORECASE)
LABELED_HEADING_RE = re.compile(
    r'^(Test|Layer|Step|Phase|Stage)\s+\d+\s*[-–—:]\s+\S+',
    re.IGNORECASE,
)
BULLET_RE = re.compile(r'^[\*\u2022\u2013\-]\s+(.+)$')
NUMBERED_RE = re.compile(r'^(\d+)[\.\)]\s+(.+)$')
SELECT_ONE_RE = re.compile(r'^Select one correct answer\s*$', re.IGNORECASE)

CHAPTER_SECTION_ECHO_RE = re.compile(
    r'^CHAPTER\s+(\d+\.\d+(?:\.\d+)?)\b(.*)$',
    re.IGNORECASE,
)
_TITLE_ECHO_WORDS = {
    'SAFETY', 'ENVIRONMENT', 'RISK', 'MANAGEMENT', 'EMERGENCY', 'READINESS',
    'CLINICAL', 'SCREENING', 'WATER', 'INTAKE', 'FOUNDATIONS', 'AQUATIC',
    'THERAPY', 'CHAPTER',
}

SKIP_HEADING_DUP_RE = re.compile(
    r'^(CHAPTER\s+\d+(\.\d+)*|INTRODUCTION|OVERVIEW|STUDY TIME|ASSESSMENT NOTE|CLINICAL RELEVANCE)\s*$',
    re.IGNORECASE,
)


def _norm_space(text: str) -> str:
    cleaned = (text or '').replace('\u200b', '').replace('\u200c', '')
    return re.sub(r'[ \t]+', ' ', cleaned).strip()


def _is_false_section(text: str, title: str | None = None) -> bool:
    """Numbers like 33.5 - 35.5°C are body copy, not lesson X.Y headings."""
    title = _norm_space(title if title is not None else (SECTION_RE.match(text).group(4) if SECTION_RE.match(text) else ''))
    return bool(
        NUMERIC_RANGE_RE.match(text)
        or title.startswith('-')
        or (title.endswith('.') and len(text) > 80)
    )


def _is_all_caps_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 4:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.85 and len(line) <= 120


def extract_pdf_pages(pdf_bytes: bytes) -> dict[str, Any]:
    """Extract text lines and images from a PDF. Requires PyMuPDF."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    lines: list[dict[str, Any]] = []
    text_lines: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    try:
        for page_index, page in enumerate(doc):
            page_dict = page.get_text('dict') or {}
            for block in page_dict.get('blocks') or []:
                bbox = block.get('bbox') or (0, 0, 0, 0)
                y0 = float(bbox[1]) if len(bbox) > 1 else 0.0
                if block.get('type') == 0:
                    for line in block.get('lines') or []:
                        spans = line.get('spans') or []
                        text = ''.join(str(s.get('text') or '') for s in spans)
                        text = text.replace('\xa0', ' ').replace('\u200b', ' ').replace('\u200c', '').rstrip()
                        if not text.strip():
                            continue
                        size = 0.0
                        if spans:
                            size = max(float(s.get('size') or 0) for s in spans)
                        lines.append({
                            'text': text.strip(),
                            'page': page_index,
                            'y0': float((line.get('bbox') or (0, y0, 0, 0))[1]),
                            'size': size,
                        })
                elif block.get('type') == 1:
                    raw = block.get('image')
                    width = int(block.get('width') or 0)
                    height = int(block.get('height') or 0)
                    if not raw or width < MIN_IMAGE_EDGE or height < MIN_IMAGE_EDGE:
                        continue
                    ext = (block.get('ext') or 'png').lower()
                    content_type = 'image/jpeg' if ext in {'jpg', 'jpeg'} else 'image/png'
                    if ext not in {'jpg', 'jpeg', 'png'}:
                        try:
                            pix = fitz.Pixmap(raw) if isinstance(raw, (bytes, bytearray)) else None
                            if pix is None:
                                continue
                            if pix.n > 4:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            raw = pix.tobytes('png')
                            content_type = 'image/png'
                        except Exception:
                            continue
                    images.append({
                        'page': page_index,
                        'y0': y0,
                        'bytes': raw if isinstance(raw, (bytes, bytearray)) else b'',
                        'content_type': content_type,
                        'width': width,
                        'height': height,
                    })

            if not images or not any(img['page'] == page_index for img in images):
                for img_index, img in enumerate(page.get_images(full=True) or []):
                    xref = img[0]
                    try:
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n - pix.alpha > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        if pix.width < MIN_IMAGE_EDGE or pix.height < MIN_IMAGE_EDGE:
                            continue
                        images.append({
                            'page': page_index,
                            'y0': 0.0,
                            'bytes': pix.tobytes('png'),
                            'content_type': 'image/png',
                            'width': pix.width,
                            'height': pix.height,
                        })
                    except Exception:
                        continue
            raw_text = page.get_text('text') or ''
            for line_i, raw_line in enumerate(raw_text.splitlines()):
                cleaned = raw_line.replace('\xa0', ' ').replace('\u200b', ' ').replace('\u200c', '').strip()
                if cleaned:
                    text_lines.append({
                        'text': cleaned,
                        'page': page_index,
                        'y0': float(line_i),
                        'size': 11.0,
                    })
    finally:
        doc.close()

    images = [img for img in images if img.get('bytes')]
    return {
        'lines': _normalize_extracted_lines(lines),
        'text_lines': _normalize_extracted_lines(text_lines),
        'images': images,
    }


def _normalize_extracted_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join split heading fragments common in Google Docs PDF exports."""
    merged: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        item = dict(lines[i])
        text = item['text']
        nxt = lines[i + 1]['text'] if i + 1 < len(lines) else ''
        if SECTION_NUMBER_ONLY_RE.match(text) and nxt and not SECTION_NUMBER_ONLY_RE.match(nxt):
            item['text'] = f'{text} {nxt}'.strip()
            i += 2
            merged.append(item)
            continue
        head = CHAPTER_HEAD_RE.match(text)
        if head and not (head.group(2) or '').strip() and nxt and not CHAPTER_HEAD_RE.match(nxt):
            if _is_all_caps_heading(nxt) or (len(nxt) < 80 and not SECTION_RE.match(nxt)):
                item['text'] = f'{text} {nxt}'.strip()
                i += 2
                merged.append(item)
                continue
        if nxt and not SECTION_RE.match(nxt) and not CHAPTER_HEAD_RE.match(nxt):
            stripped = text.rstrip()
            if stripped.endswith(('&', '—', '–', ',')) or (
                SECTION_RE.match(stripped)
                and len(nxt.split()) <= 4
                and nxt[0].isupper()
                and not stripped.endswith('.')
            ):
                item['text'] = f'{stripped} {nxt}'.strip()
                i += 2
                merged.append(item)
                continue
        item['text'] = _clean_section_heading(item['text'])
        merged.append(item)
        i += 1
    return merged


def _is_list_continuation(line: str) -> bool:
    """Wrapped PDF lines that belong to the previous bullet/number, not a new block."""
    if not line:
        return False
    if (
        BULLET_RE.match(line)
        or NUMBERED_RE.match(line)
        or SECTION_RE.match(line)
        or CHAPTER_HEAD_RE.match(line)
        or LEARNING_OBJ_RE.match(line)
        or LABELED_HEADING_RE.match(line)
        or _is_all_caps_heading(line)
    ):
        return False
    return line[0].islower() or line[0] in '([“"'


def _find_content_start(lines: list[dict[str, Any]]) -> int:
    """Skip cover/TOC. Prefer INTRODUCTION - CHAPTER N, else first X.Y with body."""
    for i, item in enumerate(lines):
        if CHAPTER_INTRO_RE.match(item['text']):
            return i
        if TOC_LINE_RE.match(item['text']):
            continue
    for i, item in enumerate(lines):
        m = SECTION_RE.match(item['text'])
        if not m or m.group(3):
            continue
        # Need a following non-heading line soon after
        for nxt in lines[i + 1:i + 8]:
            if SECTION_RE.match(nxt['text']) or CHAPTER_HEAD_RE.match(nxt['text']):
                continue
            if len(nxt['text']) > 40:
                return i
    return 0


def _guess_course_title(lines: list[dict[str, Any]]) -> str:
    for item in lines[:40]:
        text = item['text']
        if TOC_LINE_RE.match(text) or CHAPTER_HEAD_RE.match(text):
            continue
        if 'COURSE MANUAL' in text.upper() or 'CERTIFICATION' in text.upper():
            return _norm_space(text)[:200]
        if _is_all_caps_heading(text) and len(text) > 12:
            return _norm_space(text).title()[:200]
    return 'Imported Course Manual'


def _clean_section_heading(text: str) -> str:
    """Drop '2.3 FOO CHAPTER 2.3 FOO' echoes from Google Docs running headers."""
    text = _norm_space(text)
    sec = SECTION_RE.match(text)
    if not sec or _is_false_section(text, sec.group(4)):
        return text
    key = f'{sec.group(1)}.{sec.group(2)}'
    if sec.group(3):
        key = f'{key}.{sec.group(3)}'
    rest = _norm_space(sec.group(4) or '')
    rest = re.sub(rf'\s+CHAPTER\s+{re.escape(key)}\b.*$', '', rest, flags=re.IGNORECASE).strip()
    return f'{key} {rest}'.strip()


def _is_title_echo_line(text: str, module: dict[str, Any] | None) -> bool:
    """True for cover-page fragments of the chapter name, not real lesson copy."""
    cleaned = _norm_space(text)
    echo = CHAPTER_SECTION_ECHO_RE.match(cleaned)
    if echo and module and str(echo.group(1).split('.')[0]) == str(module.get('number')):
        return True
    cleaned = re.sub(r'^CHAPTER\s+\d+\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip('—–- ')
    if not cleaned:
        return True
    if SECTION_RE.match(cleaned) or LEARNING_OBJ_RE.match(cleaned) or CHAPTER_INTRO_RE.match(text):
        return False
    words = [w.upper() for w in re.findall(r"[A-Za-z0-9']+", cleaned)]
    words = [w for w in words if w not in {'AND', 'THE', 'OF', 'A'}]
    if not words or len(cleaned) > 90:
        return False
    hay = ' '.join([
        (module or {}).get('name') or '',
        ' '.join(sorted(_TITLE_ECHO_WORDS)),
    ]).upper()
    return all(word in hay for word in words)


def _chapter_title(number: int, extra: str, fallback_names: dict[int, str]) -> str:
    extra = _norm_space(extra).lstrip('—–- ').strip()
    if extra and extra.upper() not in {'INTRODUCTION', 'QUIZ', 'SUMMARY', 'CONCLUSION', 'REFERENCES'}:
        pretty = extra.title() if extra.isupper() else extra
        return f'Chapter {number} — {pretty}'[:200]
    named = fallback_names.get(number)
    if named:
        return f'Chapter {number} — {named}'[:200]
    return f'Chapter {number}'


def _collect_toc_chapter_names(lines: list[dict[str, Any]]) -> dict[int, str]:
    names: dict[int, str] = {}
    for item in lines[:200]:
        m = CHAPTER_HEAD_RE.match(item['text'])
        if not m:
            continue
        num = int(m.group(1))
        extra = _norm_space(m.group(2) or '')
        if extra and extra.upper() not in {'INTRODUCTION', 'QUIZ', 'SUMMARY', 'CONCLUSION', 'REFERENCES'}:
            names.setdefault(num, extra.lstrip('—–- ').strip().title() if extra.isupper() else extra)
    return names


def _classify_line(text: str) -> tuple[str, Any]:
    if CHAPTER_INTRO_RE.match(text):
        m = CHAPTER_INTRO_RE.match(text)
        return 'chapter', {'number': int(m.group(1)), 'extra': _norm_space(m.group(2) or 'Introduction')}
    m = QUIZ_HEAD_RE.match(text)
    if m:
        return 'quiz', None
    m = SUMMARY_RE.match(text)
    if m:
        return 'summary', None
    if CONCLUSION_RE.match(text):
        return 'conclusion', None
    m = CHAPTER_HEAD_RE.match(text)
    if m:
        extra = _norm_space(m.group(2) or '')
        extra_u = extra.upper()
        if extra_u == 'SUMMARY':
            return 'summary', None
        if extra_u == 'QUIZ':
            return 'quiz', None
        if extra_u == 'CONCLUSION':
            return 'conclusion', None
        if extra_u == 'REFERENCES':
            return 'references', None
        return 'chapter', {'number': int(m.group(1)), 'extra': extra}
    m = SECTION_RE.match(text)
    if m:
        major, minor, nested, title = m.group(1), m.group(2), m.group(3), m.group(4)
        title = _norm_space(title)
        if _is_false_section(text, title):
            return 'text', text
        return 'section', {
            'major': int(major),
            'minor': int(minor),
            'nested': int(nested) if nested else None,
            'title': title or f'{major}.{minor}',
            'key': f'{major}.{minor}',
            'full_key': f'{major}.{minor}.{nested}' if nested else f'{major}.{minor}',
        }
    return 'text', text


def _new_lesson(title: str, kind: str, section_key: str | None, page: int, y0: float) -> dict[str, Any]:
    nest_depth = 0
    if section_key:
        nest_depth = str(section_key).count('.')
    return {
        'title': title[:200],
        'kind': kind,
        'section_key': section_key,
        'nest_depth': nest_depth,
        'is_parent_stub': False,
        'raw_lines': [],
        'raw_items': [],
        'page': page,
        'y0': y0,
        'end_page': page,
        'end_y0': y0,
        'outcomes': [],
        'quiz_questions': [],
        'blocks': [],
    }


def _module_has_section_key(module: dict[str, Any], key: str, current_lesson: dict[str, Any] | None) -> bool:
    if current_lesson and current_lesson.get('section_key') == key:
        return True
    return any(lesson.get('section_key') == key for lesson in (module.get('lessons') or []))


def _pop_parent_stub(module: dict[str, Any], key: str) -> dict[str, Any] | None:
    lessons = module.get('lessons') or []
    for index, lesson in enumerate(lessons):
        if lesson.get('section_key') == key and lesson.get('is_parent_stub'):
            return lessons.pop(index)
    return None


def _append_line(lesson: dict[str, Any], item: dict[str, Any]) -> None:
    lesson['raw_lines'].append(item['text'])
    lesson.setdefault('raw_items', []).append({
        'text': item['text'],
        'page': item.get('page', 0),
        'y0': item.get('y0', 0.0),
    })
    lesson['end_page'] = item['page']
    lesson['end_y0'] = item['y0']


def split_lines_into_modules(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    toc_names = _collect_toc_chapter_names(lines)
    start = _find_content_start(lines)
    body = lines[start:]

    modules: list[dict[str, Any]] = []
    current_module: dict[str, Any] | None = None
    current_lesson: dict[str, Any] | None = None
    last_xy_key: str | None = None

    def _extend_module_name(module: dict[str, Any], extra: str) -> None:
        extra = _norm_space(extra).lstrip('—–- ').strip()
        if not extra or extra.upper() in {'INTRODUCTION', 'QUIZ', 'SUMMARY', 'CONCLUSION', 'REFERENCES'}:
            return
        current_name = module.get('name') or ''
        extra_pretty = extra.title() if extra.isupper() else extra
        if current_name.rstrip().endswith((',', '&', '—', '–')):
            suffix = extra_pretty
            if current_name.rstrip()[-1] in {',', '&'}:
                module['name'] = f'{current_name} {suffix}'[:200]
            else:
                module['name'] = f'{current_name} {suffix}'[:200]
        elif extra_pretty.lower() not in current_name.lower() and len(extra_pretty) > len(current_name):
            module['name'] = _chapter_title(module['number'], extra, toc_names)

    def ensure_module(number: int, extra: str = '') -> dict[str, Any]:
        nonlocal current_module, current_lesson, last_xy_key
        if current_module and current_module.get('number') == number:
            _extend_module_name(current_module, extra)
            return current_module
        existing = next((module for module in modules if module.get('number') == number), None)
        if existing:
            if current_module and current_lesson:
                current_module['lessons'].append(current_lesson)
                current_lesson = None
                last_xy_key = None
            current_module = existing
            _extend_module_name(current_module, extra)
            return current_module
        if current_module and current_lesson:
            current_module['lessons'].append(current_lesson)
            current_lesson = None
            last_xy_key = None
        current_module = {
            'number': number,
            'name': _chapter_title(number, extra, toc_names),
            'order': number,
            'lessons': [],
        }
        modules.append(current_module)
        return current_module

    def flush_lesson() -> None:
        nonlocal current_lesson
        if current_module is not None and current_lesson is not None:
            if current_lesson['raw_lines'] or current_lesson['kind'] == 'quiz':
                current_module['lessons'].append(current_lesson)
        current_lesson = None

    for item in body:
        text = item['text']
        kind, payload = _classify_line(text)
        extra_u = ((payload or {}).get('extra') or '').upper() if isinstance(payload, dict) else ''
        if (
            kind == 'chapter'
            and extra_u in {'', 'INTRODUCTION'}
            and 0 < float(item.get('y0') or 0) < RUNNING_HEADER_Y0
            and int(item.get('page') or 0) >= 1
        ):
            continue

        if kind == 'chapter':
            number = payload['number']
            extra = payload.get('extra') or ''
            already = bool(current_module and current_module.get('number') == number)
            ensure_module(number, extra)
            extra_u = extra.upper()
            if not already and current_module.get('lessons'):
                last = current_module['lessons'][-1]
                if last.get('kind') == 'intro':
                    current_lesson = current_module['lessons'].pop()
                    already = True
            if already:
                if current_lesson and current_lesson['kind'] == 'intro':
                    if not _is_title_echo_line(text, current_module):
                        _append_line(current_lesson, item)
                last_xy_key = None
                continue
            flush_lesson()
            last_xy_key = None
            current_lesson = _new_lesson('Introduction', 'intro', None, item['page'], item['y0'])
            if extra and extra_u not in {'', 'INTRODUCTION'} and not _is_title_echo_line(text, current_module):
                _append_line(current_lesson, item)
            continue

        if current_module is None:
            # Infer chapter from first X.Y
            if kind == 'section':
                ensure_module(payload['major'])
            else:
                continue

        if kind == 'section':
            if payload['major'] != current_module['number']:
                ensure_module(payload['major'])
            if payload['nested']:
                # Parent/sub-lesson hierarchy: X.Y.Z is its own navigable lesson.
                # If the parent X.Y has not appeared yet, insert a stub so the
                # syllabus always has a place for the parent above its children.
                parent_key = payload['key']
                if not _module_has_section_key(current_module, parent_key, current_lesson):
                    flush_lesson()
                    stub = _new_lesson(parent_key, 'section', parent_key, item['page'], item['y0'])
                    stub['is_parent_stub'] = True
                    current_module.setdefault('lessons', []).append(stub)
                flush_lesson()
                last_xy_key = payload['full_key']
                section_title = _clean_section_heading(f"{payload['full_key']} {payload['title']}")
                item = dict(item)
                item['text'] = section_title
                current_lesson = _new_lesson(
                    section_title,
                    'subsection',
                    payload['full_key'],
                    item['page'],
                    item['y0'],
                )
                _append_line(current_lesson, item)
                continue
            # Parent X.Y — upgrade an earlier stub if sub-lessons arrived first.
            section_title = _clean_section_heading(f"{payload['key']} {payload['title']}")
            stub = _pop_parent_stub(current_module, payload['key'])
            flush_lesson()
            last_xy_key = payload['key']
            item = dict(item)
            item['text'] = section_title
            if stub:
                stub['title'] = section_title[:200]
                stub['is_parent_stub'] = False
                stub['kind'] = 'section'
                stub['nest_depth'] = 1
                current_lesson = stub
            else:
                current_lesson = _new_lesson(
                    section_title,
                    'section',
                    payload['key'],
                    item['page'],
                    item['y0'],
                )
            # Keep the heading as a raw line so it becomes an H2
            _append_line(current_lesson, item)
            continue

        if kind in {'summary', 'quiz', 'conclusion', 'references'}:
            if current_lesson and current_lesson['kind'] == kind:
                if kind != 'quiz':
                    _append_line(current_lesson, item)
                continue
            flush_lesson()
            last_xy_key = None
            titles = {
                'summary': f"Chapter {current_module['number']} Summary",
                'quiz': f"Chapter {current_module['number']} Quiz",
                'conclusion': 'Conclusion',
                'references': 'References',
            }
            current_lesson = _new_lesson(titles[kind], kind, None, item['page'], item['y0'])
            if kind != 'quiz':
                _append_line(current_lesson, item)
            continue

        if current_lesson and current_lesson['kind'] == 'intro' and _is_title_echo_line(text, current_module):
            _extend_module_name(current_module, text)
            continue
        if (
            current_lesson
            and current_lesson.get('section_key')
            and CHAPTER_SECTION_ECHO_RE.match(text)
        ):
            continue

        if current_lesson is None:
            current_lesson = _new_lesson('Introduction', 'intro', None, item['page'], item['y0'])
        _append_line(current_lesson, item)

    flush_lesson()
    return [m for m in modules if m.get('lessons')]


def parse_quiz_questions(raw_lines: list[str]) -> list[dict[str, str]]:
    """Parse CHAPTER N QUIZ text into LessonQuizQuestion-shaped dicts."""
    questions: list[dict[str, str]] = []
    current: dict[str, Any] | None = None
    question_parts: list[str] = []
    option_letter: str | None = None
    option_parts: list[str] = []

    def store_option() -> None:
        nonlocal option_letter, option_parts
        if current is not None and option_letter:
            key = f'option_{option_letter.lower()}'
            current[key] = _norm_space(' '.join(option_parts))
        option_letter = None
        option_parts = []

    def finish() -> None:
        nonlocal current, question_parts
        store_option()
        if not current:
            question_parts = []
            return
        current['question'] = _norm_space(' '.join(question_parts))
        if current['question'] and current.get('option_a') and current.get('option_b'):
            current.setdefault('option_c', '')
            current.setdefault('option_d', '')
            current.setdefault('correct_answer', 'A')
            questions.append(current)
        current = None
        question_parts = []

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        qmatch = QUESTION_RE.match(line)
        if qmatch:
            finish()
            current = {
                'question': '',
                'option_a': '',
                'option_b': '',
                'option_c': '',
                'option_d': '',
                'correct_answer': 'A',
            }
            question_parts = []
            continue
        if current is None:
            continue
        if SELECT_ONE_RE.match(line):
            continue
        omatch = OPTION_RE.match(line)
        if omatch:
            store_option()
            option_letter = omatch.group(1).upper()
            option_parts = [omatch.group(2)]
            continue
        nmatch = NUMBERED_OPTION_RE.match(line)
        if nmatch and (question_parts or option_letter or current.get('option_a')):
            store_option()
            option_letter = _NUMBERED_OPTION_LETTER[nmatch.group(1)]
            option_parts = [nmatch.group(2)]
            continue
        cmatch = CORRECT_RE.match(line)
        if cmatch:
            store_option()
            current['correct_answer'] = cmatch.group(1).upper()
            finish()
            continue
        if option_letter:
            option_parts.append(line)
        else:
            question_parts.append(line)
    finish()
    return questions


def _extract_outcomes(raw_lines: list[str]) -> list[str]:
    outcomes: list[str] = []
    capturing = False
    for line in raw_lines:
        if LEARNING_OBJ_RE.match(line):
            capturing = True
            continue
        if capturing:
            if not line.strip():
                if outcomes:
                    break
                continue
            if _is_all_caps_heading(line) or SECTION_RE.match(line) or CHAPTER_HEAD_RE.match(line):
                break
            m = NUMBERED_RE.match(line)
            if m:
                outcomes.append(_norm_space(m.group(2)))
            elif BULLET_RE.match(line):
                outcomes.append(_norm_space(BULLET_RE.match(line).group(1)))
            elif outcomes and not _is_all_caps_heading(line):
                outcomes[-1] = _norm_space(outcomes[-1] + ' ' + line)
    return outcomes[:12]


def lines_to_blocks(raw_lines: list[str], kind: str = 'section') -> list[dict[str, Any]]:
    """Turn verbatim lines into Editor.js-style section dicts (no paraphrase)."""
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_style = 'unordered'

    def flush_paragraph() -> None:
        nonlocal paragraph
        text = _norm_space(' '.join(paragraph))
        paragraph = []
        if not text:
            return
        from myApp.utils.lesson_blocks import expand_run_on_paragraph

        expanded = expand_run_on_paragraph(text)
        if expanded:
            for block in expanded:
                data = block.get('data') or {}
                if block.get('type') == 'paragraph':
                    blocks.append({'type': 'paragraph', 'text': data.get('text', '')})
                elif block.get('type') == 'header':
                    blocks.append({
                        'type': 'header',
                        'text': data.get('text', ''),
                        'level': data.get('level', 3),
                    })
                elif block.get('type') == 'list':
                    blocks.append({
                        'type': 'list',
                        'style': data.get('style', 'unordered'),
                        'items': data.get('items') or [],
                    })
            return
        blocks.append({'type': 'paragraph', 'text': text})

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            blocks.append({'type': 'list', 'style': list_style, 'items': list_items[:]})
        list_items = []

    def flush_all() -> None:
        flush_list()
        flush_paragraph()

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            flush_all()
            continue

        sec = SECTION_RE.match(line)
        if sec and _is_false_section(line, sec.group(4)):
            sec = None
        if sec and sec.group(3):
            flush_all()
            title = _norm_space(f"{sec.group(1)}.{sec.group(2)}.{sec.group(3)} {sec.group(4)}")
            blocks.append({'type': 'header', 'text': title, 'level': 3})
            continue
        if sec and not sec.group(3):
            flush_all()
            title = _norm_space(f"{sec.group(1)}.{sec.group(2)} {sec.group(4)}")
            blocks.append({'type': 'header', 'text': title, 'level': 2})
            continue

        if SUMMARY_RE.match(line) or CONCLUSION_RE.match(line) or CHAPTER_HEAD_RE.match(line):
            flush_all()
            pretty = _norm_space(line).title() if line.isupper() else _norm_space(line)
            blocks.append({'type': 'header', 'text': pretty, 'level': 2})
            continue

        if LABELED_HEADING_RE.match(line):
            flush_all()
            blocks.append({'type': 'header', 'text': _norm_space(line), 'level': 3})
            continue

        if LEARNING_OBJ_RE.match(line) or (_is_all_caps_heading(line) and not SECTION_RE.match(line)):
            if SKIP_HEADING_DUP_RE.match(line) and kind == 'intro' and not blocks:
                continue
            flush_all()
            pretty = _norm_space(line)
            if pretty.isupper() and pretty not in {'INTRODUCTION'}:
                pretty = pretty.title()
            blocks.append({'type': 'header', 'text': pretty, 'level': 3})
            continue

        bullet = BULLET_RE.match(line)
        numbered = NUMBERED_RE.match(line)
        if bullet or numbered:
            flush_paragraph()
            style = 'ordered' if numbered else 'unordered'
            if list_items and list_style != style:
                flush_list()
            list_style = style
            list_items.append(_norm_space((numbered or bullet).group(2 if numbered else 1)))
            continue

        if list_items:
            if _is_list_continuation(line):
                list_items[-1] = _norm_space(list_items[-1] + ' ' + line)
                continue
            flush_list()
        paragraph.append(line)

    flush_all()
    return blocks


def build_lesson_blocks(
    raw_items: list[dict[str, Any]],
    images: list[dict[str, Any]] | None,
    kind: str = 'section',
) -> list[dict[str, Any]]:
    """Turn lesson text and figures into blocks in PDF reading order."""
    items = list(raw_items or [])
    pictures = list(images or [])
    stream: list[tuple[Any, ...]] = [
        (int(item.get('page') or 0), float(item.get('y0') or 0), 0, 'text', item)
        for item in items
    ]
    stream.extend(
        (int(img.get('page') or 0), float(img.get('y0') or 0), 1, 'image', img)
        for img in pictures
    )
    stream.sort(key=lambda row: (row[0], row[1], row[2]))

    blocks: list[dict[str, Any]] = []
    text_buf: list[str] = []

    def flush_text() -> None:
        if not text_buf:
            return
        blocks.extend(lines_to_blocks(text_buf, kind=kind))
        text_buf.clear()

    for _page, _y0, _prio, kind_row, payload in stream:
        if kind_row == 'image':
            flush_text()
            blocks.append({
                'type': 'image',
                'bytes': payload.get('bytes') or b'',
                'content_type': payload.get('content_type') or 'image/png',
                'caption': payload.get('caption') or '',
                'url': payload.get('url') or '',
                'page': payload.get('page', 0),
                'y0': payload.get('y0', 0),
            })
            continue
        text_buf.append(str(payload.get('text') or ''))
    flush_text()
    return blocks


def _first_paragraph_text(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        if block.get('type') == 'paragraph' and block.get('text'):
            return str(block['text']).strip()
    return ''


def _image_belongs_to_lesson(image: dict[str, Any], lesson: dict[str, Any], next_lesson: dict[str, Any] | None) -> bool:
    """A lesson owns figures from its heading until the next heading, including image-only pages."""
    page = image['page']
    y0 = image.get('y0') or 0.0
    start_page = lesson.get('page', 0)
    start_y0 = lesson.get('y0') or 0.0
    if page < start_page or (page == start_page and y0 + 1 < start_y0):
        return False
    if next_lesson is not None:
        nxt_page = next_lesson.get('page', 10**9)
        nxt_y0 = next_lesson.get('y0') or 0.0
        if page > nxt_page or (page == nxt_page and y0 >= nxt_y0):
            return False
    return True


def attach_images(modules: list[dict[str, Any]], images: list[dict[str, Any]]) -> None:
    lessons: list[dict[str, Any]] = []
    for module in modules:
        lessons.extend(module.get('lessons') or [])
    used: set[int] = set()
    for i, lesson in enumerate(lessons):
        nxt = lessons[i + 1] if i + 1 < len(lessons) else None
        for idx, image in enumerate(images):
            if idx in used:
                continue
            if _image_belongs_to_lesson(image, lesson, nxt):
                lesson.setdefault('images', []).append(image)
                used.add(idx)
    # Leftover images go on the last lesson of the last module
    leftovers = [img for i, img in enumerate(images) if i not in used]
    if leftovers and lessons:
        lessons[-1].setdefault('images', []).extend(leftovers)


def finalize_lessons(modules: list[dict[str, Any]]) -> None:
    for module in modules:
        cleaned = []
        for lesson in module.get('lessons') or []:
            raw = lesson.get('raw_lines') or []
            if lesson['kind'] == 'quiz':
                lesson['quiz_questions'] = parse_quiz_questions(raw)
                lesson['blocks'] = [{
                    'type': 'paragraph',
                    'text': 'Complete the chapter quiz to check your understanding. Exact questions from the source manual.',
                }]
            else:
                raw_items = lesson.get('raw_items') or [
                    {'text': line, 'page': lesson.get('page', 0), 'y0': float(i)}
                    for i, line in enumerate(raw)
                ]
                lesson['blocks'] = build_lesson_blocks(
                    raw_items,
                    lesson.get('images') or [],
                    kind=lesson['kind'],
                )
                lesson['images'] = []
                lesson['outcomes'] = _extract_outcomes(raw)
                if lesson['kind'] == 'intro' and not lesson['outcomes']:
                    # Outcomes sometimes sit in the intro under "Learning Objectives"
                    pass
            first = _first_paragraph_text(lesson['blocks'])
            lesson['short_summary'] = first[:400]
            lesson['full_description'] = first[:2000]
            if lesson['kind'] == 'intro' and not first and not lesson.get('outcomes'):
                has_body = any(
                    block.get('type') in {'paragraph', 'list', 'image'}
                    for block in (lesson.get('blocks') or [])
                )
                if not has_body:
                    continue
            if lesson['kind'] == 'quiz' or lesson.get('blocks') or lesson.get('quiz_questions') or lesson.get('images'):
                cleaned.append(lesson)
        module['lessons'] = cleaned


def parse_course_text(text: str, images: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Parse already-extracted plain text (newline separated) into course structure."""
    lines = [
        {'text': ln.strip(), 'page': 0, 'y0': float(i), 'size': 11.0}
        for i, ln in enumerate((text or '').splitlines())
        if ln.strip()
    ]
    return parse_extracted({'lines': _normalize_extracted_lines(lines), 'images': images or []})


def _lesson_count(modules: list[dict[str, Any]]) -> int:
    return sum(len(m.get('lessons') or []) for m in modules)


def parse_extracted(extracted: dict[str, Any]) -> dict[str, Any]:
    images = extracted.get('images') or []
    candidates = []
    for key in ('lines', 'text_lines'):
        raw = extracted.get(key) or []
        if raw:
            candidates.append(raw)
    if not candidates:
        candidates = [[]]

    best_modules: list[dict[str, Any]] = []
    best_lines: list[dict[str, Any]] = []
    for lines in candidates:
        modules = split_lines_into_modules(lines)
        attach_images(modules, images)
        finalize_lessons(modules)
        if _lesson_count(modules) > _lesson_count(best_modules):
            best_modules = [m for m in modules if m.get('lessons')]
            best_lines = lines

    if _lesson_count(best_modules) == 0:
        all_lines = extracted.get('text_lines') or extracted.get('lines') or []
        raw_texts = [ln['text'] for ln in all_lines]
        blocks = lines_to_blocks(raw_texts, kind='intro')
        if blocks:
            first = _first_paragraph_text(blocks)
            best_modules = [{
                'number': 1,
                'name': 'Imported Manual',
                'order': 1,
                'lessons': [{
                    'title': 'Imported content',
                    'kind': 'intro',
                    'section_key': None,
                    'blocks': blocks,
                    'outcomes': _extract_outcomes(raw_texts),
                    'quiz_questions': [],
                    'images': images,
                    'short_summary': first[:400],
                    'full_description': first[:2000],
                    'page': 0,
                    'y0': 0,
                    'end_page': 0,
                    'end_y0': 0,
                    'raw_lines': raw_texts,
                }],
            }]
            best_lines = all_lines

    title = _guess_course_title(best_lines)
    first_para = ''
    from myApp.utils.lesson_hierarchy import clean_lesson_nav_title, section_sort_key

    for module in best_modules:
        lessons = module.get('lessons') or []
        for lesson in lessons:
            lesson['title'] = clean_lesson_nav_title(lesson.get('title') or '') or lesson.get('title') or 'Untitled'
        # Preserve original relative order among equal keys via enumerate fallback
        lessons = [
            lesson for _, lesson in sorted(
                enumerate(lessons),
                key=lambda pair: section_sort_key(
                    pair[1].get('title') or '',
                    fallback_order=pair[0],
                    fallback_id=0,
                    kind=pair[1].get('kind'),
                ),
            )
        ]
        module['lessons'] = lessons
        for lesson in lessons:
            first_para = lesson.get('full_description') or ''
            if first_para:
                break
        if first_para:
            break
    return {
        'course_title': title,
        'short_description': (first_para or title)[:1000],
        'description': first_para or 'Imported from uploaded course manual.',
        'modules': best_modules,
    }


def parse_pdf_bytes(pdf_bytes: bytes) -> dict[str, Any]:
    extracted = extract_pdf_pages(pdf_bytes)
    parsed = parse_extracted(extracted)
    if not parsed['modules']:
        raise ValueError(
            'Could not extract readable text from this PDF. '
            'If it is a scanned document, export it from Google Docs / Word as a text PDF and try again.'
        )
    return parsed


def _unique_lesson_slug(course, title: str, generate_slug) -> str:
    base = generate_slug(title) or 'lesson'
    if len(base) > 180:
        base = base[:180].rstrip('-') or 'lesson'
    slug = base
    counter = 1
    while course.lessons.filter(slug=slug).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug


def _truncate(value: str, limit: int) -> str:
    value = value or ''
    return value if len(value) <= limit else value[:limit]


def persist_imported_course(course, parsed: dict[str, Any], *, generate_slug, create_editorjs_content) -> dict[str, int]:
    """Create Module / Lesson / LessonQuiz rows from a parsed PDF structure."""
    from myApp.models import Lesson, LessonQuiz, LessonQuizQuestion, Module
    from myApp.utils import iceberg

    tenant = course.tenant
    modules_created = 0
    lessons_created = 0
    questions_created = 0
    images_uploaded = 0
    lesson_ids: list[int] = []

    if not course.name or course.name in {'Imported Course Manual', 'Imported PDF Course'}:
        extracted_title = (parsed.get('course_title') or '').strip()
        if extracted_title:
            course.name = extracted_title[:200]
    if parsed.get('short_description') and (
        not course.short_description or course.short_description.startswith('Imported from')
    ):
        course.short_description = parsed['short_description'][:1000]
    if parsed.get('description') and (
        not course.description or course.description.startswith('Imported from')
    ):
        course.description = parsed['description']
    course.save(update_fields=['name', 'short_description', 'description'])

    for module_data in parsed.get('modules') or []:
        module = Module.objects.create(
            tenant=tenant,
            course=course,
            name=(module_data.get('name') or f"Chapter {module_data.get('order', modules_created + 1)}")[:200],
            description='',
            order=module_data.get('order') or (modules_created + 1),
        )
        modules_created += 1
        for order, lesson_data in enumerate(module_data.get('lessons') or [], start=1):
            title = (lesson_data.get('title') or 'Untitled Lesson')[:200]
            sections: list[dict[str, Any]] = []

            def _upload_figure(image: dict[str, Any]) -> str:
                raw = image.get('bytes') or b''
                if not raw or not iceberg.is_configured():
                    return image.get('url') or ''
                ext = 'jpg' if image.get('content_type') == 'image/jpeg' else 'png'
                key = (
                    f'course_imports/tenant_{tenant.id if tenant else "global"}/'
                    f'course_{course.id}/{uuid.uuid4().hex}.{ext}'
                )
                try:
                    return iceberg.upload_bytes(raw, key, image.get('content_type') or 'image/png')
                except Exception:
                    logger.exception('Figure upload failed for course %s', course.id)
                    return ''

            for block in lesson_data.get('blocks') or []:
                if block.get('type') == 'image':
                    url = _upload_figure(block)
                    if url:
                        sections.append({
                            'type': 'image',
                            'url': url,
                            'caption': block.get('caption') or '',
                            'page': block.get('page'),
                            'y0': block.get('y0'),
                        })
                        images_uploaded += 1
                    continue
                sections.append(block)
            for image in lesson_data.get('images') or []:
                url = _upload_figure(image)
                if url:
                    sections.append({
                        'type': 'image',
                        'url': url,
                        'caption': image.get('caption') or '',
                        'page': image.get('page'),
                        'y0': image.get('y0'),
                    })
                    images_uploaded += 1

            content = create_editorjs_content(sections) if sections else {}
            first = _first_paragraph_text(lesson_data.get('blocks') or [])
            outcomes = lesson_data.get('outcomes') or []
            section_key = (lesson_data.get('section_key') or '').strip()
            nest_depth = lesson_data.get('nest_depth')
            if nest_depth is None:
                nest_depth = section_key.count('.') if section_key else 0
            lesson = Lesson.objects.create(
                tenant=tenant,
                course=course,
                module=module,
                title=title,
                slug=_unique_lesson_slug(course, title, generate_slug),
                description=first or title,
                order=order,
                working_title=title,
                ai_clean_title=title,
                ai_short_summary=(lesson_data.get('short_summary') or first)[:400],
                ai_full_description=lesson_data.get('full_description') or first,
                ai_outcomes=outcomes,
                ai_coach_actions=[],
                content=content,
                ai_generation_status='generated',
                generation_settings={
                    'source': 'pdf_import',
                    'faithful': True,
                    'section_key': section_key,
                    'nest_depth': int(nest_depth or 0),
                    'kind': lesson_data.get('kind') or '',
                },
            )
            lessons_created += 1

            quiz_questions = lesson_data.get('quiz_questions') or []
            if quiz_questions:
                quiz, _ = LessonQuiz.objects.get_or_create(
                    lesson=lesson,
                    defaults={
                        'tenant': tenant,
                        'title': title,
                        'passing_score': 70,
                        'is_required': False,
                    },
                )
                for q_idx, q in enumerate(quiz_questions, start=1):
                    answer = (q.get('correct_answer') or 'A').strip().upper()
                    if answer not in {'A', 'B', 'C', 'D'}:
                        answer = 'A'
                    LessonQuizQuestion.objects.create(
                        quiz=quiz,
                        tenant=tenant,
                        text=q.get('question') or '',
                        option_a=_truncate(q.get('option_a') or '', 300),
                        option_b=_truncate(q.get('option_b') or '', 300),
                        option_c=_truncate(q.get('option_c') or '', 300),
                        option_d=_truncate(q.get('option_d') or '', 300),
                        correct_option=answer,
                        order=q_idx,
                    )
                    questions_created += 1

            lesson_ids.append(lesson.id)

    if lessons_created == 0:
        raise ValueError(
            'The PDF was read but no lessons could be created. '
            'Export it as a text PDF from Google Docs or Word and try again.'
        )

    return {
        'modules': modules_created,
        'lessons': lessons_created,
        'questions': questions_created,
        'images': images_uploaded,
        'lesson_ids': lesson_ids,
    }


def save_import_pdf(course_id: int, uploaded_file) -> str:
    """Write the uploaded PDF to a temp path the background worker can read."""
    from django.conf import settings

    dest_dir = os.path.join(str(settings.MEDIA_ROOT), 'pdf_imports')
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f'course_{course_id}_{uuid.uuid4().hex}.pdf')
    uploaded_file.seek(0)
    with open(dest_path, 'wb') as fh:
        for chunk in uploaded_file.chunks():
            fh.write(chunk)
    return dest_path
