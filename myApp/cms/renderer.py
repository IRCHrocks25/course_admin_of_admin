"""Merge CMS content JSON into annotated HTML templates."""
from __future__ import annotations

import copy
import re

from bs4 import BeautifulSoup, NavigableString

from .html_utils import soup_to_html_document
from .parser import _default_for_element

# Keep in sync with sanitizeRteHtml() in cms_landing_editor.html: templates carry
# arbitrary design markup (classes, inline styles, svg icons), so richtext values
# must keep it too — strip only script-capable tags and attributes.
_RICHTEXT_STRIP_TAGS = ('script', 'style', 'iframe', 'object', 'embed')


def _sanitize_richtext_fragment(value: str) -> BeautifulSoup:
    # html.parser keeps the value a bare fragment; lxml would wrap it in
    # <html><body><p>…, injecting a block <p> into inline contexts.
    fragment = BeautifulSoup(value or '', 'html.parser')
    for tag in fragment.find_all(_RICHTEXT_STRIP_TAGS):
        tag.decompose()
    for tag in fragment.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith('on'):
                del tag[attr]
            elif attr.lower() in ('href', 'src', 'xlink:href') and re.match(
                r'\s*javascript:', str(tag[attr]), re.IGNORECASE
            ):
                del tag[attr]
    return fragment


def merge_with_defaults(content: dict | None, defaults: dict | None) -> dict:
    content = copy.deepcopy(content or {})
    defaults = defaults or {}
    merged = copy.deepcopy(defaults)
    for section_id, fields in content.items():
        if str(section_id).startswith('_'):
            merged[section_id] = fields
            continue
        if not isinstance(fields, dict):
            continue
        merged.setdefault(section_id, {})
        merged[section_id].update(fields)
    for key, value in content.items():
        if str(key).startswith('_'):
            merged[key] = value
    return merged


def _apply_brand_tokens(soup, brand: dict):
    style_tag = soup.find('style', attrs={'data-tokens': True}) or soup.find('style')
    if not style_tag or not style_tag.string or not brand:
        return
    css = style_tag.string
    for key, value in brand.items():
        css_var = key.replace('_', '-')
        # Replacement callable: token values often start with digits ("0 10px…"),
        # which would corrupt a "\1{value}" template into a bad group reference.
        css = re.sub(
            rf'(--{re.escape(css_var)}\s*:\s*)[^;]+(;)',
            lambda m, v=str(value): m.group(1) + v + m.group(2),
            css,
            count=1,
        )
    style_tag.string = css


def _set_text_preserving_children(element, value: str):
    """Replace an element's text while keeping child elements (e.g. icon <svg>s)."""
    text_nodes = [child for child in element.children if isinstance(child, NavigableString)]
    has_element_children = any(getattr(child, 'name', None) for child in element.children)
    if not has_element_children:
        element.clear()
        element.append(value)
        return
    replaced = False
    for node in text_nodes:
        if not replaced and node.strip():
            node.replace_with(value)
            replaced = True
        elif node.strip():
            node.extract()
    if not replaced:
        element.insert(0, value)


def _apply_field(element, field_type: str, value: str):
    if value is None:
        return
    if field_type == 'text':
        _set_text_preserving_children(element, value)
    elif field_type == 'richtext':
        fragment = _sanitize_richtext_fragment(value)
        element.clear()
        for child in list(fragment.children):
            element.append(child.extract())
    elif field_type == 'image':
        element['src'] = value
        for attr in ('srcset', 'data-src', 'data-lazy-src'):
            if element.has_attr(attr):
                del element[attr]
    elif field_type == 'link':
        element['href'] = value
    elif field_type == 'color':
        style = element.get('style') or ''
        if 'background' in (element.get('data-label') or '').lower():
            style = re.sub(r'background-color\s*:\s*[^;]+;?', '', style)
            style += f'background-color:{value};'
        else:
            style = re.sub(r'color\s*:\s*[^;]+;?', '', style)
            style += f'color:{value};'
        element['style'] = style.strip()
    elif field_type == 'video':
        source = element.find('source')
        if source is not None:
            source['src'] = value
        else:
            element['src'] = value
    elif field_type == 'select':
        from .parser import _select_style_prop
        prop = _select_style_prop(element)
        if prop:
            style = element.get('style') or ''
            style = re.sub(rf'{re.escape(prop)}\s*:\s*[^;]+;?', '', style, flags=re.IGNORECASE).strip()
            if style and not style.endswith(';'):
                style += ';'
            style += f'{prop}:{value};'
            element['style'] = style
    elif field_type == 'embed':
        element['src'] = value
    elif field_type == 'code':
        # Unsanitized on purpose — see parser._default_for_element's note on
        # the 'code' type. The tenant is editing their own page; this is the
        # same trust boundary as the existing "custom HTML" landing mode.
        fragment = BeautifulSoup(value or '', 'html.parser')
        element.clear()
        for child in list(fragment.children):
            element.append(child.extract())


