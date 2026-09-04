"""Curated block palette for tenant landing pages.

Two sources, merged into one dict of ``{key: annotated_html_fragment}``:

1. ``_PORTED_FROM_LOCKED_CMS`` — the actual primitive palette from Locked
   CMS's ``core/management/commands/seed_builder_blocks.py`` (the
   "BUILDER_BLOCKS" library), ported here verbatim (same field ids, same
   defaults, same inline styles) so this is genuinely the same library, not a
   reinterpretation of it. Two things from that source were deliberately
   NOT ported:
     - "section" / "section-tight" / "row-1".."row-6": Locked CMS's layout
       primitives, each a container with nested `data-region` column slots
       you drop other blocks into. This module's block engine (blocks.py)
       only supports one flat, top-level list of blocks — no nested
       drag-and-drop columns yet. Porting these here would add UI that
       silently doesn't do anything (an empty column with nothing to drop
       into it). Real nested-region support is a separate, bigger follow-up.
     - "form" (a GHL lead-form embed, field type "ghl-embed"): Courseforge's
       landing CMS has no GHL-embed field type or GHL-forms wiring at all, so
       there's nothing for it to bind to yet.
2. ``BLOCK_LIBRARY_CUSTOM`` — a few complete, ready-to-use sections (not raw
   primitives) built for this product specifically: a single big testimonial,
   one FAQ item, a dark CTA banner, a team member card. These don't exist in
   Locked CMS's primitive library (which gives you a "headline" + "paragraph"
   + "button" to compose one yourself); kept because they're genuinely useful
   out of the box and don't overlap the ported set.

Every field type the ported blocks use — text, richtext, image, link, color,
video, select, embed, code — is now handled by `parser.py` / `renderer.py` /
the editor's field controls. `select` fields (e.g. divider style, gallery
column count) render as a dropdown in the editor and apply to an inline CSS
property via `data-apply="style:<prop>"`; `code` fields are raw HTML the
tenant controls, rendered unsanitized on their own page (same trust level as
the existing "custom HTML" landing mode) — a deliberate opt-in power block,
not a default one.

To add another block: add one more `key: html_source` entry to either dict
below. Nothing else needs to change — `blocks.get_catalog()` derives each
block's schema straight from its HTML via `parser.build_block_schema()`.
"""
from __future__ import annotations

# --- helpers (mirrors Locked CMS's seed_builder_blocks.py exactly) -------- #

_INNER_OPEN = (
    '<div style="max-width:1100px;margin-left:auto;margin-right:auto;'
    'padding-left:clamp(16px,4vw,40px);padding-right:clamp(16px,4vw,40px);">'
)
_INNER_CLOSE = "</div>"


def _leaf(key: str, label: str, icon: str, category: str, inner: str, pad: str = "8px 0") -> str:
    return (
        f'<div data-block="{key}" data-label="{label}" data-icon="{icon}" '
        f'data-category="{category}" style="padding:{pad};">'
        f'{_INNER_OPEN}{inner}{_INNER_CLOSE}</div>'
    )


def _hug(key: str, label: str, icon: str, category: str, inner: str, pad: str = "8px 0") -> str:
    """Leaf that hugs its own width (buttons/links) instead of a 1100px wrap."""
    return (
        f'<div data-block="{key}" data-label="{label}" data-icon="{icon}" '
        f'data-category="{category}" '
        f'style="padding:{pad};display:block;width:100%;text-align:center;">'
        f'{inner}</div>'
    )


def _slots(fmt: str, n: int, start: int = 1) -> str:
    """Repeat an HTML fragment ``fmt`` (which uses ``{i}``) n times."""
    return "".join(fmt.format(i=i) for i in range(start, start + n))


# --- leaf content, verbatim from Locked CMS's BUILDER_BLOCKS -------------- #

_DIVIDER = (
    '<hr data-edit="divider.style" data-type="select" data-label="Divider style" '
    'data-apply="style:border-top" data-default="2px solid #cbd5e1" '
    'data-options="Thin=1px solid #e5e7eb;Normal=2px solid #cbd5e1;'
    'Thick=4px solid #94a3b8;Dashed=2px dashed #cbd5e1" '
    'style="border:0;border-top:2px solid #cbd5e1;margin:0;">'
)

