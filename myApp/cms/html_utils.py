"""HTML normalization helpers for CMS landing templates."""
from __future__ import annotations

import html as html_module
import re

KATALYST_MARKERS = (
    'herobox', 'beh-grid', 'section--warm', 'section--dark', 'hero-badge',
    'foot-badge', 'hs-page', 'hs-embed', 'hero-gradient-accent',
)

_INLINE_STYLE_THRESHOLD = 4000


def normalize_custom_html_input(raw: str) -> str:
    text = (raw or '').replace('\ufeff', '').strip()
    if not text:
        return ''
    lower = text.lower()
    if '&lt;html' in lower or '&lt;!doctype' in lower:
        text = html_module.unescape(text)
    return text.strip()


def is_full_html_document(html: str) -> bool:
    lower = (html or '').lower()
    if lower.startswith('<!doctype') or '<html' in lower:
        return True
    return '<head' in lower and '<style' in lower


def coerce_full_html_document(html: str) -> str:
    html = normalize_custom_html_input(html)
    if not html:
        return ''
    if is_full_html_document(html):
        return html

    style_blocks = re.findall(r'<style[^>]*>[\s\S]*?</style>', html, flags=re.IGNORECASE)
    link_blocks = re.findall(
        r'<link[^>]*\brel=["\']stylesheet["\'][^>]*>',
        html,
        flags=re.IGNORECASE,
    )
    body_html = html
    for block in link_blocks + style_blocks:
        body_html = body_html.replace(block, '', 1)
    body_html = re.sub(r'<!DOCTYPE[^>]*>', '', body_html, flags=re.IGNORECASE)
    body_html = re.sub(r'<head[^>]*>[\s\S]*?</head>', '', body_html, flags=re.IGNORECASE)
    if '<body' in body_html.lower():
        match = re.search(r'<body[^>]*>([\s\S]*?)</body>', body_html, flags=re.IGNORECASE)
        body_inner = match.group(1).strip() if match else body_html.strip()
    else:
        body_inner = body_html.strip()

    head_extras = ''.join(link_blocks + style_blocks)
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        f'{head_extras}'
        '</head><body>'
        f'{body_inner}'
        '</body></html>'
    )


def should_passthrough_landing_html(html: str) -> bool:
    html = html or ''
    lower = html.lower()
    if not is_full_html_document(html):
        return False
    marker_hits = sum(1 for marker in KATALYST_MARKERS if marker in lower)
    if marker_hits >= 1:
        return True
    style_blocks = re.findall(r'<style[^>]*>([\s\S]*?)</style>', html, flags=re.IGNORECASE)
    total_style_len = sum(len(block) for block in style_blocks)
    return total_style_len >= _INLINE_STYLE_THRESHOLD


def find_document_close_tag(html: str, tag: str) -> int | None:
    """Find real </head> or </body> ignoring closing tags inside style/script."""
    pattern = re.compile(rf'</{tag}>', re.IGNORECASE)
    in_style = False
    in_script = False
    pos = 0
    while pos < len(html):
        lower_slice = html[pos:pos + 20].lower()
        if lower_slice.startswith('<style'):
            in_style = True
            pos = html.find('>', pos)
            if pos == -1:
                return None
            pos += 1
            continue
        if lower_slice.startswith('<script'):
            in_script = True
            pos = html.find('>', pos)
            if pos == -1:
                return None
            pos += 1
            continue
        if in_style:
            end = html.find('</style>', pos)
            if end == -1:
                return None
            in_style = False
            pos = end + len('</style>')
            continue
        if in_script:
            end = html.find('</script>', pos)
            if end == -1:
                return None
            in_script = False
            pos = end + len('</script>')
            continue
        match = pattern.search(html, pos)
        if not match:
            return None
        return match.start()
    return None


def soup_to_html_document(soup, original_html: str) -> str:
    rendered = str(soup)
    original_lower = (original_html or '').lower()
    if original_lower.startswith('<!doctype') and not rendered.lower().startswith('<!doctype'):
        return '<!DOCTYPE html>\n' + rendered
    return rendered


def decode_uploaded_html_bytes(data: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'utf-8', 'latin-1'):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='ignore')
