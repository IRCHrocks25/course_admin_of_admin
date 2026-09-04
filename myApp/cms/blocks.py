"""Curated block palette: let a tenant add/remove/reorder/duplicate agency-
curated sections on their landing page, layered on top of the existing
annotate/edit/render pipeline without changing any of it.

Design goal: a tenant's *existing*, already-annotated landing page (template
HTML + saved content) is never rewritten by this module. Block instances live
in one new, additive spot — ``content['_blocks']`` — and get assembled into a
single dedicated container (``[data-cms-blocks-region]``) that is inserted
into the template once, idempotently, the first time it's needed. A tenant
who never touches "Add block" sees zero change: no block region is rendered
with content, and the only difference on disk is one empty, invisible
``<div>`` added to their stored template HTML the next time it's loaded.

Everything downstream of assembly reuses the *existing*, unmodified
``parser.build_schema`` / ``renderer.merge_with_defaults`` / ``renderer.
render_site`` — a block instance becomes an ordinary ``data-section`` /
``data-edit`` element once assembled, so every existing field type, the
richtext sanitizer, the preview bridge, and the live-editing bridge all just
work with no special-casing.
"""
from __future__ import annotations

import copy
import secrets

from bs4 import BeautifulSoup

from .block_library import BLOCK_LIBRARY
from .html_utils import soup_to_html_document
from .parser import build_block_schema

# Hard cap on how many extra blocks one tenant page may have. Mirrors the
# spirit of Locked CMS's MAX_BLOCKS_PER_PAGE — an abuse/perf guard, not a
# design constraint a real tenant should ever hit.
MAX_BLOCKS = 40

# "container" is the one block type with special handling below: it starts
# empty and holds its own list of child block instances (one level of
# nesting only — a container's children can never themselves be containers).
# This is the "start with a blank section, then add blocks into it" flow —
# a deliberately small slice of Locked CMS's full nested row/column system
# (see block_library.py's docstring for why that full system isn't ported).
CONTAINER_TYPE = "container"
MAX_CHILDREN = 20

_CATALOG_CACHE: dict[str, dict] | None = None


def get_catalog() -> dict[str, dict]:
    """Key -> {key, label, icon, category, schema, html}. Cached in-process;
    the palette is code (BLOCK_LIBRARY), not tenant data, so it never needs
    invalidating within a running process."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    catalog: dict[str, dict] = {}
    for key, html_source in BLOCK_LIBRARY.items():
        schema = build_block_schema(html_source or "")
        catalog[key] = {
            "key": key,
            "label": schema.get("label") or key.replace("_", " ").title(),
            "icon": schema.get("icon") or "layout",
            "category": schema.get("category") or "General",
            "schema": schema,
            "html": html_source,
        }
    _CATALOG_CACHE = catalog
    return catalog


def palette() -> list[dict]:
    """Editor-facing palette: no HTML, just what the "Add block" picker needs."""
    return [
        {
            "key": entry["key"],
            "label": entry["label"],
            "icon": entry["icon"],
            "category": entry["category"],
            "field_count": len((entry["schema"] or {}).get("fields") or []),
        }
        for entry in get_catalog().values()
    ]


def new_instance_id() -> str:
    """A fresh, collision-resistant block-instance id. Doubles as the
    instance's `data-section` id once assembled, so it must never collide
    with a tenant's own hand-authored section ids or another instance."""
    return "blk_" + secrets.token_hex(4)


def get_blocks(content: dict | None) -> list[dict]:
    blocks = (content or {}).get("_blocks")
    return blocks if isinstance(blocks, list) else []


#: Matches the Add-A-Section width picker. maxWidth is applied as an inline
#: style on the promoted instance wrapper (see _build_block_instance) so a
#: tenant can pick how wide a new section sits on the page, the same choice
#: Locked CMS offers before a section is added.
SECTION_WIDTHS = {
    "full": None,  # no max-width override — block renders at its own natural width
    "wide": "1200px",
    "medium": "960px",
    "small": "720px",
}


