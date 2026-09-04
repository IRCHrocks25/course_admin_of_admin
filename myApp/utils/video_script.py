"""Generate a ~5-minute instructional video script from a finished lesson.

Used by the course-generation worker after lesson notes are saved.

The generated structured JSON is stored on ``Lesson.video_script``.
``render_script_html`` / ``script_to_html`` render that JSON into
production-friendly HTML for conversion/upload to Google Docs.

Core principle:
The lesson is the source of truth. The model should transform the lesson
into a visual teaching experience, not merely summarize it.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from django.utils.html import escape, strip_tags

logger = logging.getLogger(__name__)

SOURCE_MAX_CHARS = 24000
MAX_SECTIONS = 12
MIN_SECTIONS = 4
MAX_SHOT_LIST = 7
MAX_OUTPUT_TOKENS = 5000
TARGET_WORD_MIN = 650
TARGET_WORD_MAX = 820
DEFAULT_DURATION = 'about 5 minutes'
DEFAULT_FORMAT = 'Educational / Explainer'
DEFAULT_TONE = 'Clear, practical, instructional'


# ---------------------------------------------------------------------------
# Lesson-content flattening
# ---------------------------------------------------------------------------

def flatten_lesson_source(lesson) -> str:
    """Plain-text source for the script: Editor.js notes, else rough_notes."""
    flattened = flatten_content_to_text(getattr(lesson, 'content', None))
    if flattened:
        return flattened
    return (getattr(lesson, 'rough_notes', None) or '').strip()


def script_display_title(lesson) -> str:
    """Title used in the script prompt and Doc name.

    Prefer the AI clean title. The working/seed title is often a leftover
    label (e.g. coffee) that does not match the finished notes.
    """
    return (
        (getattr(lesson, 'ai_clean_title', None) or '').strip()
        or (getattr(lesson, 'title', None) or '').strip()
        or 'Untitled Lesson'
    )


def flatten_content_to_text(content) -> str:
    """Turn Editor.js JSON or loose block content into readable plain text."""
    if not content:
        return ''

    if isinstance(content, str):
        return _clean_text(content)

    blocks = []
    if isinstance(content, dict):
        raw_blocks = content.get('blocks')
        if isinstance(raw_blocks, list):
            blocks = raw_blocks
        elif isinstance(content.get('content'), list):
            blocks = content['content']
    elif isinstance(content, list):
        blocks = content

    parts = [_block_to_text(block) for block in blocks]
    flattened = '\n\n'.join(part for part in parts if part)
    flattened = re.sub(r'[ \t]+', ' ', flattened)
    flattened = re.sub(r'\n[ \t]+', '\n', flattened)
    flattened = re.sub(r'\n{3,}', '\n\n', flattened)
    return flattened.strip()


def _block_to_text(block) -> str:
    if isinstance(block, str):
        return _clean_text(block)
    if not isinstance(block, dict):
        return ''

    btype = str(block.get('type') or '').strip().lower()
    raw_data = block.get('data')
    data = raw_data if isinstance(raw_data, dict) else block

    if btype in ('paragraph', 'header') or (not btype and data.get('text')):
        return _clean_text(data.get('text'))

    if btype == 'quote':
        text = _clean_text(data.get('text'))
        caption = _clean_text(data.get('caption'))
        if text and caption:
            return f'{text} — {caption}'
        return text

    if btype == 'list':
        items = []
        for item in data.get('items') or []:
            text = _list_item_text(item)
            if text:
                items.append(f'- {text}')
        return '\n'.join(items)

    if btype == 'table':
        rows = []
        for row in data.get('content') or []:
            if not isinstance(row, (list, tuple)):
                continue
            cells = [_clean_text(cell) for cell in row]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(' | '.join(cells))
        return '\n'.join(rows)

    if btype == 'checklist':
        items = []
        for item in data.get('items') or []:
            if isinstance(item, dict):
                label = _clean_text(item.get('text') or item.get('content') or item.get('label'))
            else:
                label = _list_item_text(item)
            if label:
                checked = bool(item.get('checked')) if isinstance(item, dict) else False
                marker = '[x]' if checked else '[ ]'
                items.append(f'- {marker} {label}')
        return '\n'.join(items)

    fallback = data.get('text')
    return _clean_text(fallback) if fallback else ''


def _list_item_text(item) -> str:
    if isinstance(item, str):
        return _clean_text(item)
    if isinstance(item, dict):
        return _clean_text(item.get('content') or item.get('text') or item.get('label') or '')
    return _clean_text(item)


def _clean_text(value: Any) -> str:
    if value is None:
        return ''
    text = strip_tags(str(value)).replace('\xa0', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Source preparation
# ---------------------------------------------------------------------------

def truncate_source(text: str, max_chars: int = SOURCE_MAX_CHARS) -> str:
    """Keep beginning and ending when the source is longer than max_chars.

    Finished lessons often put scenarios, takeaways, and checklists near the
    bottom, so a naive head-only cut drops the most useful closing material.
    """
    source = (text or '').strip()
    if not source or len(source) <= max_chars:
        return source
    head_size = int(max_chars * 0.65)
    tail_size = max_chars - head_size
    return (
        f'{source[:head_size].rstrip()}\n\n'
        '[...middle portion shortened because lesson exceeded input limit...]\n\n'
        f'{source[-tail_size:].lstrip()}'
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_video_script_prompt(source_text: str, lesson_title: str, course_name: str = '') -> str:
    title = lesson_title or 'Untitled Lesson'
    course = course_name or 'Untitled Course'
    return f"""
