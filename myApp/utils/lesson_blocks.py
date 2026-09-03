"""Display-time and import helpers for Editor.js lesson blocks."""
from __future__ import annotations

import re
from typing import Any

_INVISIBLE_RE = re.compile(r'[\u200b\u200c\u200d\ufeff]')
_NUMBERED_START_RE = re.compile(r'(?<![A-Za-z0-9])(\d{1,2})\.\s+(?=[A-Za-z“"‘])')
_BULLET_SPLIT_RE = re.compile(r'(?:^|\s+)[•●▪◦]\s+')
_GLUED_SENTENCE_RE = re.compile(r'([a-z0-9\)])\.([A-Z])')
_KNOWN_HEADING_RE = re.compile(
    r'(?:(?<=[.!?;:])\s*|(?<=\s)|^)'
    r'(Learning Objectives|Overview|Clinical Relevance|Study Time|Assessment Note|'
    r'Introduction|Precautions:?|Clinical Application:?|Physiological Effects|'
    r'Depth-Based Biomechanics(?:\s*\(\d+\))?|Pool chemistry|'
    r'Four core clinical screening questions|'
    r'Layer\s+\d+\s*[-–—]\s*[A-Z]+|'
    r'Step\s+\d+\s*[-–—]\s+[A-Z][A-Za-z0-9’\']*(?:\s+(?:&|(?!Use\b|This\b|Look\b)[A-Z][A-Za-z0-9’\']+))*|'
    r'Test\s+\d+\s*[-–—:]\s+[A-Z0-9][A-Za-z0-9’\'\-/]*(?:\s+[A-Z0-9][A-Za-z0-9’\'\-/]*)*'
    r'(?=\s+(?:See\s+Appendix|[A-Z][a-z]{3,}\s+[a-z])|\s*$))'
)
_DEFINITION_RE = re.compile(
    r'(?:(?<=[.!?])\s+|(?<=[•●])\s+|^)'
    r'([A-Z][A-Za-z0-9][A-Za-z0-9/ \-]{0,40}):\s+'
    r'(?=[A-Z“"‘])'
)
_TITLE_BEFORE_BULLET_RE = re.compile(
    r'(?:(?<=[.!?])\s+|^)'
    r'([A-Z][A-Za-z0-9/\-]*(?:\s+[A-Z][A-Za-z0-9/\-]*){0,4}(?:\s*\(\d+\))?)\s+'
    r'(?=[•●])'
)
_DEFINITION_STOP = {
    'there', 'this', 'these', 'that', 'with', 'after', 'because', 'when',
    'while', 'from', 'available', 'looking', 'use', 'for', 'the', 'and',
}


def _normalize_display_text(text: str) -> str:
    text = (text or '').replace('\xa0', ' ')
    text = _INVISIBLE_RE.sub('', text)
    text = re.sub(r'(\d{1,2})\.(?=[A-Za-z“"‘])', r'\1. ', text)
    text = re.sub(r'([•●▪◦])(?=\S)', r'\1 ', text)
    text = _GLUED_SENTENCE_RE.sub(r'\1. \2', text)
    return re.sub(r'[ \t]+', ' ', text).strip()


def _is_noise_text(text: str) -> bool:
    return not (text or '').strip(' :•●▪◦')


def _pretty_heading(text: str) -> str:
    text = (text or '').strip().rstrip(':')
    if text.isupper() and text not in {'INTRODUCTION'}:
        return text.title()
    return text


def _is_definition_label(label: str) -> bool:
    words = [w for w in (label or '').split() if w]
    if not (1 <= len(words) <= 5) or len(label) > 42:
        return False
    return words[0].lower() not in _DEFINITION_STOP


def split_inline_numbered_list(text: str) -> tuple[str, list[str]] | None:
    """Split 'Preamble: 1. Foo. 2. Bar. 3. Baz' into preamble + items."""
    text = _normalize_display_text(text)
    if not text:
        return None
    matches = list(_NUMBERED_START_RE.finditer(text))
    if len(matches) < 2:
        return None
    nums = [int(m.group(1)) for m in matches]
    if nums[0] != 1 or nums != list(range(1, len(nums) + 1)):
        return None
    preamble = text[:matches[0].start()].strip()
    items: list[str] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        item = text[start:end].strip().rstrip('.')
        if item:
            items.append(item)
    if len(items) < 2:
        return None
    return preamble, items


def _split_bullet_chunk(text: str) -> tuple[str, list[str]] | None:
    text = _normalize_display_text(text)
    if not text:
        return None
    parts = [p.strip(' .') for p in _BULLET_SPLIT_RE.split(text) if p.strip(' .')]
    if len(parts) < 2:
        return None
    if text.lstrip().startswith(('•', '●', '▪', '◦')):
        return '', parts
    return parts[0], parts[1:]


