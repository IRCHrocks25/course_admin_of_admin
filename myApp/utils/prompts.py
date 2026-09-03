"""Prompt builders and generation settings for AI lesson generation.

These functions are pure: no I/O, no DB, no API calls. That makes them
testable in isolation and lets us iterate on wording without touching the
call sites in dashboard_views.py.
"""
from dataclasses import dataclass, asdict
from typing import Tuple
import json


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
    generate_image: bool = True
    generate_quiz: bool = True
    skip_exercise: bool = False

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
                generate_image=bool(data.get('generate_image', defaults.generate_image)),
                generate_quiz=bool(data.get('generate_quiz', defaults.generate_quiz)),
                skip_exercise=bool(data.get('skip_exercise', defaults.skip_exercise)),
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


def target_lesson_count(blueprint, default=12):
    """Read total_classes from a creation blueprint. Form range is 1–120."""
    if not isinstance(blueprint, dict):
        return default
    raw = blueprint.get('total_classes')
    if raw in (None, ''):
        return default
    try:
        return max(1, min(120, int(raw)))
    except (TypeError, ValueError):
        return default


def build_course_structure_prompt(course_name, description, course_type='sprint',
                                  coach_name='Sprint Coach', blueprint=None,
                                  short_description='', blueprint_extra=''):
    """Syllabus prompt: source brief + exact lesson count + generation settings."""
    source = '\n\n'.join(
        part for part in (
            (short_description or '').strip(),
            (description or '').strip(),
        ) if part
    )
    title = (course_name or '').strip() or '(untitled)'
    n = target_lesson_count(blueprint)
    gen = LessonGenerationSettings.from_dict(
        blueprint.get('generation_settings') if isinstance(blueprint, dict) else None
    )
    directives = _generation_directives_block(gen)
    directives_block = f"\n{directives}\n" if directives else ''
    extra = f"\n{blueprint_extra}\n" if (blueprint_extra or '').strip() else ''
    source_block = source or (
        'No source brief was provided. Plan the course from the working title only.'
    )
    return f"""You are an expert course creator. Build a complete course syllabus from the SOURCE BRIEF below.

Course type: {course_type}
Coach name: {coach_name}
Working title (label only): {title}

SOURCE BRIEF (this IS the course subject — not optional flavor text):
{source_block}

Grounding rules (follow strictly):
- Teach the subject in the SOURCE BRIEF. The working title is a label only.
- If the title or a "topic" label is about a different subject than the source brief, IGNORE the title/topic. Do not plan a course about the title and then sprinkle in a few source keywords.
- Every module and lesson must come from the source brief. You may sequence and name lessons, but do not invent a new subject.

HARD COUNT (do not ignore):
- Create EXACTLY {n} lessons in total across all modules.
- The sum of lessons in every module MUST equal {n}. Not "about {n}". Not 12-30 unless {n} is in that range.
- Choose a module count that fits {n} lessons (typically 2-8 modules; fewer modules when {n} is small).
{directives_block}{extra}
Return the structure in JSON format:
{{
  "modules": [
    {{
      "name": "Module Name",
      "description": "Brief module description drawn from the source brief",
      "order": 1,
      "lessons": [
        {{
          "title": "Lesson Title",
          "description": "Detailed lesson description of what students will learn from the source brief",
          "order": 1
        }}
      ]
    }}
  ]
}}

Only return valid JSON, no additional text."""


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
    if not getattr(settings, 'generate_quiz', True):
        parts.append('Do not invent quiz sections, practice quizzes, or quiz questions in the lesson notes.')
    if getattr(settings, 'skip_exercise', False):
        parts.append('Do not invent exercises, drills, practice worksheets, or homework sections.')
    if not parts:
        return ''
    return "Generation directives (follow strictly):\n" + "\n".join(f"- {p}" for p in parts)


def _source_grounding_block(inputs):
    """Force the model to teach the pasted notes/transcript, not the title.

    Title and course name are labels. If they name a different subject than
    the source (coffee title + hydrotherapy notes), the source wins.
    """
    source = (inputs.get('lesson_description') or '').strip()
    title = (inputs.get('lesson_title') or '').strip() or '(untitled)'
    course = (inputs.get('course_name') or '').strip() or '(unnamed course)'
    if not source:
        return (
            "No source notes or transcript were provided. "
            "Write the lesson from the lesson title and course context only.\n"
        )
    return (
        "SOURCE MATERIAL (this IS the lesson — not optional flavor text):\n"
        f"{source}\n\n"
        "Grounding rules (follow strictly):\n"
        f'- Teach the subject in the SOURCE MATERIAL. The working title "{title}" '
        f'and course name "{course}" are labels only.\n'
        "- If the title or course name is about a different topic than the source, "
        "IGNORE the title/course topic. Do not write a lesson about the title and "
        "then sprinkle in a few source keywords.\n"
        "- Every fact, number, definition, and teaching point must come from the "
        "source. You may reorganize, clarify, and add brief connective explanation, "
        "but do not invent a new subject.\n"
        "- If the source looks like a transcript or technical notes, convert it into "
        "polished lesson notes that preserve those facts.\n"
    )