You are an expert instructional video scriptwriter creating a
production-ready training video from a finished course lesson.

Your job is NOT to summarize the lesson.

Your job is to transform the finished lesson into a clear, visual,
approximately five-minute teaching experience for an instructor or
professional voiceover.

# SOURCE OF TRUTH

The finished lesson notes below ARE the subject of the video.
The course name and lesson title are labels only. They must not
choose the topic.

If a label names a different subject than the notes (for example a
coffee or smoothie title on personal-development notes), IGNORE the
label. Teach the notes. Do not write a video about the label and then
sprinkle in a few source keywords.

Do not invent ingredients, steps, temperatures, equipment, standards,
or any other facts that are not in the notes.

Course label (ignore if it conflicts with the notes): {course}
Lesson label (ignore if it conflicts with the notes): {title}

--- SOURCE START ---

{source_text}

--- SOURCE END ---

# PRIMARY OBJECTIVE

Transform the lesson into a teaching sequence that helps the learner
understand:

1. Why the subject matters.
2. What principle, standard, or skill they need to understand.
3. Who or what is involved.
4. What exact standards or specifications they need to remember.
5. What correct execution looks like.
6. What happens when the standard is not met.
7. What they should do immediately after learning it.

The result should feel like an experienced instructor teaching the lesson,
not like someone reading lesson notes aloud.

# SOURCE-OF-TRUTH RULE

The video is about the notes, not the labels.

Preserve exact source information whenever it appears.

This includes:

- numbers
- percentages
- measurements
- temperatures
- weights
- dimensions
- durations
- timing windows
- quantities
- ranges
- standards
- SOP names and codes
- terminology
- role names
- equipment
- ingredients
- procedures
- sequences
- safety requirements
- required checklist items
- distinctions between mandatory and optional items

Never invent a missing figure.

Never substitute a general industry recommendation for a value provided
in the source.

Never turn an optional item into a requirement.

Never soften a mandatory item into a recommendation.

Never collapse two distinct stages or specifications into one generic rule.

# CONTENT PRIORITY

When deciding what deserves video time, prioritize information in this order:

1. Learning objective
2. Central principle or reason the lesson exists
3. Named standards, policies, frameworks, or SOP requirements
4. Roles and accountability
5. Safety-critical information
6. Exact numbers, timings, measurements, temperatures, and specifications
7. Required equipment or setup
8. Required workflow, process, or checklist
9. Cause-and-effect explanations
10. Practical scenarios, cases, mistakes, or troubleshooting examples
11. Key takeaways
12. Immediate action checklist

