# Lesson video scripts and Google Drive

Per-lesson ~5-minute video scripts are a fire-and-forget side effect of Course Builder / Lesson Generator (and of appending seed lessons). They do **not** block course creation. The progress widget can say Complete! while script threads are still finishing.

## What is generated

1. **Database** — `Lesson.video_script` (JSON) is saved first, even if Drive is down.
2. **Google Doc** — a shooting table in `SOP Course Video Scripts / <Course name> / <Lesson title> — Video Script`, if OAuth is connected.

The finished lesson notes (`content`, else `rough_notes`) are the only factual source. The working title and course name are labels only — if they name a different subject than the notes, the notes win. Quiz Q&A is excluded. The prompt uses `ai_clean_title` when present.

## Required environment

AI text (always needed for a script):

- `OPENAI_API_KEY`

Google OAuth **app** credentials (server env only):

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI` — optional exact callback if the public URL differs from the request host

Hardcoded in `myProject/settings.py`:

- `GENERATE_LESSON_SCRIPTS = True`
- `VIDEO_SCRIPT_MODEL = "gpt-4o-mini"`

The **refresh token** and **scripts folder ID** live in `PlatformConfig` (encrypted token). Connect from Superadmin — do not put `GOOGLE_OAUTH_REFRESH_TOKEN` in `.env` unless you need a temporary fallback.

## OAuth setup (Superadmin button)

1. Create a Google Cloud OAuth **Web application** client (Testing is fine).
2. Enable the Google Drive API.
3. Add this authorized redirect URI (must match exactly):

   `https://<your-host>/superadmin/integrations/gdrive/callback/`

   Local example: `http://127.0.0.1:8000/superadmin/integrations/gdrive/callback/`
4. Set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` on the server.
5. Create a Drive folder named `SOP Course Video Scripts` and copy its ID from the folder URL.
6. Sign in as a superuser → **Super Admin → Google Drive**:
   - Paste the folder ID and click **Save folder ID**
   - Click **Connect Google Drive**
7. Complete Google consent. The refresh token is stored encrypted in the database.

Writes use **OAuth as your Google user** (your quota). A Cloud OAuth app in Testing expires the refresh token after **7 days**. Click **Reconnect Google Drive** weekly or new Docs will fail while lesson JSON still saves.

Fallback CLI (writes the same DB row): `python manage.py gdrive_oauth`

## What triggers a script

| Action | Scripts? |
|--------|----------|
| Course Builder / Lesson Generator with AI on | Yes, per lesson |
| Append seed lessons | Yes, per new lesson |
| Create course with Generate with AI off | No |
| PDF import | No |
| Lesson editor “Regenerate AI Content” | No |
| Audio / hero-image backfill | No |
| Translations | No |

There is no dashboard “generate script” button. To regenerate:

```bash
python manage.py generate_lesson_scripts --lesson-id 42 --force
python manage.py generate_lesson_scripts --course my-course-slug
```

Or call `_run_generate_and_upload_script(lesson_id, course_name, folder_id)` from a Django shell.

## How to verify

1. Superadmin → Google Drive shows **Connected** and a scripts folder ID.
2. Create a small course (Lesson Generator, one lesson is enough).
3. Wait until the progress widget completes, then wait a short extra beat for the script thread.
4. In Django admin: the lesson has `video_script` JSON and, if Drive worked, a `script_doc_url` pointing at docs.google.com.
5. On Manage Lessons: a **Video script** link appears when the Doc URL is set.
6. In Drive: **SOP Course Video Scripts → \<course name\> → \<lesson title\> — Video Script**.
7. Open the Doc: shooting table (Time / Visual / VO / On-Screen) plus production notes.

## Failure behaviour

Script failures never fail the course.

| Situation | Lesson JSON | Google Doc | Course create |
|-----------|-------------|------------|----------------|
| OpenAI succeeds, Drive OK | Saved | Created / updated | Continues |
| OpenAI succeeds, Drive down or token expired | Saved | Missing or stale | Continues |
| No lesson body (`content` and `rough_notes` empty) | Skipped | None | Continues |
| Drive not configured | Saved if OpenAI ran | None | Continues |
| OpenAI script call fails | Not saved | None | Continues |

Logs to look for:

- `Video script for lesson '…' has N narration words` — generation ran (word count is a warning only).
- `[Background] Skipping video script for lesson N: no content or rough_notes.`
- `[Background] Drive upload failed for lesson …`
- `[Background] Drive scripts folder failed`
- `[Background] Video script failed for lesson …`
