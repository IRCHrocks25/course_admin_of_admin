# PDF import and deploy wrap — 30 Aug 2026

## 1. Chapter 2 “duplicate” lessons (Liquid Gym 2)

The extra sidebar items were not a second PDF. The importer treated the **chapter cover page** as a lesson.

- `CHAPTER 2 — SAFETY, ENVIRONMENT, RISK MANAGEMENT` became lesson 1
- The wrapped title (`SAFETY, ENVIRONMENT… &`) became lesson 2
- Running headers glued onto real sections: `2.3 ENVIRONMENTAL SAFETY CHAPTER 2.3 ENVIRONMENTAL SAFETY` (same for 2.6)
- Opening that cover stub showed stacked titles, leftover fragments (`Management`, `& Emergency`, `Readiness`), and the empty block under **Finish Lesson**

**Parser fix (in code, covered by tests):**

- Chapter starts are named `Introduction`
- Cover-page title fragments are dropped
- `CHAPTER X.Y …` is stripped from section titles
- `test_chapter_cover_pages_do_not_become_extra_lessons` plus the rest of the PDF import suite: **31 tests, all passing**

A new import should not recreate those extras.

**Live cleanup on Liquid Gym 2 (course 117):**

- Deleted the cover-page stub
- Renamed the real first lessons to `Introduction`
- Cleaned `2.3` and `2.6` titles

Refresh Chapter 2 to see one Introduction, then `2.1`–`2.6`.

## 2. Production: `No module named 'django'`

That was not a missing Django pin. The `updated pdf upload` commit had checked in the **local macOS `.venv`** (~25k files). Railway reused it, skipped `pip install`, then ran `python manage.py migrate` with a bare Python.

**Shipped on `main`:** `d17d2c23`

- Removed `.venv`, `__pycache__`, and `db.sqlite3` from git
- Updated `.gitignore` so they cannot be committed again
- Pushed to origin

Railway should install from `requirements.txt` on the next successful build. Confirm the deploy log shows pip completing before migrate.

## 3. Already in place from this PDF-import work

These were already fixed and tested; they were the reason Liquid Gym 2 was re-imported:

| Area | Outcome |
| --- | --- |
| Figures | Woven by page/position; uploaded to Iceberg, not Cloudinary |
| Heading-only lessons (1.6, 3.6, 3.7) | Keep images that sit on the next page |
| Quizzes | Stop at the correct answer; `CONCLUSION - CHAPTER N` recognized |
| Extra Chapter 2 modules | Running headers and ranges like `33.5–35.5°C` no longer open a new chapter |
| Lists | Numbered questions stay 1, 2, 3, 4 instead of restarting |
| 3.4 “Test N” walls of text | Split as headings |
| Lesson width | Content uses the full center rail |

## Still true

- Re-importing onto an **existing** course still **adds** modules; it does not replace them
- Pages that are only vector art with no image xref can still come out empty
- The Railway deploy after `d17d2c23` needs a green build in the Railway UI to confirm production is back

The live site was not re-checked in a browser after the last title cleanup or the Railway push.
