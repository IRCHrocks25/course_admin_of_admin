"""AI-assisted annotation: let an LLM choose which elements of an imported
landing page become editable CMS fields, with human-friendly section and
field names.

The LLM never touches the HTML. We build an indexed inventory of candidate
elements, the model returns which indices to annotate (plus keys/labels/types),
and we apply the plan deterministically with BeautifulSoup. That makes the
result immune to selector hallucination — a bad index is simply skipped.
"""
from __future__ import annotations

import json
import os
import re

from bs4 import BeautifulSoup

SKIP_TAGS = frozenset({
    'script', 'style', 'svg', 'noscript', 'iframe', 'video', 'audio', 'source',
    'canvas', 'template', 'head', 'meta', 'link', 'title',
})
FIELD_TAGS = frozenset({
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'span', 'strong', 'em',
    'small', 'label', 'figcaption', 'img', 'a', 'button', 'blockquote',
})
INLINE_TAGS = frozenset({'span', 'strong', 'em', 'small'})
INLINE_PARENTS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'a', 'li', 'button', 'figcaption', 'label'})
SECTION_TAGS = frozenset({'section', 'header', 'nav', 'footer', 'main', 'article', 'aside'})
VALID_TYPES = frozenset({'text', 'richtext', 'image', 'link'})

MAX_FIELD_CANDIDATES = 350
MAX_SECTION_CANDIDATES = 80
SNIPPET_LEN = 110
MIN_APPLIED_FIELDS = 3


class AIAnnotationError(Exception):
    """Raised when the AI annotation pass cannot produce a usable result."""


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r'[^a-z0-9_]+', '_', (value or '').strip().lower()).strip('_')
    return slug[:40] or fallback


def _has_skipped_ancestor(element) -> bool:
    parent = element.parent
    while parent is not None and getattr(parent, 'name', None):
        if parent.name.lower() in SKIP_TAGS:
            return True
        parent = parent.parent
    return False


def _inside_existing_edit(element) -> bool:
    parent = element.parent
    while parent is not None and getattr(parent, 'name', None):
        if parent.has_attr('data-edit'):
            return True
        parent = parent.parent
    return False


def _snippet(element) -> str:
    tag = element.name.lower()
    if tag == 'img':
        alt = (element.get('alt') or '').strip()
        src = (element.get('src') or '').strip()
        return f'alt="{alt[:60]}" src="{src[-70:]}"'
    text = element.get_text(' ', strip=True)
    text = re.sub(r'\s+', ' ', text)[:SNIPPET_LEN]
    if tag == 'a':
        href = (element.get('href') or '').strip()
        return f'"{text}" href="{href[:60]}"'
    return f'"{text}"'


def _first_heading_text(element) -> str:
    heading = element.find(['h1', 'h2', 'h3', 'h4'])
    if heading is None:
        return ''
    return re.sub(r'\s+', ' ', heading.get_text(' ', strip=True))[:80]


def collect_candidates(soup):
    """Walk the document once and return (index_map, section_lines, field_lines).

    index_map maps the shared integer index to the live soup element, so the
    plan can be applied to the exact nodes the model saw.
    """
    index_map = {}
    section_lines = []
    field_lines = []
    body = soup.body or soup

    for idx, element in enumerate(body.find_all(True)):
        tag = element.name.lower()
        if tag in SKIP_TAGS or _has_skipped_ancestor(element):
            continue

        is_section_candidate = (
            tag in SECTION_TAGS
            or (tag == 'div' and element.parent is body and (element.get('id') or element.get('class')))
        )
        if is_section_candidate and len(section_lines) < MAX_SECTION_CANDIDATES:
            ident = element.get('id') or ' '.join(element.get('class') or [])[:50]
            heading = _first_heading_text(element)
            index_map[idx] = element
            section_lines.append(f'S{idx} <{tag}> id/class="{ident}" heading="{heading}"')

        if tag not in FIELD_TAGS:
            continue
        if element.has_attr('data-edit') or _inside_existing_edit(element):
            continue
        if tag in INLINE_TAGS:
            parent_tag = element.parent.name.lower() if element.parent and element.parent.name else ''
            if parent_tag in INLINE_PARENTS:
                continue
        if tag == 'img':
            if not (element.get('src') or '').strip():
                continue
        elif len(element.get_text(strip=True)) < 2:
            continue
        if len(field_lines) >= MAX_FIELD_CANDIDATES:
            continue
        index_map[idx] = element
        field_lines.append(f'E{idx} <{tag}> {_snippet(element)}')

    return index_map, section_lines, field_lines