def add_block(content: dict, block_key: str, width: str | None = None) -> str:
    """Append a new instance of ``block_key`` to ``content['_blocks']``
    (mutates ``content`` in place) and return the new instance id. ``width``
    is one of SECTION_WIDTHS's keys (optional; unknown/omitted values are
    just ignored, never fatal — this is a cosmetic default, not something
    that should ever block adding a section)."""
    catalog = get_catalog()
    if block_key not in catalog:
        raise ValueError(f'Unknown block type "{block_key}".')
    blocks = get_blocks(content)
    if len(blocks) >= MAX_BLOCKS:
        raise ValueError(f"This page already has the maximum of {MAX_BLOCKS} extra sections.")
    instance = {"id": new_instance_id(), "type": block_key, "fields": {}}
    max_width = SECTION_WIDTHS.get(width or "")
    if max_width:
        instance["style"] = {"maxWidth": max_width}
    blocks = blocks + [instance]
    content["_blocks"] = blocks
    return instance["id"]


def remove_block(content: dict, instance_id: str) -> bool:
    """Remove one instance. Returns False if it wasn't found (already
    removed, stale id) rather than raising — callers treat that as a no-op."""
    blocks = get_blocks(content)
    kept = [b for b in blocks if b.get("id") != instance_id]
    content["_blocks"] = kept
    return len(kept) != len(blocks)


def _clone_instance(instance: dict) -> dict:
    """Deep-clone one instance with a fresh id (and, recursively, fresh ids
    for every child of a container) so a duplicated section never shares a
    data-section id — or therefore field values — with its original."""
    clone = {
        "id": new_instance_id(),
        "type": instance.get("type"),
        "fields": copy.deepcopy(instance.get("fields") or {}),
    }
    if instance.get("style"):
        clone["style"] = copy.deepcopy(instance["style"])
    if instance.get("type") == CONTAINER_TYPE:
        clone["children"] = [_clone_instance(c) for c in (instance.get("children") or [])]
    return clone


def duplicate_block(content: dict, instance_id: str) -> str | None:
    """Clone one instance (fresh id, same field values, children cloned too
    if it's a container) right after the original. Returns the new instance
    id, or None if not found."""
    blocks = get_blocks(content)
    for i, b in enumerate(blocks):
        if b.get("id") != instance_id:
            continue
        if len(blocks) >= MAX_BLOCKS:
            raise ValueError(f"This page already has the maximum of {MAX_BLOCKS} extra sections.")
        clone = _clone_instance(b)
        new_blocks = blocks[: i + 1] + [clone] + blocks[i + 1 :]
        content["_blocks"] = new_blocks
        return clone["id"]
    return None


def _find_top_level(content: dict, instance_id: str) -> dict | None:
    for b in get_blocks(content):
        if b.get("id") == instance_id:
            return b
    return None


def add_child_block(content: dict, parent_id: str, block_key: str) -> str:
    """Add a block inside a container instance — the "then show them they
    can add blocks there" half of the blank-section flow. Raises ValueError
    for an unknown block key, a missing/non-container parent, a full
    container, or an attempt to nest a container inside a container (only
    one level of nesting is supported)."""
    if block_key == CONTAINER_TYPE:
        raise ValueError("A blank section can't contain another blank section.")
    catalog = get_catalog()
    if block_key not in catalog:
        raise ValueError(f'Unknown block type "{block_key}".')
    parent = _find_top_level(content, parent_id)
    if parent is None or parent.get("type") != CONTAINER_TYPE:
        raise ValueError("Section not found.")
    children = parent.setdefault("children", [])
    if len(children) >= MAX_CHILDREN:
        raise ValueError(f"This section already has the maximum of {MAX_CHILDREN} blocks.")
    child = {"id": new_instance_id(), "type": block_key, "fields": {}}
    children.append(child)
    return child["id"]


def remove_child_block(content: dict, parent_id: str, child_id: str) -> bool:
    parent = _find_top_level(content, parent_id)
    if parent is None:
        return False
    children = parent.get("children") or []
    kept = [c for c in children if c.get("id") != child_id]
    parent["children"] = kept
    return len(kept) != len(children)


