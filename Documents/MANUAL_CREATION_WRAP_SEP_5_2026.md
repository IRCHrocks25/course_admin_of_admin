# Manual Creation wrap — 5 Sep 2026

Shipped a write-it-yourself path on **Create New Course**: fourth tab **Manual Creation**. Save-as-you-go so image/video uploads already have lesson IDs. Course Builder, Lesson Generator, and PDF import were left alone.

## Done today

1. **Manual Creation tab.** Title + optional short description + free/paid pricing creates a real `Course` and a default **Lessons** module. **Add lesson** creates a real approved lesson, then expands its card (previous cards collapse; toast + highlight). Course PDFs/workbooks attach through existing `CourseResource` + Iceberg.

2. **Custom “What you’ll learn”.** New `Lesson.what_youll_learn_heading` (default `What You'll Learn Today`). Body stays on `ai_full_description`. Student page uses the heading and hides the section when the body is empty. Migration `0069`.

3. **Notes editor reused, not copied.** Extracted the block editor (paragraph, header, list, quote, image, video / WebM) into `components/_notes_block_editor.html` + `static/js/notes_block_editor.js`. Manual lesson cards and the AI lesson page both mount the same factory.

4. **Done actually finishes.** First version saved silently and left the editor open. **Done** now shows a spinner, persists notes, closes to a preview, toasts **Lesson saved**, and turns the header control into **Edit**.

5. **View live course.** Footer button after create opens the student course page in a new tab. **Open course dashboard** sits next to it.

6. **Hero image.** Per-lesson upload on the card (JPG/PNG/WEBP → Iceberg, same helper as the AI lesson editor). Preview + remove. Shows above the lesson title when there is no hero video.

7. **Hero video.** Upload (WebM convert + Iceberg) or paste Vimeo / YouTube / Drive / file URL. Plays at the top of the student lesson page and replaces the hero image. Uploaded files use a native `<video>` player.

8. **Tests.** `myApp.tests.test_manual_creation` covers create course, add/save lesson, resources, heading/empty-body/video on the student page, tenant isolation, hero image, and hero video URL save/delete.

## How to use it

Dashboard → Courses → **Create New Course** → **Manual Creation**.

1. Title → Create course  
2. Add lesson → heading, body, hero image/video, **Create your lesson** notes  
3. Optional course resources  
4. **View live course**

Apply `0069` if a host has not: `python manage.py migrate`.

## Still open

- Refresh loses in-tab state (save-as-you-go writes the DB; reopen via course dashboard).
- No AI, quizzes, or exams on this tab (by design).
- Course-level cover/thumbnail is still not on this tab (lesson hero only).
- Per-lesson workbook URL stays on the existing lesson editor.
- Hard-refresh if **Done** or new fields look stale (`notes_block_editor.js` is static).

## One-liner

Added a Manual Creation tab that writes a real course and lessons as you go, with a reusable notes editor, custom What you’ll learn heading, hero image, hero video, and a View live course button.

---

# Landing Page Builder wrap — 4 Sep 2026

Shipped a full port + redesign of the tenant landing-page editor (Branding settings → Landing page editor). Courseforge's old "HTML → editable blocks" tool now looks and works like cms_platform's real editor, with a much bigger block library and a proper blank-section flow. Existing tenants' already-saved landing HTML was the hard constraint throughout — nothing here touches classic parsing/rendering, everything is additive.

## Done today

1. **Full block library ported from cms_platform.** 30 blocks total: 26 ported leaf blocks (headline, image, button, faq, reviews, counter, pricing, gallery, map, code, divider, video, slider, logos, and more) plus 4 custom ones (testimonial, faq_item, cta_banner, team_member). Three new field types added to support them: select, embed, code.

2. **Editor UI redesign to match cms_platform.** Replaced the old always-open accordion sidebar with cms's real layout: a Layers panel on the left, the live-preview canvas in the middle, and a selection-driven Properties panel on the right — General/Styles tabs, collapsible field rows, and on-canvas click-to-select with a floating move/duplicate/remove toolbar.

3. **Add-A-Section now starts blank, like cms's real flow.** Picking a width no longer drops in a pre-made content block — it creates an empty "blank section," and you add blocks into it afterward from that section's own Properties panel (a "+ Add block" button). One level of nesting only — a blank section can't hold another blank section — matching how far courseforge's flat block engine goes.

4. **Width picker + Styles tab.** Full / Wide / Medium / Small width option when adding a section, editable later from the Properties panel's Styles tab.

5. **Two real bugs found and fixed while building this.** A duplicated blank section used to share ids with its original's children (fixed with a proper recursive clone, so every nested child gets a fresh id). The on-canvas toolbar's move/duplicate/remove buttons were being swallowed by the page's own "click to annotate" listener — they silently did nothing, and hovering them showed a "click to make editable" tooltip — fixed by excluding the toolbar from that logic.

6. **Zero risk to existing tenants.** Byte-compat smoke tests confirm a tenant with no saved blocks renders identically before/after; verified through Django's real template engine plus py_compile / node --check directly on this machine.

## How to use it

Dashboard → Branding settings → Landing page editor.

1. **Add A Section** → Quick Add / Elements for ready-made blocks, or Sections for a blank one you build up yourself
2. Click any section on the canvas (or in Layers) to edit it in the Properties panel
3. A blank section shows **+ Add block** — click it to fill the section in
4. Move / duplicate / remove from the floating on-canvas toolbar or the Properties panel controls

## Still open

- Row/column multi-column layouts aren't available yet (cms's real layout primitives) — the Add-A-Section modal says so.
- Two levels of nesting (a section inside a section) is a deliberate non-goal, not a bug.
- GHL embed form block intentionally excluded, same as before.

## One-liner

Rebuilt courseforge's landing-page editor to look and work like cms_platform's — full block library, Layers/Properties panel UI, and a real blank-section flow — with zero risk to tenants' existing saved pages.