def _build_prompt(section_lines, field_lines) -> str:
    return (
        'You are labeling a landing page for a visual CMS so a non-technical site owner '
        'can edit it. Below is an inventory of the page.\n\n'
        'SECTION CANDIDATES (structural containers):\n'
        + ('\n'.join(section_lines) if section_lines else '(none found)')
        + '\n\nELEMENT CANDIDATES (potential editable fields):\n'
        + '\n'.join(field_lines)
        + '\n\nReturn a JSON object:\n'
        '{"sections": [{"idx": <int from S-lines>, "key": "<snake_case>", "label": "<short friendly name>"}],\n'
        ' "fields": [{"idx": <int from E-lines>, "section": "<section key>", "key": "<snake_case>", '
        '"label": "<short friendly name>", "type": "text|richtext|image|link"}]}\n\n'
        'Rules:\n'
        '- Aim for COMPLETE coverage: include every headline, subheading, paragraph, list item, '
        'button label, image, testimonial, pricing line, and nav/footer link a site owner might edit '
        '(up to 250 fields). Skip only purely decorative or structural elements.\n'
        '- Labels must be short and human ("Main headline", "CTA button", "Feature 1 title"). '
        'Never use raw CSS classes or tag names as labels.\n'
        '- Section labels describe purpose ("Hero banner", "Pricing", "Footer").\n'
        '- type rules: <img> is always "image". <a> is "text" when the owner edits its label '
        '(CTA/buttons) or "link" when the owner edits its URL (nav/menu/footer links). '
        'Use "richtext" only for paragraphs containing inline formatting.\n'
        '- Every field\'s "section" must match a key in "sections". Only use idx values from the inventory.\n'
        '- Output JSON only.'
    )


def _call_model(section_lines, field_lines):
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise AIAnnotationError('OPENAI_API_KEY is not configured.')
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise AIAnnotationError('openai package is not installed.') from exc

    client = OpenAI(api_key=api_key, timeout=90)
    response = client.chat.completions.create(
        model='gpt-4o-mini',
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': 'You label editable regions of landing pages for a visual CMS. You output strict JSON.'},
            {'role': 'user', 'content': _build_prompt(section_lines, field_lines)},
        ],
        temperature=0.2,
        max_tokens=12000,
    )
    raw = (response.choices[0].message.content or '').strip()
    raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIAnnotationError('AI returned invalid JSON.') from exc
    if not isinstance(plan, dict) or not isinstance(plan.get('fields'), list):
        raise AIAnnotationError('AI returned an unexpected structure.')
    return plan, response


def _apply_plan(soup, index_map, plan) -> int:
    body = soup.body or soup

    # 1. Sections first, so field prefixes can resolve against real ancestors.
    used_section_keys = set()
    for item in plan.get('sections') or []:
        if not isinstance(item, dict):
            continue
        element = index_map.get(item.get('idx'))
        if element is None or element.has_attr('data-section'):
            continue
        key = _slug(str(item.get('key') or ''), f'section_{item.get("idx")}')
        suffix = 2
        base = key
        while key in used_section_keys:
            key = f'{base}_{suffix}'
            suffix += 1
        used_section_keys.add(key)
        element['data-section'] = key
        element['data-label'] = str(item.get('label') or key.replace('_', ' ').title())[:60]
        element['data-group'] = 'Home'

    # 2. Fields — the section prefix always comes from the nearest annotated
    #    ancestor, so a wrong "section" value from the model cannot orphan a field.
    counters: dict[str, set] = {}
    applied = 0
    for item in plan.get('fields') or []:
        if not isinstance(item, dict):
            continue
        element = index_map.get(item.get('idx'))
        if element is None or element.has_attr('data-edit') or _inside_existing_edit(element):
            continue
        tag = element.name.lower()

        section_id = None
        parent = element
        while parent is not None and getattr(parent, 'name', None):
            if parent.has_attr('data-section'):
                section_id = parent['data-section']
                break
            parent = parent.parent
        if not section_id:
            section_id = body.get('data-section') or 'landing'
            body['data-section'] = section_id
            body['data-label'] = body.get('data-label') or 'Page'

        field_type = str(item.get('type') or '').strip().lower()
        if tag == 'img':
            field_type = 'image'
        elif field_type == 'image' or field_type not in VALID_TYPES:
            field_type = 'link' if tag == 'a' and field_type == 'link' else 'text'
        if field_type == 'link' and tag != 'a':
            field_type = 'text'

        label = str(item.get('label') or '').strip()[:60]
        base_key = _slug(str(item.get('key') or '') or label, tag)
        keys = counters.setdefault(section_id, {
            el.get('data-edit', '').split('.', 1)[1]
            for el in soup.select(f'[data-edit^="{section_id}."]')
        })
        key = base_key
        suffix = 2
        while key in keys:
            key = f'{base_key}_{suffix}'
            suffix += 1
        keys.add(key)

        element['data-edit'] = f'{section_id}.{key}'
        element['data-type'] = field_type
        element['data-label'] = label or key.replace('_', ' ').title()
        applied += 1

    return applied


