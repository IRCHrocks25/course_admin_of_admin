"""Prompt builders and generation settings for AI lesson generation.

These functions are pure: no I/O, no DB, no API calls. That makes them
testable in isolation and lets us iterate on wording without touching the
call sites in dashboard_views.py.
"""
from dataclasses import dataclass, asdict
from typing import Tuple


@dataclass(frozen=True)
class LessonGenerationSettings:
    """User-configurable knobs that shape AI lesson output.

    Step 2 wires this through the pipeline. Step 3 will honor
    `reading_level`, `length`, and `depth` in the prompt builders. The
    remaining fields are scaffolded for future controls and are accepted
    but ignored today, so persisted settings dicts forward-compatibly.
    """

    reading_level: str = 'practitioner'        # foundational | practitioner | expert
    length: str = 'standard'                   # short | standard | deep
    depth: str = 'how_to'                      # overview | how_to | comprehensive
    tone: str = 'coach'                        # coach | professor | peer | from_sample
    outcomes_count: int = 5
    creativity: str = 'balanced'               # precise | balanced | inventive
    enabled_block_types: Tuple[str, ...] = ('paragraph', 'header', 'list', 'quote')
    audience_override: str = ''

    @classmethod
    def from_dict(cls, data):
        """Build from a JSONField payload. Unknown keys ignored, bad types fall back to defaults."""
        if not isinstance(data, dict):
            return cls()
        defaults = cls()
        try:
            return cls(
                reading_level=data.get('reading_level', defaults.reading_level),
                length=data.get('length', defaults.length),
                depth=data.get('depth', defaults.depth),
                tone=data.get('tone', defaults.tone),
                outcomes_count=int(data.get('outcomes_count', defaults.outcomes_count)),
                creativity=data.get('creativity', defaults.creativity),
                enabled_block_types=tuple(data.get('enabled_block_types', defaults.enabled_block_types)),
                audience_override=data.get('audience_override', defaults.audience_override),
            )
        except (TypeError, ValueError):
            return cls()

    def to_dict(self):
        d = asdict(self)
        d['enabled_block_types'] = list(self.enabled_block_types)
        return d


READING_LEVEL_DIRECTIVES = {
    'foundational': 'plain, concrete language; define every term on first use; aim for ~8th-grade readability; no jargon without a one-line gloss.',
    'practitioner': 'professional but accessible language; assume the reader has basic familiarity with the field; briefly explain advanced terms.',
    'expert': 'precise, dense language; assume the reader is a practitioner; do not explain core terms; use field-standard nomenclature.',
}

LENGTH_DIRECTIVES = {
    'short': 'produce 4-6 content blocks (~250 words). Keep it tight; one idea per block.',
    'standard': 'produce 7-10 content blocks (~600 words).',
    'deep': 'produce 12-16 content blocks (~1200 words). Include worked examples and edge cases.',
}

DEPTH_DIRECTIVES = {
    'overview': 'focus on the WHAT and WHY. At most one worked example.',
    'how_to': 'focus on the HOW. Include 2-3 worked examples and a step checklist.',
    'comprehensive': 'cover what / why / how, plus common pitfalls and one advanced edge case.',
}


def _generation_directives_block(settings):
    """Prompt fragment listing user-facing generation directives.

    Always emitted (even at defaults) so the model receives a concrete brief
    instead of the vague "engaging and informative" wording it had before
    these controls existed.
    """
    parts = []
    rl = READING_LEVEL_DIRECTIVES.get(settings.reading_level)
    if rl:
        parts.append(f"Reading level — {rl}")
    ln = LENGTH_DIRECTIVES.get(settings.length)
    if ln:
        parts.append(f"Lesson length — {ln}")
    dp = DEPTH_DIRECTIVES.get(settings.depth)
    if dp:
        parts.append(f"Content depth — {dp}")
    if not parts:
        return ''
    return "Generation directives (follow strictly):\n" + "\n".join(f"- {p}" for p in parts)


def build_lesson_metadata_prompt(inputs, settings):
    """Build the prompt for clean_title / summary / description / outcomes / coach_actions."""
    blueprint_context = inputs.get('blueprint_context') or ''
    extra = f"\n{blueprint_context}\n" if blueprint_context else ''
    directives = _generation_directives_block(settings)
    directives_block = f"\n{directives}\n" if directives else ''
    return f"""You are an expert course creator. Generate comprehensive lesson metadata for the following lesson:

Course: {inputs['course_name']}
Course Type: {inputs['course_type']}
Lesson Title: {inputs['lesson_title']}
Lesson Description: {inputs['lesson_description']}
{extra}{directives_block}
Generate the following fields:
1. clean_title: A polished, professional version of the lesson title (keep it concise and clear)
2. short_summary: A 1-2 sentence summary for lesson cards/lists (max 150 characters)
3. full_description: A detailed 2-3 paragraph description explaining what students will learn (engaging and informative)
4. outcomes: An array of 3-5 specific learning outcomes (what students will achieve)
5. coach_actions: An array of 3-4 recommended AI coach actions (e.g., "Summarize in 5 bullets", "Create a 3-step action plan")

Return in JSON format:
{{
  "clean_title": "Polished Lesson Title",
  "short_summary": "Brief summary for lesson cards",
  "full_description": "Detailed multi-paragraph description of what students will learn in this lesson. Make it engaging and informative.",
  "outcomes": [
    "Outcome 1",
    "Outcome 2",
    "Outcome 3"
  ],
  "coach_actions": [
    "Action 1",
    "Action 2",
    "Action 3"
  ]
}}

Only return valid JSON, no additional text."""


def build_lesson_content_prompt(inputs, settings):
    """Build the prompt for Editor.js content blocks."""
    blueprint_context = inputs.get('blueprint_context') or ''
    extra = f"\n{blueprint_context}\n" if blueprint_context else ''
    directives = _generation_directives_block(settings)
    directives_block = f"\n{directives}\n" if directives else ''
    return f"""You are an expert course creator. Create comprehensive lesson content for the following lesson:

Course: {inputs['course_name']}
Course Type: {inputs['course_type']}
Lesson Title: {inputs['lesson_title']}
Lesson Description: {inputs['lesson_description']}
{extra}{directives_block}
Generate detailed lesson content that includes:
1. An engaging introduction paragraph
2. Key learning objectives (as headers)
3. Main content sections with explanations
4. Practical examples or tips
5. A summary or conclusion

Return the content in JSON format with Editor.js compatible blocks:
{{
  "content": [
    {{
      "type": "header",
      "text": "Section Title",
      "level": 2
    }},
    {{
      "type": "paragraph",
      "text": "Paragraph text here"
    }},
    {{
      "type": "list",
      "style": "unordered",
      "items": ["Item 1", "Item 2", "Item 3"]
    }},
    {{
      "type": "quote",
      "text": "Important quote or tip",
      "caption": "Optional caption"
    }}
  ]
}}

Make the content educational, practical, and engaging. Match the lesson-length directive above for the number of blocks.
Only return valid JSON, no additional text."""