Do not spend valuable video time on minor descriptive material when more
important operational or instructional information is available.

# TARGET LENGTH

Target approximately 700 to 780 spoken words.

Target runtime: approximately five minutes.

Assume natural professional instructional delivery of approximately
140 to 155 spoken words per minute.

Do not pad the script merely to reach a target word count.

# TEACHING ARCHITECTURE

Use this progression:

WHY -> STANDARD -> EXECUTION -> APPLICATION -> ACTION

The sequence should feel cumulative.

Each new beat should build naturally on the previous beat.

# HOOK

Use approximately the first 15 to 20 seconds.

Open with the central operational problem, consequence, contrast,
observation, or real-world situation that makes the lesson relevant.

Avoid generic openings such as:

"Welcome to this lesson."
"In this video..."
"Today we are going to learn..."

unless the source or context genuinely requires one.

Prefer showing the learner the problem immediately.

The hook should then make clear what the learner will understand,
recognize, or be able to do.

The hook must include its own visual direction (``b_roll``), exactly like a
section, because the hook is a real on-camera segment, not a title card.

# OBJECTIVES / ROADMAP BEAT

Immediately after the hook, include ONE short beat (roughly 10 to 15
seconds) that states what the learner will be able to do by the end,
drawn from the lesson's stated learning objective. Keep it to a single
compact sentence of narration. This is the first item in ``sections``.

# CORE SECTIONS

Create approximately 6 to 12 instructional beats when the source supports it
(the objectives/roadmap beat counts as the first one).

Do not force everything into only three or four oversized sections.

Each section should teach ONE main idea.

Possible section types include:

- learning objectives / roadmap
- why the standard exists
- roles and accountability
- required setup
- equipment
- specifications
- process
- timing
- safety
- checklist
- decision rule
- correct versus incorrect execution
- scenario
- corrective action

Use fewer sections if the lesson is genuinely simple.

Use more sections (up to 12) when the lesson contains several important
operational concepts.

Never create sections solely to reach a number.

# PRACTICAL APPLICATION

If the source contains practical scenarios, cases, mistakes, troubleshooting
examples, or decision points, include the strongest one or two when they
improve understanding.

Present them as teaching scenarios, not quiz questions.

Good structure:

"Scenario: [situation]."

Then explain:

- what is wrong or at risk
- what the standard requires
- what action should be taken
- why that action matters

Do not invent scenarios when the source does not provide enough information
to support them.

# CAUSE AND EFFECT

Whenever the source explains WHY a standard exists, preserve that reasoning.

Prefer:

"A thin pan loses heat when the steak goes in, so instead of searing,
you begin steaming."

over:

"Use the correct pan."

Learners should understand both the standard and the consequence behind it.

# NARRATION STYLE

Write for speech.

The instructor should sound:

- experienced
- direct
- calm
- practical
- confident
- precise
- conversational but professional
- authoritative without sounding academic

Use second person where natural.

Prefer active language.

Prefer short and medium spoken sentences.

Avoid textbook-style paragraphs.

Avoid unnecessary adjectives.

Avoid motivational filler.

Avoid repeating the same fact in different words unless repetition is
instructionally useful.

# VISUAL THINKING

This is a VIDEO script, not just narration.

EVERY beat -- including the hook and the close -- must include a specific
visual concept (``b_roll``) that directly reinforces the narration.

Good visuals include:

- equipment being used
- close-ups of ingredients or components
- measurements being shown
- thermometer readings
- timers or clocks
- role diagrams
- process diagrams
- side-by-side comparisons
- before-and-after states
- checklist items ticking on
- correct versus incorrect technique
- realistic scenario recreations
- safety equipment in context
- workflow sequences

Avoid vague production notes such as:

"Show relevant B-roll."
"Show kitchen footage."
"Instructor talking."

Describe what the learner should actually see.

# ON-SCREEN TEXT

Use on-screen text as memory reinforcement.

Prioritize:

- numbers
- temperatures
- timings
- measurements
- concise standards
- role relationships
- checklist names
- process sequences
- critical warnings
- decision rules

Do NOT put the full narration on screen.

Keep overlays concise.

Prefer approximately 3 to 10 words when possible.

Examples:

"163°C FIRST FRY · 190–200°C SECOND FRY"

"COOK EXECUTES · PASS VERIFIES · SOUS CHEF AUDITS"

"A GATE ITEM IS NOT A PREFERENCE"

# TIMESTAMPS

Create realistic timestamps progressing continuously from approximately
0:00 through 5:00.

Do not create equal-sized sections merely for symmetry.

Give more time to ideas that need explanation.

Give less time to simple transitions or specifications.

The amount of narration inside each segment must plausibly fit the
allocated time.

Do not place 70 spoken words inside a 10-second segment.

Timestamps must be continuous: each segment's start equals the previous
segment's end, with no gaps and no overlaps, ending at approximately 5:00.

# CLOSE

Use approximately the final 20 to 30 seconds.

Do not merely summarize what was taught.

Convert the lesson into action.

When the source contains an action checklist, pre-service checklist,
implementation sequence, next steps, or immediate application instructions,
use them to construct the close.

Prefer language such as:

"Before your next service..."
"Before you begin..."
"Run these checks..."
"Confirm..."
"Make sure..."

End on the operational result the learner is trying to achieve.

The close must include its own visual direction (``b_roll``).

DO NOT invent a next lesson.

Only mention a next lesson if the source explicitly identifies it.

Otherwise finish with an application-focused final statement.

# PRODUCTION NOTES

Create 4 to 7 concise shot-list / production notes.

Begin each note with a short label followed by a colon, so the shot list
reads as labelled guidance rather than a flat list. Use labels such as:

"Pacing:", "Music:", "Voice direction:", "Text overlays:", "Safety:",
"Continuity:", "Demonstration:".

Make them specific to this lesson.

Where relevant, cover:

- pacing
- demonstrations
- important text overlays
- visual continuity
- safety visibility
- process diagrams
- key numbers that should stay on screen longer
- recurring visual motifs
- correct-versus-incorrect comparisons

Do not provide generic cinematography advice.

# EXCLUSIONS

Do not include:

- quiz questions
- multiple-choice questions
- unsupported facts
- invented examples
- invented next-lesson information
- citations
- Markdown
- explanatory commentary outside the requested JSON

# OUTPUT FORMAT

Return valid JSON only.

Use exactly this top-level structure:

{{
  "title": "string",
  "duration": "about 5 minutes",
  "format": "Educational / Explainer",
  "tone": "short tone descriptor, e.g. Clear, practical, instructional",
  "hook": {{
    "time": "0:00–0:15",
    "narration": "spoken narration",
    "on_screen": "concise learner-facing overlay or visual label",
    "b_roll": "specific visual direction"
  }},
  "sections": [
    {{
      "time": "0:15–0:30",
      "heading": "short instructional beat title",
      "narration": "spoken narration",
      "on_screen": "concise learner-facing overlay",
      "b_roll": "specific visual direction"
    }}
  ],
  "close": {{
    "time": "4:30–5:00",
    "narration": "spoken actionable close",
    "on_screen": "final takeaway or action",
    "b_roll": "specific visual direction"
  }},
  "shot_list": [
    "Label: specific production note"
  ]
}}

# FINAL SILENT QUALITY CHECK

Before returning your answer, silently verify all of the following:

- The script teaches rather than merely summarizes.
- The core learning objective is preserved.
- Important named standards are preserved.
- Numbers are copied accurately.
- Measurement units are preserved.
- Mandatory versus optional distinctions remain correct.
- Roles and accountability remain accurate.
- Safety-critical information is retained.
- Important cause-and-effect reasoning is retained.
- Practical scenarios are used when valuable.
- No quiz questions are included.
- Every section teaches one clear concept.
- Every beat, including the hook and close, has a specific visual.
- On-screen text is concise.
- Timestamps are continuous and plausible.
- Narration plausibly fits approximately five minutes.
- Total narration is approximately 700 to 780 words.
- The closing provides action rather than a generic recap.
- No next lesson has been invented.
- The response is syntactically valid JSON.

Return JSON only.
""".strip()


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------

def generate_video_script(
    client,
    source_text: str,
    lesson_title: str,
    *,
    course_name: str = '',
    model: str = 'gpt-4o-mini',
    usage_logger: Callable[..., None] | None = None,
) -> dict | None:
    """Call OpenAI and return a normalized script dict, or None on failure."""
    source = truncate_source((source_text or '').strip())
    if not source:
        return None
    prompt = build_video_script_prompt(source, lesson_title, course_name)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'You are an expert instructional video scriptwriter. '
                        'Transform finished lesson notes into concise, '
                        'visual, production-ready training scripts. '
                        'The lesson notes are the only subject and the only '
                        'factual source of truth. Course name and lesson '
                        'title are labels: if they name a different topic '
                        'than the notes, ignore them. Do not invent a '
                        'recipe, process, or subject that is not in the '
                        'notes. Preserve exact standards, numbers, roles, '
                        'safety requirements, and meaningful distinctions. '
                        'Always return one valid JSON object and nothing else.'
                    ),
                },
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.2,
            response_format={'type': 'json_object'},
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        if usage_logger:
            try:
                usage_logger(response, model)
            except Exception:
                logger.exception('Failed to log video-script OpenAI usage')

        finish_reason = getattr(response.choices[0], 'finish_reason', None)
        if finish_reason == 'length':
            logger.warning(
                'Video script response hit the token limit for lesson %r; '
                'output may be truncated.',
                lesson_title,
            )

        raw_text = (response.choices[0].message.content or '').strip()
        parsed = _parse_json_object(raw_text)
        if not isinstance(parsed, dict):
            logger.warning(
                'Video script model returned non-JSON output for lesson %r: %s',
                lesson_title,
                raw_text[:1000],
            )
            return None
        script = normalize_video_script(parsed, lesson_title)
        log_script_warnings(script, lesson_title)
        return script
    except Exception:
        logger.exception("OpenAI video script failed for lesson '%s'", lesson_title)
        return None


# ---------------------------------------------------------------------------
# Output normalization
# ---------------------------------------------------------------------------

def normalize_video_script(data: Any, lesson_title: str) -> dict:
    """Normalize model output into the stored script schema."""
    raw = data if isinstance(data, dict) else {}
    sections_in = raw.get('sections') if isinstance(raw.get('sections'), list) else []
    shots_in = raw.get('shot_list') if isinstance(raw.get('shot_list'), list) else []

    sections = []
    for item in sections_in[:MAX_SECTIONS]:
        beat = _normalize_beat(item, include_heading=True)
        if _beat_has_content(beat):
            sections.append(beat)

    shot_list = []
    for shot in shots_in:
        text = _clean_text(shot)
        if text:
            shot_list.append(text)

    hook = _normalize_beat(raw.get('hook'), include_heading=False)
    if not hook.get('time'):
        hook['time'] = '0:00–0:20'
    close = _normalize_beat(raw.get('close'), include_heading=False)
    if not close.get('time'):
        close['time'] = '4:30–5:00'

    return {
        'title': _clean_text(raw.get('title')) or (lesson_title or 'Video Script'),
        'duration': _clean_text(raw.get('duration')) or DEFAULT_DURATION,
        'format': _clean_text(raw.get('format')) or DEFAULT_FORMAT,
        'tone': _clean_text(raw.get('tone')) or DEFAULT_TONE,
        'hook': hook,
        'sections': sections,
        'close': close,
        'shot_list': shot_list[:MAX_SHOT_LIST],
    }


def _normalize_beat(beat, *, include_heading: bool) -> dict:
    source = beat if isinstance(beat, dict) else {}
    result = {
        'time': _clean_text(source.get('time')),
        'narration': _clean_text(source.get('narration')),
        'on_screen': _clean_text(source.get('on_screen')),
        'b_roll': _clean_text(
            source.get('b_roll') or source.get('visual') or source.get('b-roll')
        ),
    }
    if include_heading:
        result['heading'] = _clean_text(source.get('heading'))
    return result


def _beat_has_content(beat: dict) -> bool:
    return any(
        _clean_text(beat.get(key))
        for key in ('heading', 'narration', 'on_screen', 'b_roll')
    )


def count_narration_words(script: dict) -> int:
    total = _word_count((script.get('hook') or {}).get('narration'))
    for section in script.get('sections') or []:
        total += _word_count((section or {}).get('narration'))
    total += _word_count((script.get('close') or {}).get('narration'))
    return total


def _word_count(text) -> int:
    cleaned = _clean_text(text)
    return len(cleaned.split()) if cleaned else 0


def _parse_timestamp(value) -> int | None:
    """Parse the START time of a M:SS / M:SS–M:SS range into seconds."""
    text = _clean_text(value)
    if not text:
        return None
    start = re.split(r'[-–—]', text)[0].strip()
    match = re.match(r'^(\d{1,2}):(\d{2})$', start)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def log_script_warnings(script: dict, lesson_title: str) -> int:
    """Log word-count / structure / timestamp warnings. Never fails."""
    sections = script.get('sections') or []
    if len(sections) < MIN_SECTIONS:
        logger.warning(
            'Video script for lesson %r has only %d sections (min %d).',
            lesson_title,
            len(sections),
            MIN_SECTIONS,
        )

    words = count_narration_words(script)
    logger.info("Video script for lesson '%s' has %s narration words", lesson_title, words)
    print(f"Video script for lesson '{lesson_title}' has {words} narration words")
    if not (TARGET_WORD_MIN <= words <= TARGET_WORD_MAX):
        logger.warning(
            "Video script for lesson '%s' narration word count %s is outside %s–%s",
            lesson_title,
            words,
            TARGET_WORD_MIN,
            TARGET_WORD_MAX,
        )

    beats = [script.get('hook', {})] + list(sections) + [script.get('close', {})]
    starts = [_parse_timestamp(b.get('time')) for b in beats if isinstance(b, dict)]
    known = [s for s in starts if s is not None]
    if known != sorted(known):
        logger.warning(
            "Video script for lesson '%s' has non-monotonic timestamps: %s",
            lesson_title,
            [b.get('time') for b in beats if isinstance(b, dict)],
        )

    times = [_clean_text((b or {}).get('time')) for b in beats]
    joined = ' '.join(t for t in times if t)
    if '5:00' not in joined and '5.00' not in joined:
        logger.warning(
            "Video script for lesson '%s' timestamps may not reach 5:00 (%s)",
            lesson_title,
            joined[:120],
        )
    return words


def script_doc_title(lesson_title: str) -> str:
    title = (lesson_title or 'Lesson').strip() or 'Lesson'
    return f'{title} — Video Script'


# ---------------------------------------------------------------------------
# Google Doc HTML rendering
# ---------------------------------------------------------------------------

def render_script_html(script: dict, lesson_title: str = '') -> str:
    """4-column shooting table HTML for Google Doc conversion."""
    data = script if isinstance(script, dict) else {}
    title = script_doc_title(lesson_title or _clean_text(data.get('title')) or 'Lesson')
    duration = _clean_text(data.get('duration')) or DEFAULT_DURATION
    fmt = _clean_text(data.get('format')) or DEFAULT_FORMAT
    tone = _clean_text(data.get('tone')) or DEFAULT_TONE

    parts = [
        '<html>',
        '<head>',
        '<meta charset="utf-8">',
        '<style>',
        'body { font-family: Arial, Helvetica, sans-serif; line-height: 1.5; color: #111; }',
        'h1 { margin-bottom: 4px; }',
        'h2 { margin-top: 28px; margin-bottom: 8px; }',
        'p { margin: 6px 0; }',
        'table { border-collapse: collapse; width: 100%; margin-top: 12px; }',
        'th, td { border: 1px solid #bbb; padding: 8px; vertical-align: top; text-align: left; }',
        'th { background: #f2f2f2; }',
        'td.time { white-space: nowrap; font-weight: bold; width: 84px; }',
        'td.visual { width: 30%; color: #333; }',
        'td.onscreen { width: 22%; font-weight: bold; }',
        '.meta { color: #555; margin-bottom: 8px; }',
        'ul { margin-top: 8px; }',
        '</style>',
        '</head>',
        '<body>',
        f'<h1>{escape(title)}</h1>',
        (
            '<p class="meta">'
            f'<b>Total runtime:</b> {escape(duration)} &nbsp;·&nbsp; '
            f'<b>Format:</b> {escape(fmt)} &nbsp;·&nbsp; '
            f'<b>Tone:</b> {escape(tone)}'
            '</p>'
        ),
        '<table>',
        '<thead><tr>',
        '<th>Time</th>',
        '<th>Visual</th>',
        '<th>Narration (VO)</th>',
        '<th>On-Screen Text</th>',
        '</tr></thead>',
        '<tbody>',
    ]

    hook = data.get('hook') if isinstance(data.get('hook'), dict) else {}
    if _beat_has_content(hook):
        parts.append(_beat_row(hook, heading='Hook'))

    sections = data.get('sections') if isinstance(data.get('sections'), list) else []
    for i, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        heading = _clean_text(section.get('heading')) or f'Section {i}'
        parts.append(_beat_row(section, heading=heading))

    close = data.get('close') if isinstance(data.get('close'), dict) else {}
    if _beat_has_content(close):
        parts.append(_beat_row(close, heading='Close'))

    parts.extend(['</tbody>', '</table>'])

    shots = [_clean_text(item) for item in (data.get('shot_list') or []) if _clean_text(item)]
    if shots:
        parts.append('<h2>Production Notes</h2>')
        parts.append('<ul>')
        parts.extend(_production_note_html(shot) for shot in shots)
        parts.append('</ul>')

    parts.extend(['</body>', '</html>'])
    return '\n'.join(parts)


script_to_html = render_script_html


def _beat_row(beat: dict, *, heading: str) -> str:
    time = escape(_clean_text(beat.get('time')))
    visual = escape(_clean_text(beat.get('b_roll')))
    narration = escape(_clean_text(beat.get('narration')))
    on_screen = escape(_clean_text(beat.get('on_screen')))
    beat_heading = _clean_text(beat.get('heading')) or heading
    heading_html = f'<b>{escape(beat_heading)}</b><br>' if beat_heading else ''
    return (
        '<tr>'
        f'<td class="time">{time}</td>'
        f'<td class="visual">{heading_html}{visual}</td>'
        f'<td>{narration}</td>'
        f'<td class="onscreen">{on_screen}</td>'
        '</tr>'
    )


def _production_note_html(note: str) -> str:
    match = re.match(r'^([^:]{1,32}):\s*(.+)$', note)
    if match:
        label = escape(match.group(1).strip())
        rest = escape(match.group(2).strip())
        return f'<li><b>{label}:</b> {rest}</li>'
    return f'<li>{escape(note)}</li>'


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def _parse_json_object(text):
    """Parse a JSON object from a model response. Returns None if unusable."""
    if not text:
        return None
    s = text.strip()
    if s.startswith('```'):
        s = re.sub(r'^```(?:json)?\s*', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\s*```$', '', s)
        s = s.strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    candidate = _extract_balanced_json_object(s)
    if not candidate:
        return None
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == '\\':
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None