_SPACER = (
    '<div data-edit="spacer.height" data-type="select" data-label="Height" '
    'data-apply="style:height" data-default="48px" '
    'data-options="Small=24px;Medium=48px;Large=96px;Extra large=160px" '
    'style="height:48px;"></div>'
)

_ICON = (
    '<div data-edit="icon.glyph" data-type="text" data-label="Icon (emoji / character)" '
    'style="font-size:48px;line-height:1;text-align:center;">⭐</div>'
)

_VIDEO = (
    '<video data-edit="video.src" data-type="video" data-label="Video" controls '
    'playsinline style="max-width:100%;height:auto;border-radius:10px;display:block;'
    'margin:auto;"><source src="" type="video/mp4"></video>'
)

_SLIDER = (
    '<div style="display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;'
    'padding-bottom:10px;">'
    + _slots(
        '<img data-edit="slider.img{i}" data-type="image" data-label="Slide {i}" '
        'src="https://placehold.co/640x400?text=Slide+{i}" alt="" '
        'style="flex:0 0 78%;scroll-snap-align:center;border-radius:10px;'
        'object-fit:cover;">', 4)
    + "</div>"
)

_GALLERY = (
    '<div data-edit="gallery.columns" data-type="select" data-label="Columns" '
    'data-apply="style:--gcols" data-default="repeat(3,minmax(0,1fr))" '
    'data-options="2 columns=repeat(2,minmax(0,1fr));3 columns=repeat(3,minmax(0,1fr));'
    '4 columns=repeat(4,minmax(0,1fr))" '
    'style="display:grid;grid-template-columns:var(--gcols,repeat(3,minmax(0,1fr)));'
    'gap:10px;">'
    + _slots(
        '<img data-edit="gallery.img{i}" data-type="image" data-label="Photo {i}" '
        'src="https://placehold.co/400x400?text={i}" alt="" '
        'style="width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:8px;">', 6)
    + "</div>"
)

_LOGOS = (
    '<div style="display:flex;flex-wrap:wrap;gap:32px;align-items:center;'
    'justify-content:center;">'
    + _slots(
        '<img data-edit="logos.logo{i}" data-type="image" data-label="Logo {i}" '
        'src="https://placehold.co/160x60?text=Logo+{i}" alt="" '
        'style="height:44px;width:auto;object-fit:contain;filter:grayscale(1);'
        'opacity:.7;">', 5)
    + "</div>"
)

_FAQ = _slots(
    '<details style="border-bottom:1px solid #e5e7eb;padding:14px 0;">'
    '<summary data-edit="faq.q{i}" data-type="text" data-label="Question {i}" '
    'style="font-weight:600;cursor:pointer;">Question {i}?</summary>'
    '<div data-edit="faq.a{i}" data-type="richtext" data-label="Answer {i}" '
    'style="margin-top:10px;color:#475569;line-height:1.6;">'
    '<p style="margin:0;">Answer to question {i}.</p></div></details>', 4)

_REVIEWS = (
    '<div data-edit="reviews.columns" data-type="select" data-label="Columns" '
    'data-apply="style:--rcols" data-default="repeat(3,minmax(0,1fr))" '
    'data-options="1 column=minmax(0,1fr);2 columns=repeat(2,minmax(0,1fr));'
    '3 columns=repeat(3,minmax(0,1fr));4 columns=repeat(4,minmax(0,1fr))" '
    'style="display:grid;grid-template-columns:var(--rcols,repeat(3,minmax(0,1fr)));'
    'gap:16px;">'
    + _slots(
        '<div style="border:1px solid #e5e7eb;border-radius:12px;padding:20px;">'
        '<div data-edit="reviews.r{i}Stars" data-type="text" data-label="Review {i} stars" '
        'style="color:#f59e0b;font-size:18px;">★★★★★</div>'
        '<p data-edit="reviews.r{i}Body" data-type="text" data-label="Review {i} text" '
        'style="margin:10px 0;color:#475569;line-height:1.6;">Great experience, '
        'highly recommend!</p>'
        '<div data-edit="reviews.r{i}Name" data-type="text" data-label="Review {i} name" '
        'style="font-weight:600;">Happy Client</div></div>', 3)
    + "</div>"
)