def duplicate_child_block(content: dict, parent_id: str, child_id: str) -> str | None:
    parent = _find_top_level(content, parent_id)
    if parent is None:
        return None
    children = parent.get("children") or []
    for i, c in enumerate(children):
        if c.get("id") != child_id:
            continue
        if len(children) >= MAX_CHILDREN:
            raise ValueError(f"This section already has the maximum of {MAX_CHILDREN} blocks.")
        clone = _clone_instance(c)
        children[i + 1 : i + 1] = [clone]
        parent["children"] = children
        return clone["id"]
    return None


def reorder_child_blocks(content: dict, parent_id: str, ordered_ids: list[str]) -> None:
    parent = _find_top_level(content, parent_id)
    if parent is None:
        return
    children = parent.get("children") or []
    by_id = {c.get("id"): c for c in children}
    new_order = [by_id[i] for i in ordered_ids if i in by_id]
    seen = {c.get("id") for c in new_order}
    new_order.extend(c for c in children if c.get("id") not in seen)
    parent["children"] = new_order


def set_block_width(content: dict, instance_id: str, width: str | None) -> bool:
    """Change an existing instance's Add-A-Section width choice (the
    Properties panel's Styles-tab equivalent of the width picker shown when
    the block was first added). Returns False if the instance isn't found.
    ``width`` of None/unknown clears the override back to natural width."""
    blocks = get_blocks(content)
    for b in blocks:
        if b.get("id") != instance_id:
            continue
        max_width = SECTION_WIDTHS.get(width or "")
        if max_width:
            b["style"] = {"maxWidth": max_width}
        else:
            b.pop("style", None)
        content["_blocks"] = blocks
        return True
    return False


def reorder_blocks(content: dict, ordered_ids: list[str]) -> None:
    """Reorder ``_blocks`` to match ``ordered_ids``. Unknown ids in the list
    are ignored; any existing block not mentioned is appended at the end
    (rather than silently dropped) so a stale/partial client-side order can
    never lose data."""
    blocks = get_blocks(content)
    by_id = {b.get("id"): b for b in blocks}
    new_order = [by_id[i] for i in ordered_ids if i in by_id]
    seen = {b.get("id") for b in new_order}
    new_order.extend(b for b in blocks if b.get("id") not in seen)
    content["_blocks"] = new_order


