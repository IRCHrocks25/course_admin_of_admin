"""Load platform default CMS landing templates."""
from __future__ import annotations

from pathlib import Path

from django.template import Context, Template

from myApp.utils.branding import get_tenant_branding


def get_default_landing_cms_template(tenant=None) -> str:
    branding = get_tenant_branding(tenant) if tenant else {}
    template_path = Path(__file__).resolve().parent.parent / 'branding_templates' / 'default_landing_cms.html'
    raw = template_path.read_text(encoding='utf-8')
    return Template(raw).render(Context({'branding': branding}))