def build_lesson_metadata_prompt(inputs, settings):
    """Build the prompt for clean_title / summary / description / outcomes / coach_actions."""
    blueprint_context = inputs.get('blueprint_context') or ''
    extra = f"\n{blueprint_context}\n" if blueprint_context else ''
    directives = _generation_directives_block(settings)
    directives_block = f"\n{directives}\n" if directives else ''
    grounding = _source_grounding_block(inputs)
    return f"""You are an expert course creator. Generate lesson metadata grounded in the source material below.

Course (label only): {inputs['course_name']}
Course Type: {inputs['course_type']}
Working title (label only): {inputs['lesson_title']}
{grounding}{extra}{directives_block}
Generate the following fields:
1. clean_title: If the working title names the SAME subject as the source, polish it. If the working title names a DIFFERENT subject, replace it with a concise title for the SOURCE topic. Never keep a mismatched title.
2. short_summary: A 1-2 sentence summary of the SOURCE topic for lesson cards/lists (max 150 characters)
3. full_description: A detailed 2-3 paragraph description of what students will learn from the SOURCE (do not describe a different subject)
4. outcomes: An array of 3-5 specific learning outcomes drawn from the source
5. coach_actions: An array of 3-4 recommended AI coach actions for THIS source topic (e.g., "Summarize in 5 bullets", "Create a 3-step action plan")

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
    grounding = _source_grounding_block(inputs)
    return f"""You are an expert course creator. Create lesson notes that teach the source material below.

Course (label only): {inputs['course_name']}
Course Type: {inputs['course_type']}
Working title (label only): {inputs['lesson_title']}
{grounding}{extra}{directives_block}
Generate detailed lesson content that includes:
1. An engaging introduction paragraph about the SOURCE topic
2. Key learning objectives from the source (as headers)
3. Main content sections that explain the source facts, definitions, and numbers
4. Practical examples or tips that stay inside the source subject
5. A summary or conclusion of the source topic

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
def build_lesson_image_prompt(
    clean_title: str,
    short_summary: str,
    reading_level: str = "practitioner",
    source_text: str = "",
) -> str:
    """Fallback image prompt when the custom brief call fails.

    Subject comes from source notes when present. Title is a label only.
    """

    level_map = {
        "foundational": "approachable for beginner learners, clear, encouraging, and easy to understand",
        "practitioner": "designed for business professionals, confident, strategic, and aspirational",
        "expert": "designed for senior leaders, sophisticated, executive, and authoritative",
    }

    audience_style = level_map.get(
        reading_level,
        "designed for business professionals, confident, strategic, and aspirational"
    )

    source_snippet = (source_text or '').strip()
    summary_snippet = (short_summary or '').strip() or source_snippet[:350] or clean_title
    subject_block = source_snippet[:1200] if source_snippet else summary_snippet

    return (
        f"Create a premium cinematic 16:9 hero banner image for an online course lesson.\n\n"
        f"Working title (label only — do not depict this if it conflicts with the source): {clean_title}\n"
        f"SOURCE SUBJECT (this is what the image must show):\n{subject_block}\n\n"

        f"Core visual idea:\n"
        f"Show the real-world meaning of the SOURCE SUBJECT through a polished, professional scene. "
        f"If the working title names a different topic than the source, ignore the title. "
        f"The image should feel like a premium course platform header for THIS subject.\n\n"

        f"Scene direction:\n"
        f"Match the source subject. Do not default to coffee, food, offices, boardrooms, or AI dashboards "
        f"unless the source is genuinely about those things. Include realistic people or environments "
        f"that belong to the source topic.\n\n"

        f"Composition:\n"
        f"Cinematic widescreen layout, rule of thirds, strong depth of field, premium spacing, clean visual hierarchy. "
        f"Leave some natural negative space on one side or upper area so the platform can overlay lesson text later. "
        f"The image should work as a header background and should not feel cluttered.\n\n"

        f"Style and lighting:\n"
        f"Photorealistic, ultra high resolution, warm-to-neutral color grade that fits the source subject. "
        f"Mood should feel intelligent, aspirational, calm, and premium.\n\n"

        f"Audience fit:\n"
        f"Suitable for {audience_style}.\n\n"

        f"Strict rules:\n"
        f"No readable text. No letters. No numbers. No labels. No logos. No watermarks. "
        f"No cartoon style. No flat illustration. No childish avatar look. No messy UI mockups. "
        f"No obvious stock photo cheesiness. No exaggerated sci-fi. No split-screen before-and-after layout.\n\n"

        f"Output:\n"
        f"Aspect ratio 16:9, premium course platform hero image, polished edtech aesthetic."
    )


def _audience_phrase_for(reading_level: str) -> str:
    return {
        'foundational': 'approachable, encouraging, beginner-friendly',
        'practitioner': 'confident, strategic, aspirational',
        'expert': 'sophisticated, executive, authoritative',
    }.get(reading_level, 'confident, strategic, aspirational')