def _build_block_instance(instance: dict, catalog: dict[str, dict], preview: bool = False):
    """Return a detached BeautifulSoup element for one block instance, ready
    to append into the blocks region, or None when its block type is
    unknown (e.g. a block was removed from BLOCK_LIBRARY after a tenant used
    it — degrade by dropping that one instance, not the whole page).

    A "container" instance additionally assembles its own children (one
    level of nesting) into its inner data-cms-children-region div, exactly
    like assemble_blocks does for the page-level region — recursion just
    works because a child instance has the same {id, type, fields, style}
    shape as any top-level one. When preview is True and a container has no
    children yet, a clickable "+ Add Section" button is added so the tenant
    can fill it in from the canvas; it's never added on the public page
    render (preview=False), so an empty container a tenant hasn't filled in
    yet is simply invisible there rather than showing an editor control."""
    inst_id = str(instance.get("id") or "").strip()
    btype = catalog.get(instance.get("type"))
    if not inst_id or not btype:
        return None
    frag = BeautifulSoup(btype.get("html") or "", "lxml")
    # data-block is Locked CMS's own library-authoring marker; data-section
    # is accepted too (see parser.build_block_schema for why both exist).
    wrapper = frag.find(attrs={"data-block": True}) or frag.find(attrs={"data-section": True})
    if wrapper is None:
        return None
    key = (wrapper.get("data-block") or wrapper.get("data-section") or "").strip()
    if wrapper.has_attr("data-block"):
        del wrapper["data-block"]
    # Promote the fragment to a real page section: instance id becomes the
    # data-section id, so the existing classic parser/renderer treat it like
    # any other section with zero special-casing.
    wrapper["data-section"] = inst_id
    wrapper["data-cms-block-instance"] = "1"
    wrapper["data-cms-block-type"] = key

    # Optional per-instance style overrides (currently just the Add-A-Section
    # width choice). Additive to whatever inline style the block already
    # carries — never replaces it.
    max_width = ((instance.get("style") or {}).get("maxWidth") or "").strip()
    if max_width:
        style = (wrapper.get("style") or "").rstrip()
        if style and not style.endswith(";"):
            style += ";"
        style += f"max-width:{max_width};margin-left:auto;margin-right:auto;"
        wrapper["style"] = style
    # Rewrite every field id from the block-relative "key.field" to the
    # per-instance "instanceId.field" so N copies of the same block never
    # share a value. data-label/data-icon/data-group stay untouched, so the
    # existing classic parser still picks up a friendly label/icon/group for
    # this instance with zero changes to parser.build_schema.
    for field_el in wrapper.find_all(attrs={"data-edit": True}):
        fid = (field_el.get("data-edit") or "").strip()
        if "." not in fid:
            continue
        section_part, field_part = fid.split(".", 1)
        if section_part != key:
            continue
        field_el["data-edit"] = f"{inst_id}.{field_part}"

    if key == CONTAINER_TYPE:
        region = wrapper.find(attrs={"data-cms-children-region": True})
        if region is not None:
            children = instance.get("children") or []
            for child in children:
                if (child.get("type") or "") == CONTAINER_TYPE:
                    continue  # one level of nesting only
                child_wrapper = _build_block_instance(child, catalog, preview=preview)
                if child_wrapper is not None:
                    region.append(child_wrapper)
            if not children and preview:
                placeholder = frag.new_tag("div")
                placeholder["data-cms-empty-container"] = "1"
                placeholder["style"] = (
                    "border:1.5px dashed #c6cfe2;border-radius:10px;padding:36px 16px;"
                    "text-align:center;"
                )
                btn = frag.new_tag("button")
                btn["type"] = "button"
                btn["data-cms-add-inside"] = inst_id
                btn["style"] = (
                    "display:inline-flex;align-items:center;justify-content:center;"
                    "gap:6px;padding:10px 18px;border-radius:8px;border:0;"
                    "background:#2563eb;color:#ffffff;font-size:13px;font-weight:600;"
                    "cursor:pointer;font-family:inherit;line-height:1;"
                    "box-shadow:0 1px 2px rgba(15,23,42,.12);"
                )
                btn.string = "+ Add Section"
                placeholder.append(btn)
                region.append(placeholder)

    return wrapper.extract()


def ensure_blocks_region(template_html: str) -> str:
    """Idempotently make sure ``template_html`` has exactly one blocks
    region container. Returns ``template_html`` unchanged if one already
    exists. Never touches anything else in the document — this is the one
    guarantee that makes the feature safe to turn on for tenants who already
    have a saved, working landing page."""
    if not template_html:
        return template_html
    if "data-cms-blocks-region" in template_html:
        return template_html
    soup = BeautifulSoup(template_html, "lxml")
    region = soup.new_tag("div")
    region["data-cms-blocks-region"] = "1"
    footer = soup.find(attrs={"data-section": "footer"}) or soup.find("footer")
    if footer is not None:
        footer.insert_before(region)
    else:
        host = soup.body or soup
        host.append(region)
    return soup_to_html_document(soup, template_html)


def assemble_blocks(template_html: str, content: dict | None, preview: bool = False) -> str:
    """Return template_html with the blocks region (created if missing)
    populated by every instance in content['_blocks'], in order. Unknown
    block types are skipped, not fatal. Result is plain annotated HTML —
    the caller renders it with the ordinary, unmodified build_schema /
    merge_with_defaults / render_site pipeline. ``preview`` is forwarded to
    each block instance so an empty container shows its "+ Add Section"
    button only in the editor, never on the public page."""
    shell_html = ensure_blocks_region(template_html)
    instances = get_blocks(content)
    if not instances:
        return shell_html
    catalog = get_catalog()
    soup = BeautifulSoup(shell_html, "lxml")
    region = soup.find(attrs={"data-cms-blocks-region": True})
    if region is None:
        return shell_html
    region.clear()
    for instance in instances:
        wrapper = _build_block_instance(instance, catalog, preview=preview)
        if wrapper is not None:
            region.append(wrapper)
    return soup_to_html_document(soup, template_html)