_COUNTER = (
    '<div data-edit="counter.columns" data-type="select" data-label="Columns" '
    'data-apply="style:--ccols" data-default="repeat(3,minmax(0,1fr))" '
    'data-options="2 columns=repeat(2,minmax(0,1fr));3 columns=repeat(3,minmax(0,1fr));'
    '4 columns=repeat(4,minmax(0,1fr))" '
    'style="display:grid;grid-template-columns:var(--ccols,repeat(3,minmax(0,1fr)));'
    'gap:16px;text-align:center;">'
    + _slots(
        '<div style="min-height:220px;padding:32px 16px;border-radius:12px;'
        'display:flex;flex-direction:column;justify-content:center;align-items:center;'
        'box-sizing:border-box;width:100%;background-size:cover;background-position:center;">'
        '<div data-edit="counter.n{i}Value" data-type="text" '
        'data-label="Stat {i} value" style="font-size:2.5rem;font-weight:800;'
        'color:#2563eb;">100+</div>'
        '<div data-edit="counter.n{i}Label" data-type="text" data-label="Stat {i} label" '
        'style="color:#64748b;">Metric {i}</div></div>', 3)
    + "</div>"
)

_PRICING = (
    '<div data-edit="pricing.columns" data-type="select" data-label="Columns" '
    'data-apply="style:--pcols" data-default="repeat(3,minmax(0,1fr))" '
    'data-options="2 columns=repeat(2,minmax(0,1fr));3 columns=repeat(3,minmax(0,1fr))" '
    'style="display:grid;grid-template-columns:var(--pcols,repeat(3,minmax(0,1fr)));'
    'gap:16px;">'
    + _slots(
        '<div style="border:1px solid #e5e7eb;border-radius:14px;padding:24px;'
        'text-align:center;">'
        '<div data-edit="pricing.p{i}Name" data-type="text" data-label="Plan {i} name" '
        'style="font-weight:700;font-size:1.2rem;">Plan {i}</div>'
        '<div data-edit="pricing.p{i}Price" data-type="text" data-label="Plan {i} price" '
        'style="font-size:2.2rem;font-weight:800;margin:8px 0;">$29</div>'
        '<div data-edit="pricing.p{i}Features" data-type="richtext" '
        'data-label="Plan {i} features" style="color:#475569;line-height:1.8;'
        'margin-bottom:16px;"><ul style="list-style:none;padding:0;margin:0;">'
        '<li>Feature one</li><li>Feature two</li><li>Feature three</li></ul></div>'
        '<a data-edit="pricing.p{i}Cta" data-type="link" data-label="Plan {i} button" '
        'href="#" style="display:inline-block;padding:10px 20px;background:#2563eb;'
        'color:#fff;border-radius:8px;text-decoration:none;font-weight:600;">'
        '<span data-edit="pricing.p{i}CtaLabel" data-type="text" '
        'data-label="Plan {i} button text">Choose</span></a></div>', 3)
    + "</div>"
)

_PROGRESS = (
    '<div data-edit="progress.label" data-type="text" data-label="Label" '
    'style="font-weight:600;margin-bottom:6px;">Skill</div>'
    '<div style="background:#e5e7eb;border-radius:999px;height:14px;overflow:hidden;">'
    '<div data-edit="progress.value" data-type="select" data-label="Progress" '
    'data-apply="style:width" data-default="70%" '
    'data-options="10%=10%;25%=25%;50%=50%;75%=75%;90%=90%;100%=100%" '
    'style="height:100%;width:70%;background:#2563eb;border-radius:999px;"></div></div>'
)

_FEATURE = (
    '<div data-edit="feature.side" data-type="select" data-label="Image position" '
    'data-apply="style:flex-direction" data-default="row" '
    'data-options="Image left=row;Image right=row-reverse" '
    'style="display:flex;gap:28px;align-items:center;flex-wrap:wrap;">'
    '<img data-edit="feature.image" data-type="image" data-label="Feature image" '
    'src="https://placehold.co/560x400?text=Feature" alt="" '
    'style="flex:1 1 280px;max-width:100%;border-radius:12px;object-fit:cover;">'
    '<div style="flex:1 1 280px;">'
    '<h3 data-edit="feature.title" data-type="text" data-label="Title" '
    'style="margin:0 0 10px;font-size:1.6rem;font-weight:700;">Feature title</h3>'
    '<div data-edit="feature.body" data-type="richtext" data-label="Body" '
    'style="color:#475569;line-height:1.7;margin-bottom:16px;"><p style="margin:0;">'
    'Describe the feature and why it matters to your visitor.</p></div>'
    '<a data-edit="feature.cta" data-type="link" data-label="Button" href="#" '
    'style="display:inline-block;padding:10px 20px;background:#2563eb;color:#fff;'
    'border-radius:8px;text-decoration:none;font-weight:600;">'
    '<span data-edit="feature.ctaLabel" data-type="text" data-label="Button text">'
    'Learn more</span></a></div></div>'
)