def _apply_hidden_sections(soup, hidden_sections, *, preview: bool):
    if not hidden_sections:
        return
    for section_id in hidden_sections:
        for el in soup.select(f'[data-section="{section_id}"]'):
            if preview:
                style = el.get('style') or ''
                if 'opacity:0.35' not in style:
                    el['style'] = (style + ';opacity:0.35;pointer-events:none;').strip(';')
            else:
                style = el.get('style') or ''
                el['style'] = (style + ';display:none!important;').strip(';')


PREVIEW_BRIDGE_JS = r"""
(function () {
  'use strict';
  var MODE = 'edit'; // edit | annotate | browse
  var ANNOTATABLE = ['h1','h2','h3','h4','h5','h6','p','li','span','strong','em','small','label','figcaption','img','a','button','blockquote'];
  var selectedEl = null;

  var style = document.createElement('style');
  style.textContent = [
    '[data-cms-hover]{outline:2px dashed rgba(59,130,246,.95)!important;outline-offset:2px!important;cursor:pointer!important;}',
    '[data-cms-selected]{outline:2px solid #2563eb!important;outline-offset:2px!important;}',
    '[data-cms-annotate-hover]{outline:2px dashed rgba(217,119,6,.95)!important;outline-offset:2px!important;cursor:crosshair!important;background-color:rgba(251,191,36,.08)!important;}',
    '@keyframes cmsFlash{0%{outline-color:#2563eb;box-shadow:0 0 0 6px rgba(37,99,235,.35);}100%{box-shadow:0 0 0 0 rgba(37,99,235,0);}}',
    '[data-cms-flash]{outline:2px solid #2563eb!important;outline-offset:2px!important;animation:cmsFlash 1s ease-out 2;}',
    '#__cms_chip{position:fixed;z-index:2147483647;background:#2563eb;color:#fff;font:600 11px/1 -apple-system,"Segoe UI",Roboto,sans-serif;padding:4px 8px;border-radius:5px;pointer-events:none;white-space:nowrap;box-shadow:0 2px 10px rgba(0,0,0,.4);display:none;}',
    '#__cms_chip.annotate{background:#b45309;}',
    '[data-cms-section-selected]{outline:2px solid #2563eb!important;outline-offset:4px!important;border-radius:8px!important;}',
    '#__cms_section_chip{position:fixed;z-index:2147483646;background:#2563eb;color:#fff;font:600 11px/1 -apple-system,"Segoe UI",Roboto,sans-serif;padding:4px 9px;border-radius:5px 5px 5px 0;pointer-events:none;white-space:nowrap;box-shadow:0 2px 10px rgba(0,0,0,.35);display:none;}',
    '#__cms_section_bar{position:fixed;z-index:2147483646;display:none;gap:2px;background:#0f172a;border-radius:8px;padding:3px;box-shadow:0 4px 14px rgba(0,0,0,.35);}',
    '#__cms_section_bar button{width:24px;height:24px;border:0;border-radius:5px;background:transparent;color:#e5e7eb;font-size:13px;line-height:1;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;}',
    '#__cms_section_bar button:hover{background:rgba(255,255,255,.15);}',
    '[data-cms-add-inside]:hover{background:#1d4ed8!important;}'
  ].join('\n');
  document.head.appendChild(style);

  var chip = document.createElement('div');
  chip.id = '__cms_chip';
  document.body.appendChild(chip);

  function post(msg) { try { parent.postMessage(msg, '*'); } catch (e) {} }

  function closestEdit(el) {
    while (el && el.nodeType === 1) {
      if (el.hasAttribute && el.hasAttribute('data-edit')) return el;
      el = el.parentElement;
    }
    return null;
  }

  function closestSection(el) {
    while (el && el.nodeType === 1) {
      if (el.hasAttribute && el.hasAttribute('data-section')) return el.getAttribute('data-section');
      el = el.parentElement;
    }
    return '';
  }

  function isAnnotatable(el) {
    if (!el || el.nodeType !== 1) return false;
    var tag = el.tagName.toLowerCase();
    if (ANNOTATABLE.indexOf(tag) === -1) return false;
    if (el.hasAttribute('data-edit')) return false;
    if (closestEdit(el.parentElement)) return false;
    if (el.id === '__cms_chip') return false;
    if (el.closest && el.closest('#__cms_section_bar, #__cms_section_chip, [data-cms-empty-container]')) return false;
    if (tag !== 'img' && (el.textContent || '').trim().length < 1) return false;
    return true;
  }

  function cssPath(el) {
    var parts = [];
    while (el && el.nodeType === 1 && el.tagName.toLowerCase() !== 'html') {
      var tag = el.tagName.toLowerCase();
      if (tag === 'body') { parts.unshift('body'); break; }
      var index = 1;
      var sib = el.previousElementSibling;
      while (sib) {
        if (sib.tagName === el.tagName) index += 1;
        sib = sib.previousElementSibling;
      }
      parts.unshift(tag + ':nth-of-type(' + index + ')');
      el = el.parentElement;
    }
    return parts.join(' > ');
  }

  function showChip(el, text, annotate) {
    var rect = el.getBoundingClientRect();
    chip.textContent = text;
    chip.className = annotate ? 'annotate' : '';
    chip.style.display = 'block';
    var top = rect.top - 26;
    if (top < 4) top = rect.bottom + 6;
    chip.style.top = top + 'px';
    chip.style.left = Math.max(4, rect.left) + 'px';
  }

  function hideChip() { chip.style.display = 'none'; }

  function clearHover() {
    document.querySelectorAll('[data-cms-hover]').forEach(function (n) { n.removeAttribute('data-cms-hover'); });
    document.querySelectorAll('[data-cms-annotate-hover]').forEach(function (n) { n.removeAttribute('data-cms-annotate-hover'); });
    hideChip();
  }

  function selectElement(el) {
    if (selectedEl) selectedEl.removeAttribute('data-cms-selected');
    selectedEl = el;
    if (el) el.setAttribute('data-cms-selected', '1');
  }

  // ---- Section-level selection: the on-canvas outline + floating
  // move/duplicate/remove toolbar that mirrors the Layers panel + Properties
  // panel selection. sectionMeta is filled in by the parent (label + whether
  // the section is one of our block instances, which is the only kind that
  // supports move/duplicate/remove).
  var sectionMeta = {};
  var selectedSectionEl = null;
  var sectionChip = null;
  var sectionBar = null;

  function ensureSectionUi() {
    if (sectionChip) return;
    sectionChip = document.createElement('div');
    sectionChip.id = '__cms_section_chip';
    document.body.appendChild(sectionChip);
    sectionBar = document.createElement('div');
    sectionBar.id = '__cms_section_bar';
    document.body.appendChild(sectionBar);
  }

  function clearSectionSelection() {
    if (selectedSectionEl) selectedSectionEl.removeAttribute('data-cms-section-selected');
    selectedSectionEl = null;
    if (sectionChip) sectionChip.style.display = 'none';
    if (sectionBar) sectionBar.style.display = 'none';
  }

  function positionSectionUi() {
    if (!selectedSectionEl) return;
    var rect = selectedSectionEl.getBoundingClientRect();
    var top = rect.top - 26;
    if (top < 4) top = rect.top + 6;
    sectionChip.style.top = top + 'px';
    sectionChip.style.left = Math.max(4, rect.left) + 'px';
    if (sectionBar.style.display !== 'none') {
      var barTop = rect.top - 34;
      if (barTop < 4) barTop = rect.top + 6;
      sectionBar.style.top = barTop + 'px';
      sectionBar.style.left = Math.max(4, rect.right - 108) + 'px';
    }
  }

  function applySectionSelection(sectionId) {
    ensureSectionUi();
    clearSectionSelection();
    if (!sectionId) return;
    var el = document.querySelector('[data-section="' + sectionId.replace(/"/g, '\\"') + '"]');
    if (!el) return;
    selectedSectionEl = el;
    el.setAttribute('data-cms-section-selected', '1');
    var meta = sectionMeta[sectionId] || {};
    sectionChip.textContent = meta.label || sectionId;
    sectionChip.style.display = 'block';
    sectionBar.innerHTML = '';
    if (meta.isBlock) {
      [['↑', 'move-up'], ['↓', 'move-down'], ['⎘', 'duplicate'], ['×', 'remove']].forEach(function (pair) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = pair[0];
        btn.title = pair[1];
        btn.addEventListener('click', function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          post({ type: 'cms-block-action', action: pair[1], sectionId: sectionId });
        });
        sectionBar.appendChild(btn);
      });
      sectionBar.style.display = 'flex';
    } else {
      sectionBar.style.display = 'none';
    }
    positionSectionUi();
  }

  function selectSection(sectionId, focusFieldId) {
    applySectionSelection(sectionId);
    post({ type: 'cms-section-selected', sectionId: sectionId, focusFieldId: focusFieldId || null });
  }

  window.addEventListener('scroll', function () { positionSectionUi(); }, true);
  window.addEventListener('resize', positionSectionUi);

  function findAnnotatable(start) {
    var cur = start;
    while (cur && cur.nodeType === 1 && !isAnnotatable(cur)) cur = cur.parentElement;
    return (cur && isAnnotatable(cur)) ? cur : null;
  }

  // Edit and Annotate modes share one interaction model: annotated elements
  // select their field; anything else editable offers one-click annotation.
  document.addEventListener('mouseover', function (ev) {
    if (MODE === 'browse') return;
    if (ev.target.closest && ev.target.closest('#__cms_section_bar, #__cms_section_chip, [data-cms-empty-container]')) return;
    clearHover();
    var editEl = closestEdit(ev.target);
    if (editEl) {
      editEl.setAttribute('data-cms-hover', '1');
      showChip(editEl, editEl.getAttribute('data-label') || editEl.getAttribute('data-edit'), false);
      return;
    }
    var target = findAnnotatable(ev.target);
    if (target) {
      target.setAttribute('data-cms-annotate-hover', '1');
      showChip(target, 'Click to make editable: <' + target.tagName.toLowerCase() + '>', true);
    }
  }, true);

  document.addEventListener('mouseout', function () {
    if (MODE !== 'browse') clearHover();
  }, true);

  document.addEventListener('click', function (ev) {
    if (MODE === 'browse') return;
    // Our own on-canvas toolbar (move/duplicate/remove) lives outside the
    // page's data-section/data-edit markup, appended straight to <body>.
    // Without this guard the capture-phase listener below swallows every
    // click here before the toolbar's own button handlers ever run, and the
    // generic "anything with text is annotatable" logic further down treats
    // a plain <button> as something to offer up for annotation.
    if (ev.target.closest && ev.target.closest('#__cms_section_bar, #__cms_section_chip')) return;
    var addInside = ev.target.closest && ev.target.closest('[data-cms-add-inside]');
    if (addInside) {
      ev.preventDefault();
      ev.stopPropagation();
      var parentId = addInside.getAttribute('data-cms-add-inside') || closestSection(addInside);
      post({ type: 'cms-add-inside', parentId: parentId });
      if (parentId) selectSection(parentId, null);
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();
    var editEl = closestEdit(ev.target);
    if (editEl) {
      selectElement(editEl);
      var fieldId = editEl.getAttribute('data-edit');
      post({ type: 'cms-element-selected', fieldId: fieldId });
      var editSection = closestSection(editEl);
      if (editSection) selectSection(editSection, fieldId);
      return;
    }
    var target = findAnnotatable(ev.target);
    if (!target) {
      if (MODE === 'edit') {
        var bareSection = closestSection(ev.target);
        if (bareSection) selectSection(bareSection, null);
      }
      return;
    }
    var tag = target.tagName.toLowerCase();
    var suggestedType = 'text';
    if (tag === 'img') suggestedType = 'image';
    else if (tag === 'a') suggestedType = 'link';
    else if (target.children.length > 0) suggestedType = 'richtext';
    var snippet = tag === 'img'
      ? (target.getAttribute('alt') || target.getAttribute('src') || '').slice(0, 80)
      : (target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    post({
      type: 'cms-annotate-request',
      path: cssPath(target),
      tag: tag,
      snippet: snippet,
      suggestedType: suggestedType,
      sectionId: closestSection(target)
    });
  }, true);

  // Block form submits / keyboard nav side-effects while editing
  document.addEventListener('submit', function (ev) {
    if (MODE !== 'browse') { ev.preventDefault(); ev.stopPropagation(); }
  }, true);

  function applyFieldUpdate(fieldId, fieldType, value, fieldLabel) {
    var nodes = document.querySelectorAll('[data-edit="' + fieldId.replace(/"/g, '\\"') + '"]');
    nodes.forEach(function (el) {
      if (fieldType === 'image') {
        el.setAttribute('src', value);
        el.removeAttribute('srcset');
      } else if (fieldType === 'link') {
        el.setAttribute('href', value);
      } else if (fieldType === 'video') {
        var source = el.querySelector('source');
        if (source) { source.setAttribute('src', value); try { el.load(); } catch (e) {} }
        else el.setAttribute('src', value);
      } else if (fieldType === 'color') {
        var label = (fieldLabel || el.getAttribute('data-label') || '').toLowerCase();
        el.style[label.indexOf('background') !== -1 ? 'backgroundColor' : 'color'] = value;
      } else if (fieldType === 'richtext') {
        el.innerHTML = value;
      } else {
        // Preserve child elements (icon svgs etc.) — replace only text nodes.
        if (el.children.length === 0) {
          el.textContent = value;
        } else {
          var replaced = false;
          var nodes = Array.prototype.slice.call(el.childNodes);
          nodes.forEach(function (node) {
            if (node.nodeType !== 3) return;
            if (!replaced && node.nodeValue && node.nodeValue.trim()) {
              node.nodeValue = value;
              replaced = true;
            } else if (node.nodeValue && node.nodeValue.trim()) {
              node.nodeValue = '';
            }
          });
          if (!replaced) el.insertBefore(document.createTextNode(value), el.firstChild);
        }
      }
    });
  }

  window.addEventListener('message', function (event) {
    var data = event.data || {};
    switch (data.type) {
      case 'cms-mode':
        MODE = data.mode || 'edit';
        clearHover();
        if (MODE === 'browse') { selectElement(null); clearSectionSelection(); }
        break;
      case 'cms-section-meta':
        sectionMeta = data.sections || {};
        break;
      case 'cms-select-section':
        applySectionSelection(data.sectionId);
        break;
      case 'cms-field-focus': {
        var el = document.querySelector('[data-edit="' + String(data.fieldId).replace(/"/g, '\\"') + '"]');
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          selectElement(el);
          el.removeAttribute('data-cms-flash');
          void el.offsetWidth;
          el.setAttribute('data-cms-flash', '1');
          setTimeout(function () { el.removeAttribute('data-cms-flash'); }, 2200);
        }
        break;
      }
      case 'cms-field-update':
        applyFieldUpdate(String(data.fieldId), data.fieldType || 'text', data.value, data.fieldLabel);
        break;
      case 'cms-brand-update':
        document.documentElement.style.setProperty('--' + String(data.cssVar), String(data.value));
        break;
      case 'cms-section-visibility': {
        document.querySelectorAll('[data-section="' + String(data.sectionId).replace(/"/g, '\\"') + '"]').forEach(function (el) {
          if (data.hidden) {
            el.style.opacity = '0.3';
            el.style.filter = 'grayscale(1)';
          } else {
            el.style.opacity = '';
            el.style.filter = '';
            el.style.pointerEvents = '';
          }
        });
        break;
      }
    }
  });

  post({ type: 'cms-bridge-ready' });
})();
"""


