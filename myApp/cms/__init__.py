"""Annotation-based CMS for tenant landing pages."""

from .annotator import auto_annotate_html
from .parser import build_schema
from .renderer import merge_with_defaults, render_site
from .storage import (
    get_landing_cms_content,
    get_landing_cms_template_html,
    save_landing_cms_content,
    save_landing_cms_template_html,
)

__all__ = [
    'auto_annotate_html',
    'build_schema',
    'merge_with_defaults',
    'render_site',
    'get_landing_cms_content',
    'get_landing_cms_template_html',
    'save_landing_cms_content',
    'save_landing_cms_template_html',
]