def build_image_brief_meta_prompt(course_name: str,
                                  course_category: str,
                                  course_topic: str,
                                  lesson_title: str,
                                  lesson_summary: str,
                                  lesson_description: str,
                                  lesson_outcomes: list,
                                  reading_level: str = 'practitioner',
                                  source_text: str = '') -> str:
    """Meta-prompt: instructs gpt-4o-mini to write a tailored image brief
    for a specific lesson. The brief it returns is then fed to gpt-image-1.

    Source notes / transcription win over a mismatched course name or title.
    """
    outcomes_text = '\n'.join(f'- {o}' for o in (lesson_outcomes or [])[:5]) or '(none provided)'
    category_line = f"Course category (label only): {course_category}" if course_category else ''
    topic_line = f"Course topic label (ignore if it conflicts with source): {course_topic}" if course_topic else ''
    context_lines = '\n'.join(filter(None, [category_line, topic_line]))
    source = (source_text or lesson_description or lesson_summary or '').strip()

    return f"""You are a senior creative director designing hero images for an online course platform.

Read the SOURCE MATERIAL below. That is the lesson subject. Write a vivid image brief that an AI image generator (gpt-image-1) will use to produce a 16:9 hero banner.

Grounding rules (follow strictly):
- Depict the SOURCE MATERIAL. Course name and working title are labels only.
- If the title or course name is about a different topic than the source, IGNORE the title/course topic. Do not draw coffee, food, or the title subject just because the label says so.
- Do not default to "business / corporate / boardroom / AI dashboards" unless the source is genuinely about those things.

Examples of fitting tone:
- Hydrotherapy / density / water physics → clinical pool, immersion, water, body mechanics
- A fitness lesson → physical, energetic, sweat, motion, gym or outdoors
- A mindfulness / life-mastery lesson → still, luminous, natural light, journals, tea, nature
- A coding lesson → focused, technical, screens, keyboards, ambient code glow
- A cooking lesson → warm, tactile, ingredients, kitchen, steam
- A music lesson → instruments, stage light, intimate performance
- A parenting / relationship lesson → human warmth, candid moments, soft light
- A business / strategy lesson → sharp, strategic, modern workspaces

Your brief MUST specify, in concrete language:
1. The scene (place, objects, people if any, what's happening)
2. Mood and atmosphere (in 1-2 adjectives)
3. Color palette and lighting (e.g. "warm amber, deep teal, golden-hour light")
4. Composition notes (16:9 landscape; where to leave negative space for a title overlay)
5. Style (photorealistic / cinematic / editorial — pick what fits the subject)
6. Hard constraints to repeat verbatim:
   - "No text, letters, numbers, labels, logos, or watermarks."
   - "Premium course-platform aesthetic, suitable for a hero banner."

Audience: {reading_level} ({_audience_phrase_for(reading_level)}).

SOURCE MATERIAL (this is the subject of the image):
{source[:2500] or '(none)'}

LABELS (do not use these as the subject if they conflict with the source)
Course: {course_name}
{context_lines}
Working title: {lesson_title}
Lesson summary: {lesson_summary or '(none)'}
Key outcomes:
{outcomes_text}

Write the image brief now. Output ONLY the brief — no preamble, no headings, no JSON, no quotes. 3-5 paragraphs of dense, concrete visual direction the image model can execute on."""


LANGUAGE_NAMES = {
    'it': 'Italian',
    'fil': 'Filipino',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
    'pt': 'Portuguese',
}


def build_lesson_translation_prompt(lesson_payload, target_language_code):
    """Build prompt to translate English lesson metadata + Editor.js blocks."""
    language_name = LANGUAGE_NAMES.get(target_language_code, target_language_code)
    content_json = json.dumps(lesson_payload.get('content_blocks', []), ensure_ascii=False, indent=2)
    outcomes_json = json.dumps(lesson_payload.get('outcomes', []), ensure_ascii=False)
    coach_json = json.dumps(lesson_payload.get('coach_actions', []), ensure_ascii=False)

    return f"""You are an expert translator for online course content. Translate the following English lesson into natural, fluent {language_name}.

Rules:
- Translate all human-readable text fields.
- Preserve JSON structure exactly.
- Do NOT translate URLs, IDs, block types, or header levels.
- Keep the same number of content blocks in the same order.
- Use professional, educational tone appropriate for adult learners.

English source:
Title: {lesson_payload.get('title', '')}
Short summary: {lesson_payload.get('short_summary', '')}
Full description: {lesson_payload.get('full_description', '')}
Outcomes: {outcomes_json}
Coach actions: {coach_json}
Content blocks: {content_json}

Return JSON only:
{{
  "title": "translated title",
  "short_summary": "translated summary",
  "full_description": "translated description",
  "outcomes": ["..."],
  "coach_actions": ["..."],
  "content": [
    {{"type": "header", "text": "...", "level": 2}},
    {{"type": "paragraph", "text": "..."}},
    {{"type": "list", "style": "unordered", "items": ["..."]}},
    {{"type": "quote", "text": "...", "caption": "..."}}
  ]
}}"""

