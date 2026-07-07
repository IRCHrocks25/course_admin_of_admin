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
    return element.get_text(' ', strip=True)


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
                'group': section_el.get('data-group') or 'Home',
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
            sections_map[section_id]['fields'].append({
                'id': edit_key,
                'label': element.get('data-label') or field.replace('_', ' ').title(),
                'type': field_type,
                'default': default_value,
            })
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