def _heading_cuts(text: str, include_definitions: bool = False) -> list[tuple[int, int, str]]:
    cuts: list[tuple[int, int, str]] = []
    for pattern in (_KNOWN_HEADING_RE, _TITLE_BEFORE_BULLET_RE):
        for match in pattern.finditer(text):
            label = match.group(1).strip()
            if label:
                cuts.append((match.start(1), match.end(1), label))
    if include_definitions:
        for match in _DEFINITION_RE.finditer(text):
            label = match.group(1).strip()
            if _is_definition_label(label):
                cuts.append((match.start(1), match.end(), label))
    cuts.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    merged: list[tuple[int, int, str]] = []
    used_until = -1
    for start, end, label in cuts:
        if start < used_until:
            continue
        merged.append((start, end, label))
        used_until = end
    return merged


def expand_run_on_paragraph(text: str) -> list[dict[str, Any]]:
    """Turn a joined PDF/Docs paragraph into headings, lists, and paragraphs."""
    text = _normalize_display_text(text)
    if not text:
        return []

    cuts = _heading_cuts(text, include_definitions=False)
    segments: list[tuple[str, str]] = []
    last = 0
    for start, end, label in cuts:
        before = text[last:start].strip(' :')
        if before:
            segments.append(('body', before))
        segments.append(('heading', label))
        last = end
    tail = text[last:].strip()
    if tail:
        segments.append(('body', tail))
    if not segments:
        segments = [('body', text)]

    blocks: list[dict[str, Any]] = []
    for kind, chunk in segments:
        if kind == 'heading':
            blocks.append({'type': 'header', 'data': {'text': _pretty_heading(chunk), 'level': 3}})
            continue
        numbered = split_inline_numbered_list(chunk)
        if numbered:
            preamble, items = numbered
            blocks.extend(_blocks_from_numbered(preamble, items))
            continue
        bullets = _split_bullet_chunk(chunk)
        if bullets:
            preamble, items = bullets
            if preamble and not _is_noise_text(preamble):
                blocks.extend(_expand_plain_or_definitions(preamble))
            blocks.append({'type': 'list', 'data': {'style': 'unordered', 'items': items}})
            continue
        blocks.extend(_expand_plain_or_definitions(chunk))
    return blocks


def _expand_plain_or_definitions(text: str) -> list[dict[str, Any]]:
    """Split leftover prose on Term: definition labels only (not bullet rows)."""
    cuts = _heading_cuts(text, include_definitions=True)
    if _is_noise_text(text):
        return []
    if not cuts:
        return [{'type': 'paragraph', 'data': {'text': text}}]
    blocks: list[dict[str, Any]] = []
    last = 0
    for start, end, label in cuts:
        before = text[last:start].strip(' :')
        if before and not _is_noise_text(before):
            blocks.append({'type': 'paragraph', 'data': {'text': before}})
        blocks.append({'type': 'header', 'data': {'text': _pretty_heading(label), 'level': 3}})
        last = end
    tail = text[last:].strip()
    if tail and not _is_noise_text(tail):
        blocks.append({'type': 'paragraph', 'data': {'text': tail}})
    return blocks


