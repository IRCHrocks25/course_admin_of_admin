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
    generate_image: bool = True

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
def build_lesson_image_prompt(
    clean_title: str,
    short_summary: str,
    reading_level: str = "practitioner"
) -> str:
    """
    Build a DALL-E 3 image generation prompt for a premium lesson hero image.
    Style: cinematic, corporate edtech, AI-business transformation, photorealistic.
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

    summary_snippet = short_summary[:350].strip() if short_summary else clean_title

    return (
        f"Create a premium cinematic 16:9 hero banner image for an online business and AI course lesson.\n\n"
        f"Lesson title: {clean_title}\n"
        f"Lesson context: {summary_snippet}\n\n"

        f"Core visual idea:\n"
        f"Show the real-world business meaning of this lesson through a polished, professional scene. "
        f"The image should feel like a high-end corporate AI transformation campaign, similar to a premium "
        f"course platform header, executive training module, or modern SaaS brand visual.\n\n"

        f"Scene direction:\n"
        f"Use a modern office, boardroom, strategy room, glass-walled workspace, city-view executive setting, "
        f"or collaborative business environment. Include one or more realistic professionals who appear thoughtful, "
        f"focused, strategic, and actively analyzing business challenges or opportunities. "
        f"The scene should visually suggest business diagnosis, operational clarity, decision-making, AI support, "
        f"process improvement, and future-ready systems.\n\n"

        f"AI and business transformation cues:\n"
        f"Subtle digital intelligence elements may appear as soft holographic glows, abstract data patterns, "
        f"transparent dashboards, network lines, process maps, or analytical light structures — but they must feel "
        f"integrated into the environment, not like flat icons or fake UI. Keep these elements elegant, minimal, "
        f"and cinematic.\n\n"

        f"Composition:\n"
        f"Cinematic widescreen layout, rule of thirds, strong depth of field, premium spacing, clean visual hierarchy. "
        f"Leave some natural negative space on one side or upper area so the platform can overlay lesson text later. "
        f"The image should work as a header background and should not feel cluttered.\n\n"

        f"Style and lighting:\n"
        f"Photorealistic, ultra high resolution, warm-to-neutral corporate color grade. "
        f"Use deep navy, soft cyan, warm amber, glass reflections, natural window light, soft shadows, "
        f"and rich professional textures. Mood should feel intelligent, aspirational, calm, and premium.\n\n"

        f"Audience fit:\n"
        f"Suitable for {audience_style}.\n\n"

        f"Strict rules:\n"
        f"No readable text. No letters. No numbers. No labels. No logos. No watermarks. "
        f"No cartoon style. No flat illustration. No childish avatar look. No messy UI mockups. "
        f"No obvious stock photo cheesiness. No exaggerated sci-fi. No split-screen before-and-after layout. "
        f"The image must look like a real cinematic business moment enhanced by subtle AI intelligence.\n\n"

        f"Output:\n"
        f"Aspect ratio 16:9, premium course platform hero image, polished corporate edtech aesthetic."
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
                                  reading_level: str = 'practitioner') -> str:
    """Meta-prompt: instructs gpt-4o-mini to write a tailored image brief
    for a specific lesson. The brief it returns is then fed to gpt-image-1.

    This is what makes the image context-aware: the LLM reads the actual
    lesson (subject, outcomes, audience) and designs a visual concept that
    fits it, instead of forcing every lesson into one hard-coded aesthetic.
    """
    outcomes_text = '\n'.join(f'- {o}' for o in (lesson_outcomes or [])[:5]) or '(none provided)'
    category_line = f"Course category: {course_category}" if course_category else ''
    topic_line = f"Course topic (creator-supplied): {course_topic}" if course_topic else ''
    context_lines = '\n'.join(filter(None, [category_line, topic_line]))

    return f"""You are a senior creative director designing hero images for an online course platform.

Read the lesson below, understand what it is REALLY about, then write a vivid image brief that an AI image generator (gpt-image-1) will use to produce a 16:9 hero banner.

Match the SUBJECT MATTER. Do not default to "business / corporate / boardroom / AI dashboards" unless the lesson is genuinely about those things. Examples of fitting tone:
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

LESSON CONTEXT
Course: {course_name}
{context_lines}
Lesson title: {lesson_title}
Lesson summary: {lesson_summary or '(none)'}
Lesson description: {(lesson_description or '')[:800]}
Key outcomes:
{outcomes_text}

Write the image brief now. Output ONLY the brief — no preamble, no headings, no JSON, no quotes. 3-5 paragraphs of dense, concrete visual direction the image model can execute on."""
