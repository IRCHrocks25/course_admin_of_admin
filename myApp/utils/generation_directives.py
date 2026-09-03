"""Parse explicit generation skip cues from lesson title/source text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_QUIZ_SKIP_PATTERNS = (
    r'\bdo\s+not\s+generate\s+(a\s+|an\s+)?quiz\b',
    r'\bdon\'?t\s+generate\s+(a\s+|an\s+)?quiz\b',
    r'\bno\s+quiz\b',
    r'\bskip\s+(the\s+)?quiz\b',
    r'\bwithout\s+(a\s+|an\s+)?quiz\b',
    r'\bquiz\s*:\s*off\b',
)

_EXERCISE_SKIP_PATTERNS = (
    r'\bdo\s+not\s+generate\s+(a\s+|an\s+)?exercise\b',
    r'\bdon\'?t\s+generate\s+(a\s+|an\s+)?exercise\b',
    r'\bno\s+exercise\b',
    r'\bskip\s+(the\s+)?exercise\b',
    r'\bwithout\s+(a\s+|an\s+)?exercise\b',
    r'\bno\s+exercises\b',
)


def _matches_any(text: str, patterns) -> bool:
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


@dataclass(frozen=True)
class GenerationDirectives:
    skip_quiz: bool = False
    skip_exercise: bool = False


def parse_generation_directives(title: str = '', source: str = '') -> GenerationDirectives:
    """Detect explicit skip cues in title + source (case-insensitive)."""
    blob = f'{title or ""}\n{source or ""}'
    return GenerationDirectives(
        skip_quiz=_matches_any(blob, _QUIZ_SKIP_PATTERNS),
        skip_exercise=_matches_any(blob, _EXERCISE_SKIP_PATTERNS),
    )


def effective_generate_quiz(
    title: str = '',
    source: str = '',
    explicit: Optional[bool] = None,
) -> bool:
    """Return whether to generate a quiz.

    If ``explicit`` is set (UI toggle / seed flag), it wins.
    Otherwise fall back to directive parsing (default True unless skip cue found).
    """
    if explicit is not None:
        return bool(explicit)
    return not parse_generation_directives(title, source).skip_quiz


def coerce_optional_bool(value) -> Optional[bool]:
    """Parse JSON/seed bool-ish values; None if absent/unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
    return None