def _blocks_from_numbered(preamble: str, items: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if preamble and not _is_noise_text(preamble):
        blocks.append({'type': 'paragraph', 'data': {'text': preamble}})
    if items:
        blocks.append({'type': 'list', 'data': {'style': 'ordered', 'items': items}})
    return blocks


def _block_type(block: dict[str, Any]) -> str:
    return str(block.get('type') or '')


def _block_data(block: dict[str, Any]) -> dict[str, Any]:
    data = block.get('data')
    return data if isinstance(data, dict) else {}


def _paragraph_text(block: dict[str, Any]) -> str:
    data = _block_data(block)
    return str(data.get('text') or block.get('text') or '').strip()


def _header_text(block: dict[str, Any]) -> str:
    data = _block_data(block)
    return str(data.get('text') or block.get('text') or '').strip()


def _image_caption(block: dict[str, Any]) -> str:
    return str(_block_data(block).get('caption') or '').strip()


def _norm_title(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (value or '').lower()).strip()


def _as_editorjs_block(block: dict[str, Any]) -> dict[str, Any]:
    """Normalize import-style {type, text} and Editor.js {type, data}."""
    if 'data' in block:
        return block
    btype = _block_type(block)
    if btype == 'paragraph':
        return {'type': 'paragraph', 'data': {'text': block.get('text', '')}}
    if btype == 'header':
        return {'type': 'header', 'data': {'text': block.get('text', ''), 'level': block.get('level', 2)}}
    if btype == 'list':
        return {'type': 'list', 'data': {'style': block.get('style', 'unordered'), 'items': block.get('items') or []}}
    if btype == 'quote':
        return {'type': 'quote', 'data': {'text': block.get('text', ''), 'caption': block.get('caption', '')}}
    if btype == 'image':
        url = block.get('url') or ''
        return {'type': 'image', 'data': {'file': {'url': url}, 'caption': block.get('caption', '')}}
    if btype == 'video':
        return {
            'type': 'video',
            'data': {
                'url': block.get('url') or '',
                'caption': block.get('caption', ''),
            },
        }
    return block


def _should_join_headers(left: str, right: str) -> bool:
    left = left.rstrip()
    right = right.strip()
    if not left or not right:
        return False
    if left.endswith(('&', '—', '–', '-', ':')):
        return True
    after_num = re.sub(r'^\d+(?:\.\d+)*\s*', '', left).strip()
    last_word = after_num.split()[-1].upper() if after_num.split() else ''
    if (
        re.match(r'^\d+\.\d+', left)
        and 1 <= len(right.split()) <= 4
        and not re.match(r'^\d+\.\d+', right)
        and right[0].isupper()
        and (
            len(after_num.split()) <= 3
            or last_word in {'CLINICAL', 'ENVIRONMENTAL', 'DECISION', 'AND'}
        )
    ):
        return True
    return False


def _merge_header_fragments(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    i = 0
    while i < len(blocks):
        current = blocks[i]
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if (
            nxt
            and _block_type(current) == 'header'
            and _block_type(nxt) == 'header'
            and _should_join_headers(_header_text(current), _header_text(nxt))
        ):
            joined = f"{_header_text(current).rstrip(' :')} {_header_text(nxt)}".strip()
            level = (_block_data(current).get('level') or 2)
            merged.append({'type': 'header', 'data': {'text': _pretty_heading(joined), 'level': level}})
            i += 2
            continue
        merged.append(current)
        i += 1
    return merged


_NOTE_CLOSER_RE = re.compile(r'^(If|This|These|When)\b')


def _is_ordered_list(block: dict[str, Any]) -> bool:
    return _block_type(block) == 'list' and (_block_data(block).get('style') or '') == 'ordered'


def _annotation_text(block: dict[str, Any]) -> str:
    if _block_type(block) == 'paragraph':
        return re.sub(r'^[•●▪◦\-\*]\s*', '', _paragraph_text(block)).strip()
    items = [str(item).strip() for item in (_block_data(block).get('items') or []) if str(item).strip()]
    return ' '.join(items)


def _is_bullet_annotation(block: dict[str, Any]) -> bool:
    if _block_type(block) == 'paragraph':
        text = _paragraph_text(block)
        return bool(text) and text[0] in '•●▪◦*-'
    if _block_type(block) == 'list' and (_block_data(block).get('style') or '') != 'ordered':
        items = _block_data(block).get('items') or []
        return 1 <= len(items) <= 2
    return False


def _split_list_note(note: str) -> tuple[str, str]:
    note = (note or '').strip()
    parts = re.split(r'(?<=[.!?])\s+', note, maxsplit=1)
    if len(parts) == 2 and _NOTE_CLOSER_RE.match(parts[1]):
        return parts[0], parts[1]
    return note, ''


def _fold_ordered_list_notes(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep 1. / note / 2. / note as one numbered list, not four separate 1s."""
    out: list[dict[str, Any]] = []
    pending_closers: list[str] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if _is_ordered_list(block) and nxt is not None and _is_bullet_annotation(nxt):
            items = list(_block_data(block).get('items') or [])
            note, extra = _split_list_note(_annotation_text(nxt))
            if items and note:
                items[-1] = f'{items[-1].rstrip()} {note}'.strip()
            out.append({'type': 'list', 'data': {'style': 'ordered', 'items': items}})
            if extra:
                pending_closers.append(extra)
            i += 2
            continue
        if pending_closers and not (
            out and _is_ordered_list(out[-1]) and _is_ordered_list(block)
        ):
            for closer in pending_closers:
                out.append({'type': 'paragraph', 'data': {'text': closer}})
            pending_closers = []
        out.append(block)
        i += 1
    for closer in pending_closers:
        out.append({'type': 'paragraph', 'data': {'text': closer}})
    return out


def _stitch_wrapped_list_items(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rejoin PDF-wrapped list items that were stored as list + lowercase paragraph."""
    out: list[dict[str, Any]] = []
    for block in blocks:
        if (
            out
            and _block_type(out[-1]) == 'list'
            and _block_type(block) == 'paragraph'
        ):
            text = _paragraph_text(block)
            if text and (text[0].islower() or text[0] in '([“"'):
                items = list((_block_data(out[-1]).get('items') or []))
                if items:
                    items[-1] = f'{items[-1].rstrip()} {text}'.strip()
                    out[-1] = {
                        'type': 'list',
                        'data': {
                            'style': _block_data(out[-1]).get('style') or 'unordered',
                            'items': items,
                        },
                    }
                    continue
        if (
            out
            and _block_type(out[-1]) == 'list'
            and _block_type(block) == 'list'
            and _block_data(out[-1]).get('style') == _block_data(block).get('style')
        ):
            left = list(_block_data(out[-1]).get('items') or [])
            right = list(_block_data(block).get('items') or [])
            out[-1] = {
                'type': 'list',
                'data': {
                    'style': _block_data(out[-1]).get('style') or 'unordered',
                    'items': left + right,
                },
            }
            continue
        out.append(block)
    return out


def _drop_fragment_headers(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop short headers that are already contained in the next header."""
    out: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        if _block_type(block) != 'header':
            out.append(block)
            continue
        key = _norm_title(_header_text(block))
        nxt = next((b for b in blocks[i + 1:] if _block_type(b) == 'header'), None)
        if nxt and key and key in _norm_title(_header_text(nxt)) and len(key.split()) <= 5:
            continue
        out.append(block)
    return out


def _drop_duplicate_headers(blocks: list[dict[str, Any]], title: str | None) -> list[dict[str, Any]]:
    title_key = _norm_title(title or '')
    kept: list[dict[str, Any]] = []
    seen: list[str] = []
    if title_key:
        seen.append(title_key)
    for block in blocks:
        if _block_type(block) != 'header':
            kept.append(block)
            continue
        key = _norm_title(_header_text(block))
        if not key:
            continue
        if any(key == prev or (len(key) > 12 and key in prev) for prev in seen):
            continue
        seen.append(key)
        kept.append(block)
    return kept


_SECTION_HEADER_RE = re.compile(r'^\d+\.\d+')


def _is_section_header(block: dict[str, Any]) -> bool:
    return _block_type(block) == 'header' and bool(_SECTION_HEADER_RE.match(_header_text(block)))


def _is_uncaptioned_image(block: dict[str, Any]) -> bool:
    return _block_type(block) == 'image' and not _image_caption(block)


def _interleave_parked_images(
    body: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Spread dumped figures through subsections instead of stacking them."""
    if not images:
        return body, []
    has_sections = any(_is_section_header(block) for block in body)
    if len(images) == 1 and not has_sections:
        return body, images

    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for block in body:
        if _is_section_header(block) and current:
            segments.append(current)
            current = [block]
        else:
            current.append(block)
    if current:
        segments.append(current)
    if not segments:
        return body + images, []

    result: list[dict[str, Any]] = []
    img_i = 0
    total = len(images)
    for index, segment in enumerate(segments):
        result.extend(segment)
        remaining_segments = len(segments) - index
        remaining_images = total - img_i
        take = remaining_images // remaining_segments
        for _ in range(take):
            result.append(images[img_i])
            img_i += 1
    return result, []


def prepare_lesson_article(content: dict[str, Any] | None, title: str | None = None) -> dict[str, Any]:
    """
    Prepare lesson notes for the student article layout.

    - Split run-on PDF/Docs paragraphs into headings, lists, and body copy
    - Join broken chapter titles
    - Keep a single cover figure at the top; weave other figures through sections
    """
    raw_blocks = []
    if isinstance(content, dict):
        raw_blocks = content.get('blocks') or []
    if not isinstance(raw_blocks, list):
        raw_blocks = []

    body: list[dict[str, Any]] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        block = _as_editorjs_block(raw)
        if _block_type(block) == 'paragraph':
            expanded = expand_run_on_paragraph(_paragraph_text(block))
            if expanded:
                body.extend(expanded)
                continue
        body.append(block)

    body = _merge_header_fragments(body)
    body = _drop_fragment_headers(body)
    body = _fold_ordered_list_notes(body)
    body = _stitch_wrapped_list_items(body)
    body = _drop_duplicate_headers(body, title)

    trailing: list[dict[str, Any]] = []
    while body and _is_uncaptioned_image(body[-1]):
        trailing.insert(0, body.pop())
    leading: list[dict[str, Any]] = []
    while body and _is_uncaptioned_image(body[0]):
        leading.append(body.pop(0))
    body, lead_images = _interleave_parked_images(body, leading + trailing)

    from myApp.utils.inline_media import enrich_video_block
    body = [enrich_video_block(b) if _block_type(b) == 'video' else b for b in body]

    return {
        'lead_images': lead_images,
        'blocks': body,
    }