_SOCIAL_PLATFORMS = [
    ("facebook", "Facebook", "f"),
    ("instagram", "Instagram", "IG"),
    ("x", "X / Twitter", "X"),
    ("linkedin", "LinkedIn", "in"),
    ("youtube", "YouTube", "▶"),
]
_SOCIAL = (
    '<div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">'
    + "".join(
        '<a data-edit="social.' + p + '" data-type="link" data-label="' + lbl + ' URL" '
        'href="#" style="width:42px;height:42px;border-radius:50%;background:#0f172a;'
        'color:#fff;display:inline-flex;align-items:center;justify-content:center;'
        'text-decoration:none;font-weight:700;font-size:14px;">' + g + "</a>"
        for p, lbl, g in _SOCIAL_PLATFORMS
    )
    + "</div>"
)

_MAP = (
    '<iframe data-edit="map.src" data-type="embed" data-label="Map embed URL" '
    'src="https://www.google.com/maps?q=New+York&output=embed" '
    'style="width:100%;height:360px;border:0;border-radius:12px;" loading="lazy" '
    'referrerpolicy="no-referrer-when-downgrade"></iframe>'
)

_QR = (
    '<img data-edit="qr.src" data-type="embed" data-label="QR image URL" '
    'src="https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=https://example.com" '
    'alt="QR code" style="width:220px;height:220px;display:block;margin:auto;">'
)

_CODE = (
    '<div data-edit="code.html" data-type="code" data-label="HTML / embed code">'
    '<p style="margin:0;color:#94a3b8;text-align:center;">Your embedded content '
    'appears here.</p></div>'
)

# Self-contained countdown: an inline script scoped to its own parent node reads
# the (editable) target date text and updates the display every second. Scoped
# by document.currentScript.parentNode so multiple instances don't collide.
_COUNTDOWN = (
    '<div style="text-align:center;">'
    '<div data-edit="countdown.title" data-type="text" data-label="Title" '
    'style="font-size:1.1rem;color:#475569;margin-bottom:8px;">Offer ends in</div>'
    '<div class="cms-countdown" style="font-size:2.2rem;font-weight:800;">--</div>'
    '<div data-edit="countdown.target" data-type="text" '
    'data-label="Target date (YYYY-MM-DD HH:MM)" '
    'style="font-size:12px;color:#94a3b8;margin-top:6px;">2026-12-31 23:59</div>'
    "<script>(function(){var box=document.currentScript.parentNode;"
    "var out=box.querySelector('.cms-countdown');"
    "var tEl=box.querySelector('[data-edit$=\".target\"]');"
    "function tick(){var raw=((tEl&&tEl.textContent)||'').trim().replace(' ','T');"
    "var t=Date.parse(raw);if(isNaN(t)){out.textContent='--';return;}"
    "var d=Math.max(0,t-Date.now());var s=Math.floor(d/1000);"
    "var days=Math.floor(s/86400),h=Math.floor(s%86400/3600),"
    "m=Math.floor(s%3600/60),sec=s%60;"
    "out.textContent=days+'d '+h+'h '+m+'m '+sec+'s';}"
    "tick();setInterval(tick,1000);})();</script></div>"
)


