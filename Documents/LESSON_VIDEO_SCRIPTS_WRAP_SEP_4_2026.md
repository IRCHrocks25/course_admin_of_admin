# Lesson video scripts wrap — 4 Sep 2026

Shipped fire-and-forget ~5-minute lesson video scripts on course create (JSON + optional Google Doc). Course create does not wait. Verified locally.

Ops detail: `Documents/LESSON_VIDEO_SCRIPTS_AND_GDRIVE.md`.

## Done today

1. **Pipeline.** After each lesson’s notes are saved, a daemon thread calls OpenAI (`gpt-4o-mini`), stores `Lesson.video_script`, then uploads a shooting-table Doc if Drive is connected. Same hook on Course Builder, Lesson Generator, and append seed. Widget can say Complete! while scripts finish.

2. **Storage.** `Lesson.video_script` / `script_doc_id` / `script_doc_url`. Drive refresh token + folder ID on `PlatformConfig` (encrypted). App client ID/secret stay in `.env`.

3. **Drive connect.** Superadmin → Google Drive. CLI fallback: `python manage.py gdrive_oauth`. Local CLI connect succeeded; first Docs landed under `SOP Course Video Scripts / <course>/`.

4. **Create unblocked.** Postgres `NOT NULL` on `video_script` rejected new lessons. Migration `0068` made the three script fields nullable. Create works after migrate + restart.

5. **Notes win, not the title.** Lesson Generator with working title “How to make a caramel macchiato” and personal-development source wrote a coffee recipe. Notes and `ai_clean_title` were already correct. Script prompt now treats title/course as labels and uses `ai_clean_title`. Regenerated lesson 1604 — script is about personal development; Doc updated.

6. **Tests.** `myApp.tests.test_video_script` passing (flatten, prompt grounding, clean-title preference, spawn gate).

## Redirect URIs to add in Google Cloud

Add all of these on the Drive OAuth **Web** client (exact, trailing slash):

```
https://courseforge.katek-ai.com/superadmin/integrations/gdrive/callback/
http://127.0.0.1:8000/superadmin/integrations/gdrive/callback/
http://localhost:8000/superadmin/integrations/gdrive/callback/
http://localhost:8080/
http://127.0.0.1:8080/
```

Connect from [courseforge.katek-ai.com](https://courseforge.katek-ai.com/) or local `:8000`. Do not add the GHL `/leadconnector/callback` here.

## Still open

- Paste the URIs above so Superadmin **Connect** works in production (CLI already works locally).
- Testing-mode Google tokens expire after 7 days — reconnect weekly or new Docs fail while JSON still saves.
- Narration is often short of the 650–820 word target; subject is correct.
- No dashboard regenerate button — `python manage.py generate_lesson_scripts --lesson-id N --force`.
- PDF import, translations, and “Regenerate AI Content” do not spawn scripts.

## One-liner

Shipped per-lesson video scripts on course create, unblocked the NOT NULL create failure, connected Drive via CLI, and fixed scripts following leftover working titles instead of the finished notes.
