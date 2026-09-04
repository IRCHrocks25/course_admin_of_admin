"""Build editor schema from annotated CMS HTML."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

SECTION_ICONS = {
    'nav': 'menu', 'header': 'layout', 'footer': 'layout', 'hero': 'sparkles',
    'features': 'grid', 'pricing': 'credit-card', 'testimonials': 'message',
    'cta': 'megaphone', 'landing': 'layout',
}


def _parse_brand_defaults(soup) -> dict:
    brand = {}
    style_tag = soup.find('style', attrs={'data-tokens': True}) or soup.find('style')
    if not style_tag or not style_tag.string:
        return brand
    for match in re.finditer(r'--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);', style_tag.string):
        brand[match.group(1).replace('-', '_')] = match.group(2).strip()
    return brand


def parse_select_options(element) -> list[dict]:
    """``data-options="Label1=value1;Label2=value2"`` -> [{label, value}, ...]."""
    raw = element.get('data-options') or ''
    options = []
    for pair in raw.split(';'):
        pair = pair.strip()
        if not pair or '=' not in pair:
            continue
        label, value = pair.split('=', 1)
        options.append({'label': label.strip(), 'value': value.strip()})
    return options


def _select_style_prop(element) -> str | None:
    """``data-apply="style:border-top"`` (or a CSS var like ``style:--gcols``)
    -> the property name to read/write in the element's inline style. None
    for a non-style apply target (e.g. bare ``class``, not currently used by
    any ported block but accepted for forward-compatibility)."""
    apply_target = (element.get('data-apply') or '').strip()
    if apply_target.startswith('style:'):
        return apply_target.split(':', 1)[1].strip()
    return None


def _default_for_element(element, field_type: str) -> str:
    if field_type == 'image':
        return (element.get('src') or '').strip()
    if field_type == 'link':
        return (element.get('href') or '').strip()
    if field_type == 'color':
        style = element.get('style') or ''
        for prop in ('color', 'background-color'):
            match = re.search(rf'{prop}\s*:\s*([^;]+)', style, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ''
    if field_type == 'video':
        source = element.find('source')
        if source and source.get('src'):
            return source.get('src')
        return (element.get('src') or '').strip()
    if field_type == 'richtext':
        return element.decode_contents().strip()
    if field_type == 'select':
        prop = _select_style_prop(element)
        if prop:
            style = element.get('style') or ''
            match = re.search(rf'{re.escape(prop)}\s*:\s*([^;]+)', style, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return (element.get('data-default') or '').strip()
    if field_type == 'embed':
        return (element.get('src') or '').strip()
    if field_type == 'code':
        # Raw HTML the tenant fully controls, rendered unsanitized on their
        # own page — an explicit opt-in power block, same trust level as the
        # existing "Use custom HTML (advanced)" landing mode.
        return element.decode_contents().strip()
    return element.get_text(' ', strip=True)


def _augment_select_field(entry: dict, element) -> None:
    if entry.get('type') == 'select':
        entry['options'] = parse_select_options(element)
        entry['apply'] = (element.get('data-apply') or '').strip()


def build_schema(html: str) -> dict:
    soup = BeautifulSoup(html or '', 'lxml')
    sections_map: dict[str, dict] = {}
    defaults: dict[str, dict] = {}
    link_targets = []

    for section_el in soup.select('[data-section]'):
        section_id = section_el.get('data-section') or 'landing'
        if section_id not in sections_map:
            sections_map[section_id] = {
                'id': section_id,
                'label': section_el.get('data-label') or section_id.replace('_', ' ').title(),
                'icon': SECTION_ICONS.get(section_id, 'layout'),
                # data-group is the classic (hand-authored) attribute; ported
                # Locked CMS blocks use data-category instead (see
                # block_library.py) — accepted here too so a promoted block
                # instance groups itself sensibly in the editor sidebar
                # without every block needing both attributes.
                'group': section_el.get('data-group') or section_el.get('data-category') or 'Home',
                'fields': [],
            }
            defaults[section_id] = {}

        for element in section_el.select('[data-edit]'):
            edit_key = element.get('data-edit') or ''
            if '.' not in edit_key:
                continue
            sec, field = edit_key.split('.', 1)
            if sec != section_id:
                continue
            field_type = element.get('data-type') or 'text'
            default_value = _default_for_element(element, field_type)
            defaults[section_id][field] = default_value
            field_entry = {
                'id': edit_key,
                'label': element.get('data-label') or field.replace('_', ' ').title(),
                'type': field_type,
                'default': default_value,
            }
            _augment_select_field(field_entry, element)
            sections_map[section_id]['fields'].append(field_entry)
            if field_type == 'link' and default_value.startswith('#'):
                link_targets.append({'value': default_value, 'label': default_value.lstrip('#').title()})

    brand_defaults = _parse_brand_defaults(soup)
    if brand_defaults:
        sections_map['brand'] = {
            'id': 'brand',
            'label': 'Brand colors',
            'icon': 'palette',
            'group': 'Theme',
            'fields': [
                {
                    'id': f'brand.{key}',
                    'label': key.replace('_', ' ').title(),
                    'type': 'color',
                    'default': value,
                }
                for key, value in brand_defaults.items()
            ],
        }
        defaults['brand'] = brand_defaults

    unique_links = []
    seen = set()
    for item in link_targets:
        if item['value'] in seen:
            continue
        seen.add(item['value'])
        unique_links.append(item)

    return {
        'sections': list(sections_map.values()),
        'defaults': defaults,
        'link_targets': unique_links,
    }


def build_block_schema(html: str) -> dict:
    """Parse a single annotated block fragment (one data-section wrapper plus
    its data-edit fields) into an insertable block's schema.

    Field ids are stored *relative* to the block (e.g. "quote", not
    "testimonial.quote") so the same block type can be inserted many times on
    one page; `myApp/cms/blocks.py` rewrites data-edit to "<instanceId>.
    <field>" per instance before this fragment is ever merged into a real
    page, so build_schema() (above) never has to know blocks exist.
    """
    empty = {'key': '', 'label': '', 'icon': 'layout', 'category': 'General', 'fields': [], 'defaults': {}}
    if not html or not html.strip():
        return empty

    soup = BeautifulSoup(html, 'lxml')
    # data-block is the library-authoring marker (matches Locked CMS's own
    # convention so its curated block fragments can be pasted in unchanged);
    # data-section is accepted too since that's what a hand-authored block
    # fragment in this file mostly uses.
    wrapper = soup.find(attrs={'data-block': True}) or soup.find(attrs={'data-section': True})
    if wrapper is None:
        return empty

    key = (wrapper.get('data-block') or wrapper.get('data-section') or '').strip()
    fields: list[dict] = []
    defaults: dict[str, str] = {}

    for element in wrapper.select('[data-edit]'):
        edit_key = element.get('data-edit') or ''
        if '.' not in edit_key:
            continue
        section_part, field_part = edit_key.split('.', 1)
        if section_part != key:
            continue
        field_type = element.get('data-type') or 'text'
        default_value = _default_for_element(element, field_type)
        field_entry = {
            'id': field_part,
            'label': element.get('data-label') or field_part.replace('_', ' ').title(),
            'type': field_type,
            'default': default_value,
        }
        _augment_select_field(field_entry, element)
        fields.append(field_entry)
        defaults[field_part] = default_value

    return {
        'key': key,
        'label': wrapper.get('data-label') or key.replace('_', ' ').title(),
        'icon': wrapper.get('data-icon') or SECTION_ICONS.get(key, 'layout'),
        'category': wrapper.get('data-category') or wrapper.get('data-group') or 'General',
        'fields': fields,
        'defaults': defaults,
    }