def _flatten_instances(blocks: list[dict]):
    """Yield (instance, parent_id_or_None) for every top-level instance and
    every child of a container instance (exactly one level deep — a
    container's children can't themselves be containers, so this never
    needs to recurse further)."""
    for b in blocks:
        yield b, None
        if b.get("type") == CONTAINER_TYPE:
            for c in b.get("children") or []:
                yield c, b.get("id")


def build_schema_with_blocks(template_html: str, content: dict | None) -> dict:
    """Same shape as parser.build_schema(), plus one synthetic section per
    block instance — top-level AND every child inside a container — flagged
    is_block/block_type/block_width (and is_container/child_count for a
    container, parent_id for one of its children) so the editor UI can show
    the right controls on the right sections. Block instance fields, labels,
    icons and grouping all come for free from the existing classic parser,
    because assemble_blocks() turns every instance (nested or not) into a
    completely ordinary data-section/data-edit element before parsing."""
    from .parser import build_schema

    # Always assemble with preview=True here: this is schema-building for
    # the editor, so an empty container's "+ Add Section" button should
    # exist in the parsed structure the editor UI works from. It carries
    # no data-edit fields, so it never becomes a fake form field.
    assembled_html = assemble_blocks(template_html, content, preview=True)
    schema = build_schema(assembled_html)

    blocks = get_blocks(content)
    width_by_max = {v: k for k, v in SECTION_WIDTHS.items() if v}
    block_types: dict[str, str] = {}
    block_widths: dict[str, str] = {}
    parent_of: dict[str, str] = {}
    child_counts: dict[str, int] = {}
    for inst, parent_id in _flatten_instances(blocks):
        iid = inst.get("id")
        if not iid:
            continue
        block_types[iid] = inst.get("type")
        block_widths[iid] = width_by_max.get((inst.get("style") or {}).get("maxWidth"), "full")
        if parent_id:
            parent_of[iid] = parent_id
        if inst.get("type") == CONTAINER_TYPE:
            child_counts[iid] = len(inst.get("children") or [])

    for section in schema.get("sections") or []:
        sid = section.get("id")
        if sid in block_types:
            section["is_block"] = True
            section["block_type"] = block_types[sid]
            section["block_width"] = block_widths.get(sid, "full")
            if sid in parent_of:
                section["parent_id"] = parent_of[sid]
            if block_types[sid] == CONTAINER_TYPE:
                section["is_container"] = True
                section["child_count"] = child_counts.get(sid, 0)
    return schema


def render_with_blocks(
    template_html: str,
    content: dict | None,
    *,
    preview: bool = False,
    site_settings: dict | None = None,
) -> str:
    """Drop-in replacement for the old `build_schema(template_html)` +
    `merge_with_defaults(content, schema['defaults'])` + `render_site(...)`
    call sites, now block-aware. A tenant with no `_blocks` renders byte-
    identical to before (assemble_blocks is a no-op past inserting the one
    empty region container)."""
    from .parser import build_schema
    from .renderer import merge_with_defaults, render_site

    assembled_html = assemble_blocks(template_html, content, preview=preview)
    schema = build_schema(assembled_html)

    flat_content = {k: v for k, v in (content or {}).items() if k != "_blocks"}
    for instance, _parent_id in _flatten_instances(get_blocks(content)):
        inst_id = instance.get("id")
        if inst_id:
            flat_content[inst_id] = instance.get("fields") or {}

    merged = merge_with_defaults(flat_content, schema.get("defaults"))
    return render_site(assembled_html, merged, preview=preview, site_settings=site_settings)