_PORTED_FROM_LOCKED_CMS: dict[str, str] = {
    "headline": _leaf(
        "headline", "Headline", "heading", "Text",
        '<h2 data-edit="headline.text" data-type="text" data-label="Heading text" '
        'style="margin:0;font-size:2rem;line-height:1.2;font-weight:700;">'
        'Your headline</h2>',
    ),
    "subheadline": _leaf(
        "subheadline", "Sub-headline", "heading", "Text",
        '<h3 data-edit="subheadline.text" data-type="text" data-label="Sub-headline text" '
        'style="margin:0;font-size:1.35rem;line-height:1.3;font-weight:600;color:#334155;">'
        'A supporting sub-headline</h3>',
        pad="6px 0",
    ),
    "paragraph": _leaf(
        "paragraph", "Paragraph", "text", "Text",
        '<div data-edit="paragraph.body" data-type="richtext" data-label="Paragraph">'
        '<p style="margin:0;line-height:1.6;">Write a paragraph of copy here. '
        'You can make text <strong>bold</strong> or <em>italic</em>.</p></div>',
        pad="6px 0",
    ),
    "list": _leaf(
        "list", "Bullet list", "list", "Text",
        '<div data-edit="list.items" data-type="richtext" data-label="List items">'
        '<ul style="margin:0;padding-left:0;line-height:1.7;list-style-position:inside;">'
        '<li>First item</li><li>Second item</li><li>Third item</li></ul></div>',
        pad="6px 0",
    ),
    "richtext": _leaf(
        "richtext", "Rich text", "text", "Text",
        '<div data-edit="richtext.body" data-type="richtext" data-label="Rich text">'
        '<p style="margin:0;line-height:1.6;">Rich text supports <strong>bold</strong>, '
        '<em>italic</em>, links and lists.</p></div>',
        pad="6px 0",
    ),
    "image": _leaf(
        "image", "Image", "image", "Media",
        '<img data-edit="image.src" data-type="image" data-label="Image" '
        'src="https://placehold.co/800x450?text=Image" alt="" '
        'style="max-width:100%;height:auto;display:block;border-radius:8px;">',
    ),
    "button": _hug(
        "button", "Button", "link", "Elements",
        '<a data-edit="button.link" data-type="link" data-label="Button link" href="#" '
        'style="display:inline-flex;flex-direction:column;align-items:center;gap:2px;'
        'padding:12px 22px;background:#2563eb;color:#fff;border-radius:8px;'
        'text-decoration:none;font-weight:600;line-height:1.2;max-width:100%;">'
        '<span data-edit="button.label" data-type="text" data-label="Button text">'
        'Get Started</span>'
        '<span data-edit="button.subtext" data-type="text" data-label="Sub text" '
        'style="font-size:12px;font-weight:500;opacity:.85;"></span>'
        '</a>',
        pad="8px 0",
    ),
    "nav-link": (
        '<div data-block="nav-link" data-label="Text link" data-icon="link" '
        'data-category="Elements" style="display:inline-block;padding:2px 6px;">'
        '<a data-edit="navlink.text" data-type="text" data-label="Link text" '
        'href="/" style="color:inherit;text-decoration:none;font-weight:600;'
        'font-size:15px;line-height:1.2;padding:4px 2px;">Link</a></div>'
    ),
    "divider": _leaf("divider", "Divider", "minus", "Elements", _DIVIDER, pad="16px 0"),
    "spacer": _leaf("spacer", "Spacer", "move-vertical", "Elements", _SPACER, pad="0"),
    "icon": _leaf("icon", "Icon", "star", "Elements", _ICON),
    "video": _leaf("video", "Video", "video", "Media", _VIDEO),
    "slider": _leaf("slider", "Image Slider", "images", "Media", _SLIDER),
    "gallery": _leaf("gallery", "Photo Gallery", "grid", "Media", _GALLERY),
    "logos": _leaf("logos", "Logo Showcase", "building", "Media", _LOGOS),
    "faq": _leaf("faq", "FAQ (4 questions)", "help-circle", "Elements", _FAQ),
    "reviews": _leaf("reviews", "Reviews grid", "star", "Social proof", _REVIEWS),
    "counter": _leaf("counter", "Number Counter", "hash", "Social proof", _COUNTER),
    "pricing": _leaf("pricing", "Pricing Table", "table", "Elements", _PRICING),
    "progress": _leaf("progress", "Progress Bar", "bar-chart", "Elements", _PROGRESS),
    "feature": _leaf("feature", "Image Feature", "layout", "Elements", _FEATURE),
    "social": _leaf("social", "Social Icons", "share-2", "Social", _SOCIAL),
    "map": _leaf("map", "Map", "map-pin", "Embed", _MAP),
    "qr": _leaf("qr", "QR Code", "qr-code", "Embed", _QR),
    "code": _leaf("code", "Code / Embed", "code", "Embed", _CODE),
    "countdown": _leaf("countdown", "Countdown", "clock", "Countdown", _COUNTDOWN, pad="16px 0"),
}


