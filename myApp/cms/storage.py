"""Persist CMS template HTML and content on TenantConfig.features.custom_pages."""
from __future__ import annotations

from django.core.files.storage import default_storage

TEMPLATE_FILE_PREFIX = 'tenant_cms_templates'


def _custom_pages(config) -> dict:
    features = config.features or {}
    custom_pages = features.get('custom_pages')
    if not isinstance(custom_pages, dict):
        custom_pages = {}
    return custom_pages


def _template_file_path(tenant_id: int) -> str:
    return f'{TEMPLATE_FILE_PREFIX}/tenant_{tenant_id}_landing_cms.html'


def get_landing_cms_template_html(config, tenant_id: int) -> str:
    custom_pages = _custom_pages(config)
    inline = (custom_pages.get('landing_cms_template_html') or '').strip()
    if inline:
        return inline
    file_key = (custom_pages.get('landing_cms_template_file') or '').strip()
    if not file_key:
        file_key = _template_file_path(tenant_id)
    try:
        if default_storage.exists(file_key):
            with default_storage.open(file_key, 'r') as handle:
                return handle.read()
    except Exception:
        return ''
    return ''


def save_landing_cms_template_html(config, tenant_id: int, html: str) -> None:
    # Always store inline in the config JSON. File storage is unusable here:
    # default_storage may be Cloudinary's image backend, which rejects .html
    # payloads ("Invalid image file"). Imports are capped at 500KB, which JSON
    # columns handle comfortably.
    html = html or ''
    custom_pages = _custom_pages(config)
    old_file = (custom_pages.get('landing_cms_template_file') or '').strip()
    custom_pages['landing_cms_template_html'] = html
    custom_pages.pop('landing_cms_template_file', None)
    if old_file:
        try:
            default_storage.delete(old_file)
        except Exception:
            pass
    config.features = config.features or {}
    config.features['custom_pages'] = custom_pages


def get_landing_cms_content(config) -> dict:
    custom_pages = _custom_pages(config)
    content = custom_pages.get('landing_cms_content')
    return content if isinstance(content, dict) else {}


def save_landing_cms_content(config, content: dict) -> None:
    custom_pages = _custom_pages(config)
    custom_pages['landing_cms_content'] = content or {}
    config.features = config.features or {}
    config.features['custom_pages'] = custom_pages


def set_landing_cms_published(config, published: bool) -> None:
    custom_pages = _custom_pages(config)
    custom_pages['landing_cms_published'] = bool(published)
    config.features = config.features or {}
    config.features['custom_pages'] = custom_pages