MAX_SWEEP_FIELDS = 250


def _nearest_section_id(element, soup):
    parent = element
    while parent is not None and getattr(parent, 'name', None):
        if parent.has_attr('data-section'):
            return parent['data-section']
        parent = parent.parent
    body = soup.body or soup
    section_id = body.get('data-section') or 'landing'
    body['data-section'] = section_id
    body['data-label'] = body.get('data-label') or 'Page'
    return section_id


def _unique_field_key(soup, counters, section_id, base_key):
    keys = counters.setdefault(section_id, {
        el.get('data-edit', '').split('.', 1)[1]
        for el in soup.select(f'[data-edit^="{section_id}."]')
    })
    key = base_key
    suffix = 2
    while key in keys:
        key = f'{base_key}_{suffix}'
        suffix += 1
    keys.add(key)
    return key


def _sweep_unannotated(soup) -> int:
    """Annotate every remaining editable element the AI plan skipped, so the
    whole page is clickable. Labels come from the element's own text."""
    body = soup.body or soup
    counters: dict[str, set] = {}
    added = 0
    for element in body.find_all(True):
        if added >= MAX_SWEEP_FIELDS:
            break
        tag = element.name.lower()
        if tag not in FIELD_TAGS or _has_skipped_ancestor(element):
            continue
        if element.has_attr('data-edit') or _inside_existing_edit(element):
            continue
        # Annotating a parent covers its children; skip wrappers of annotated nodes.
        if element.find(attrs={'data-edit': True}) is not None:
            continue
        if tag in INLINE_TAGS:
            parent_tag = element.parent.name.lower() if element.parent and element.parent.name else ''
            if parent_tag in INLINE_PARENTS:
                continue
        if tag == 'img':
            if not (element.get('src') or '').strip():
                continue
            text = (element.get('alt') or '').strip()
        else:
            text = element.get_text(' ', strip=True)
            if len(text) < 2:
                continue

        if tag == 'img':
            field_type = 'image'
        elif tag == 'a':
            classes = ' '.join(element.get('class') or []).lower()
            is_button = any(t in classes for t in ('btn', 'button', 'cta')) or (element.get('role') or '').lower() == 'button'
            field_type = 'text' if is_button else 'link'
        elif '<' in element.decode_contents():
            field_type = 'richtext'
        else:
            field_type = 'text'

        words = re.sub(r'\s+', ' ', text).split(' ')
        label = ' '.join(words[:5])[:40].strip() or tag.upper()
        section_id = _nearest_section_id(element, soup)
        key = _unique_field_key(soup, counters, section_id, _slug(label, tag))

        element['data-edit'] = f'{section_id}.{key}'
        element['data-type'] = field_type
        element['data-label'] = label
        added += 1
    return added


def _drop_empty_sections(soup):
    """Remove section markers with no editable fields so the sidebar stays clean."""
    for element in soup.select('[data-section]'):
        if not element.select('[data-edit]') and not element.has_attr('data-edit'):
            del element['data-section']
            if element.has_attr('data-group'):
                del element['data-group']


def ai_annotate_html(raw_html: str):
    """Annotate HTML using the LLM plan. Returns (annotated_html, response).

    Raises AIAnnotationError when the model is unavailable or the plan is too
    weak to be useful — callers should fall back to the heuristic annotator.
    """
    html = (raw_html or '').strip()
    if not html:
        raise AIAnnotationError('HTML is empty.')

    soup = BeautifulSoup(html, 'lxml')
    index_map, section_lines, field_lines = collect_candidates(soup)
    if not field_lines:
        raise AIAnnotationError('No annotatable elements found in the HTML.')

    plan, response = _call_model(section_lines, field_lines)
    applied = _apply_plan(soup, index_map, plan)
    # AI names the important fields; the sweep annotates everything else so the
    # full page is clickable in the editor.
    swept = _sweep_unannotated(soup)
    _drop_empty_sections(soup)
    if applied + swept < MIN_APPLIED_FIELDS:
        raise AIAnnotationError('AI selected too few fields to build an editor.')
    return str(soup), response