# --- a few complete sections not in Locked CMS's primitive library -------- #

BLOCK_LIBRARY_CUSTOM: dict[str, str] = {
    "testimonial": """<section data-section="testimonial" data-label="Testimonial (single, large)" data-icon="message" data-group="Social proof" style="padding:56px 24px;background:#f8fafc;text-align:center;font-family:inherit;">
  <div style="max-width:640px;margin:0 auto;">
    <p data-edit="testimonial.quote" data-type="richtext" data-label="Quote" style="font-size:20px;line-height:1.6;color:#1f2937;font-style:italic;margin:0;">&ldquo;This program completely changed how our team works. Worth every peso.&rdquo;</p>
    <p data-edit="testimonial.author" data-type="text" data-label="Author name" style="margin:16px 0 0;font-weight:700;color:#111827;">Jane Dela Cruz</p>
    <p data-edit="testimonial.role" data-type="text" data-label="Author role" style="margin:2px 0 0;color:#6b7280;font-size:14px;">Operations Manager, Acme Co.</p>
  </div>
</section>""",
    "faq_item": """<section data-section="faq_item" data-label="FAQ item (single)" data-icon="help-circle" data-group="Elements" style="padding:24px;border-bottom:1px solid #e5e7eb;font-family:inherit;max-width:720px;margin:0 auto;">
  <h3 data-edit="faq_item.question" data-type="text" data-label="Question" style="margin:0 0 8px;font-size:17px;font-weight:700;color:#111827;">What's included in the program?</h3>
  <p data-edit="faq_item.answer" data-type="richtext" data-label="Answer" style="margin:0;color:#4b5563;line-height:1.6;">Everything you need to get started, including onboarding, materials, and ongoing support from our team.</p>
</section>""",
    "cta_banner": """<section data-section="cta_banner" data-label="CTA banner" data-icon="megaphone" data-group="Elements" style="padding:48px 24px;background:#111827;text-align:center;font-family:inherit;">
  <h2 data-edit="cta_banner.heading" data-type="text" data-label="Heading" style="margin:0 0 10px;font-size:26px;font-weight:800;color:#ffffff;">Ready to get started?</h2>
  <p data-edit="cta_banner.subheading" data-type="text" data-label="Subheading" style="margin:0 0 22px;color:#d1d5db;font-size:15px;">Join the next cohort before seats run out.</p>
  <a data-edit="cta_banner.button_label" data-type="text" data-label="Button label" href="#" style="display:inline-block;padding:13px 28px;border-radius:8px;background:#2563eb;color:#ffffff;font-weight:700;text-decoration:none;font-size:15px;">Enroll now</a>
</section>""",
    "team_member": """<section data-section="team_member" data-label="Team member" data-icon="user" data-group="Elements" style="padding:32px 24px;text-align:center;font-family:inherit;max-width:320px;margin:0 auto;">
  <img data-edit="team_member.photo" data-type="image" data-label="Photo" src="https://placehold.co/160x160?text=Photo" alt="" style="width:120px;height:120px;border-radius:50%;object-fit:cover;margin:0 auto 14px;display:block;">
  <div data-edit="team_member.name" data-type="text" data-label="Name" style="font-weight:700;color:#111827;font-size:16px;">Alex Santos</div>
  <div data-edit="team_member.title" data-type="text" data-label="Title" style="color:#6b7280;font-size:13px;margin-top:2px;">Lead Instructor</div>
</section>""",
}


# A single empty container a tenant can drop blocks into one at a time,
# instead of picking a pre-built section outright — the "start blank, then
# add blocks to it" flow. blocks.py gives this one type special handling
# (it's the only block with its own nested children list); everything else
# about it — how it's parsed, promoted, labeled, categorized — works through
# the exact same machinery as every other block above. It deliberately has
# zero data-edit fields of its own: `data-cms-children-region` is where
# child block instances get assembled in by blocks.py, not a field.
BLANK_SECTION_HTML = _leaf(
    "container", "Blank section", "square", "Layout",
    '<div data-cms-children-region="1"></div>',
    pad="24px 0",
)


BLOCK_LIBRARY: dict[str, str] = {
    **_PORTED_FROM_LOCKED_CMS,
    **BLOCK_LIBRARY_CUSTOM,
    "container": BLANK_SECTION_HTML,
}
