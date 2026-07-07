"""Auto-annotate HTML with data-edit attributes for the visual CMS."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

SKIP_TAGS = frozenset({
    'script', 'style', 'svg', 'noscript', 'iframe', 'video', 'audio', 'source',
})
EDITABLE_TAGS = frozenset({
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'span', 'strong', 'em',
    'small', 'label', 'figcaption', 'img', 'a',
})
NESTED_INLINE = frozenset({'span', 'strong', 'em'})
HERO_SELECTORS = ('.herobox', '.hero', '.hero-section', '.banner', '.jumbotron')
SECTION_ICONS = {
    'nav': 'menu', 'header': 'layout', 'footer': 'layout', 'hero': 'sparkles',
    'features': 'grid', 'pricing': 'credit-card', 'testimonials': 'message',
    'cta': 'megaphone', 'landing': 'layout',
}
MIN_EXISTING_EDITS = 5


def _count_existing_edits(soup) -> int:
    return len(soup.select('[data-edit]'))


def _section_label(section_id: str, element) -> str:
    if section_id in ('nav', 'header', 'footer'):
        return section_id.title()
    if section_id == 'hero':
        return 'Welcome banner'
    data_label = element.get('data-label')
    if data_label:
        return data_label
    return section_id.replace('_', ' ').title()


def _discover_sections(soup):
    sections = []
    seen = set()

    def add_section(element, section_id, group='Home'):
        if section_id in seen:
            return
        seen.add(section_id)
        element['data-section'] = section_id
        element['data-label'] = _section_label(section_id, element)
        element['data-group'] = group
        sections.append((section_id, element))

    for tag in ('nav', 'header', 'footer'):
        for el in soup.find_all(tag):
            add_section(el, tag)

    for idx, el in enumerate(soup.find_all('section')):
        sid = el.get('id') or el.get('class', [''])[0] if el.get('class') else f'section_{idx + 1}'
        sid = re.sub(r'[^a-zA-Z0-9_-]', '_', str(sid)).strip('_') or f'section_{idx + 1}'
        add_section(el, sid)

    for selector in HERO_SELECTORS:
        for el in soup.select(selector):
            if not el.get('data-section'):
                add_section(el, 'hero')

    if not sections:
        body = soup.body or soup
        add_section(body, 'landing')

    return sections


def _is_button_link(element) -> bool:
    classes = ' '.join(element.get('class') or []).lower()
    role = (element.get('role') or '').lower()
    return any(token in classes for token in ('btn', 'button', 'cta')) or role == 'button'


def _infer_field_type(element) -> str:
    tag = element.name.lower()
    if tag == 'img':
        return 'image'
    if tag == 'a':
        return 'text' if _is_button_link(element) else 'link'
    inner_html = element.decode_contents() if hasattr(element, 'decode_contents') else ''
    if tag in EDITABLE_TAGS and '<' in inner_html:
        return 'richtext'
    return 'text'


def _field_key_for_element(section_id: str, element, counters: dict) -> str:
    tag = element.name.lower()
    base_counters = counters.setdefault(section_id, {})
    if tag == 'h1' and 'title' not in base_counters.values():
        key = 'title'
    elif tag == 'h2' and 'heading' not in base_counters.values():
        key = 'heading'
    elif tag == 'p' and 'subtitle' not in base_counters.values():
        key = 'subtitle'
    elif tag == 'img' and 'image' not in base_counters.values():
        key = 'image'
    elif tag == 'a' and _is_button_link(element) and 'cta_primary' not in base_counters.values():
        key = 'cta_primary'
    else:
        count = sum(1 for k in base_counters if k.startswith(f'{tag}_')) + 1
        key = f'{tag}_{count}' if count > 1 or tag not in ('h1', 'h2', 'p', 'img', 'a') else tag
    base_counters[key] = key
    return key


def _default_value_for_element(element, field_type: str) -> str:
    if field_type == 'image':
        return (element.get('src') or '').strip()
    if field_type == 'link':
        return (element.get('href') or '').strip()
    if field_type == 'richtext':
        return element.decode_contents().strip()
    return element.get_text(' ', strip=True)


def _inside_existing_edit(element) -> bool:
    parent = element.parent
    while parent is not None and getattr(parent, 'name', None):
        if parent.has_attr('data-edit'):
            return True
        parent = parent.parent
    return False


def _parse_brand_tokens(soup):
    brand = {}
    style_tag = soup.find('style', attrs={'data-tokens': True})
    if not style_tag:
        style_tag = soup.find('style')
    if not style_tag or not style_tag.string:
        return brand
    for match in re.finditer(r'--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);', style_tag.string):
        brand[match.group(1).replace('-', '_')] = match.group(2).strip()
    return brand


def annotate_element(raw_html: str, css_path: str, *, label: str = '', field_type: str = ''):
    """Mark a single element (located by a structural CSS path) as editable.

    Returns (html, field_id, error). On failure html/field_id are None.
    """
    soup = BeautifulSoup(raw_html or '', 'lxml')
    try:
        element = soup.select_one(css_path or '')
    except Exception:
        element = None
    if element is None:
        return None, None, 'Could not locate that element in the template. Try clicking it again.'
    if element.has_attr('data-edit'):
        return str(soup), element['data-edit'], None

    section_id = None
    parent = element
    while parent is not None and getattr(parent, 'name', None):
        if parent.has_attr('data-section'):
            section_id = parent['data-section']
            break
        parent = parent.parent
    if not section_id:
        body = soup.body or soup
        section_id = body.get('data-section') or 'landing'
        body['data-section'] = section_id
        body['data-label'] = body.get('data-label') or 'Page'

    if field_type not in ('text', 'richtext', 'image', 'link', 'color', 'video'):
        field_type = _infer_field_type(element)

    base_key = re.sub(r'[^a-z0-9_]+', '_', (label or element.name).strip().lower()).strip('_') or element.name
    existing = {el.get('data-edit') for el in soup.select('[data-edit]')}
    key = base_key
    suffix = 2
    while f'{section_id}.{key}' in existing:
        key = f'{base_key}_{suffix}'
        suffix += 1

    field_id = f'{section_id}.{key}'
    element['data-edit'] = field_id
    element['data-type'] = field_type
    element['data-label'] = (label or key.replace('_', ' ').title()).strip()
    return str(soup), field_id, None


def remove_annotation(raw_html: str, field_id: str):
    """Remove the data-edit annotation for one field. Returns (html, error)."""
    soup = BeautifulSoup(raw_html or '', 'lxml')
    elements = soup.select(f'[data-edit="{field_id}"]') if field_id else []
    if not elements:
        return None, 'Field not found in the template.'
    for element in elements:
        for attr in ('data-edit', 'data-type', 'data-label'):
            if element.has_attr(attr):
                del element[attr]
    return str(soup), None


def auto_annotate_html(raw_html: str, *, force: bool = False) -> str:
    html = (raw_html or '').strip()
    if not html:
        return ''

    soup = BeautifulSoup(html, 'lxml')
    if not force and _count_existing_edits(soup) >= MIN_EXISTING_EDITS:
        return str(soup)

    sections = _discover_sections(soup)
    counters: dict[str, dict] = {}

    for section_id, section_el in sections:
        for element in section_el.find_all(True):
            tag = element.name.lower()
            if tag in SKIP_TAGS or tag not in EDITABLE_TAGS:
                continue
            if _inside_existing_edit(element):
                continue
            if tag in NESTED_INLINE:
                parent_tag = element.parent.name.lower() if element.parent and element.parent.name else ''
                if parent_tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'a'):
                    continue
            if tag != 'img':
                text = element.get_text(' ', strip=True)
                if len(text) < 2 and tag not in ('img', 'a'):
                    continue
            if tag == 'img' and not (element.get('src') or '').strip():
                continue

            field_key = _field_key_for_element(section_id, element, counters)
            field_type = _infer_field_type(element)
            element['data-edit'] = f'{section_id}.{field_key}'
            element['data-type'] = field_type
            element['data-label'] = element.get('data-label') or field_key.replace('_', ' ').title()

    # Brand color tokens
    brand = _parse_brand_tokens(soup)
    if brand:
        style_tag = soup.find('style', attrs={'data-tokens': True}) or soup.find('style')
        if style_tag is not None:
            style_tag['data-tokens'] = 'true'

    return str(soup)