def _inject_preview_bridge(soup):
    if soup.find(id='cms-preview-bridge'):
        return
    script = soup.new_tag('script', id='cms-preview-bridge')
    script.string = PREVIEW_BRIDGE_JS
    body = soup.body or soup
    body.append(script)


def render_site(html: str, content: dict | None, *, preview: bool = False, site_settings: dict | None = None) -> str:
    original_html = html or ''
    soup = BeautifulSoup(original_html, 'lxml')
    content = content or {}

    _apply_brand_tokens(soup, content.get('brand') or {})
    hidden_sections = content.get('_hidden') or []

    for element in soup.select('[data-edit]'):
        edit_key = element.get('data-edit') or ''
        if '.' not in edit_key:
            continue
        section_id, field_key = edit_key.split('.', 1)
        section_content = content.get(section_id) or {}
        if field_key not in section_content:
            continue
        field_type = element.get('data-type') or 'text'
        value = section_content[field_key]
        # The template markup already carries the default value. Re-applying an
        # unchanged value is lossy (clears icon children, sanitizes rich text),
        # so only rewrite the element when the value actually differs.
        try:
            current = _default_for_element(element, field_type)
        except Exception:
            current = None
        if current is not None and str(value).strip() == str(current).strip():
            continue
        _apply_field(element, field_type, value)

    _apply_hidden_sections(soup, hidden_sections, preview=preview)

    if site_settings:
        title = (site_settings.get('title') or '').strip()
        if title:
            title_tag = soup.find('title')
            if title_tag:
                title_tag.string = title
            else:
                head = soup.head or soup.new_tag('head')
                if not soup.head:
                    soup.html.insert(0, head) if soup.html else None
                head.append(soup.new_tag('title'))
                head.title.string = title
        description = (site_settings.get('description') or '').strip()
        if description:
            meta = soup.find('meta', attrs={'name': 'description'})
            if meta:
                meta['content'] = description
            elif soup.head:
                meta_tag = soup.new_tag('meta')
                meta_tag['name'] = 'description'
                meta_tag['content'] = description
                soup.head.append(meta_tag)

    if preview:
        _inject_preview_bridge(soup)

    return soup_to_html_document(soup, original_html)
