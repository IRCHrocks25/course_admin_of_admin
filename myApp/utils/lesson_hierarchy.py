"""Section-number hierarchy helpers for syllabus navigation and ordering."""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

SECTION_PREFIX_RE = re.compile(
    r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?\b(?:\s+|$)(.*)$',
    re.IGNORECASE,
)
CHAPTER_ECHO_RE = re.compile(
    r'^(\d+(?:\.\d+){1,2})\s+(.+?)\s+CHAPTER\s+\1\b.*$',
    re.IGNORECASE,
)


def parse_section_parts(title: str) -> tuple[int, ...] | None:
    """Return (major, minor[, nested]) from a lesson title, or None."""
    text = (title or '').strip()
    match = SECTION_PREFIX_RE.match(text)
    if not match:
        return None
    major = int(match.group(1))
    minor = match.group(2)
    nested = match.group(3)
    if minor is None:
        return None
    parts = [major, int(minor)]
    if nested is not None:
        parts.append(int(nested))
    return tuple(parts)


def lesson_nest_depth(title: str) -> int:
    """0 = intro/summary/quiz, 1 = X.Y parent section, 2 = X.Y.Z sub-lesson."""
    parts = parse_section_parts(title)
    if not parts:
        return 0
    return 2 if len(parts) >= 3 else 1


def _lesson_bucket(title: str, kind: str | None = None) -> int:
    """0 = intro, 1 = body/sections, 2 = summary/quiz/conclusion/references."""
    kind_l = (kind or '').strip().lower()
    if kind_l == 'intro':
        return 0
    if kind_l in {'summary', 'quiz', 'conclusion', 'references'}:
        return 2
    text = (title or '').strip()
    lower = text.lower()
    if lower == 'introduction' or lower.startswith('introduction '):
        return 0
    if (
        lower.endswith(' summary')
        or lower.endswith(' quiz')
        or lower in {'summary', 'conclusion', 'references'}
        or re.match(r'^chapter\s+\d+\s+(summary|quiz)\b', lower)
    ):
        return 2
    return 1


def clean_lesson_nav_title(title: str) -> str:
    """Strip duplicated 'CHAPTER X.Y.Z …' running-header echoes from titles."""
    text = re.sub(r'\s+', ' ', (title or '').strip())
    if not text:
        return ''
    echo = CHAPTER_ECHO_RE.match(text)
    if echo:
        return f'{echo.group(1)} {echo.group(2).strip()}'.strip()
    parts = parse_section_parts(text)
    if parts:
        key = '.'.join(str(p) for p in parts)
        matched = SECTION_PREFIX_RE.match(text)
        rest = matched.group(4) if matched else ''
        rest = re.sub(rf'\s+CHAPTER\s+{re.escape(key)}\b.*$', '', rest or '', flags=re.IGNORECASE).strip()
        return f'{key} {rest}'.strip() if rest else key
    return text


def section_sort_key(
    title: str,
    fallback_order: int = 0,
    fallback_id: int = 0,
    kind: str | None = None,
) -> tuple:
    """Intro first, summary/quiz last; numbered sections as 2.3 → 2.3.1 → 2.4."""
    bucket = _lesson_bucket(title, kind=kind)
    parts = parse_section_parts(title)
    if parts:
        padded = (parts + (0, 0, 0))[:3]
        return (bucket, padded[0], padded[1], padded[2], fallback_order, fallback_id)
    return (bucket, 0, 0, 0, fallback_order, fallback_id)


def sort_lessons_by_section(lessons: Sequence[Any]) -> list[Any]:
    """Stable section-aware sort for Lesson-like objects with .title/.order/.id."""
    return sorted(
        lessons,
        key=lambda lesson: section_sort_key(
            getattr(lesson, 'title', '') or '',
            fallback_order=getattr(lesson, 'order', 0) or 0,
            fallback_id=getattr(lesson, 'id', 0) or 0,
            kind=getattr(lesson, 'kind', None),
        ),
    )


def annotate_syllabus_lessons(lessons: Iterable[Any], title_map: dict | None = None) -> list[dict]:
    """Build sidebar rows: lesson, nest_depth, display_title."""
    title_map = title_map or {}
    rows = []
    for lesson in lessons:
        raw = title_map.get(lesson.id) or lesson.title or ''
        display = clean_lesson_nav_title(raw)
        settings = getattr(lesson, 'generation_settings', None)
        nest_depth = None
        if isinstance(settings, dict) and settings.get('nest_depth') is not None:
            try:
                nest_depth = int(settings.get('nest_depth'))
            except (TypeError, ValueError):
                nest_depth = None
        if nest_depth is None:
            nest_depth = lesson_nest_depth(display or lesson.title or '')
        rows.append({
            'lesson': lesson,
            'nest_depth': nest_depth,
            'display_title': display or lesson.title,
        })
    return rows
