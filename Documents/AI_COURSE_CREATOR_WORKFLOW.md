# AI Course Creator Workflow

This document explains how AI course creation works in this Django app, from course form inputs to background generation and the right-side progress loader in the dashboard.

Use this as a blueprint to replicate the same flow in another project.

## 1) User Input (Title -> Short -> Long Description)

The "Create Course" screen collects:

- `name` (course title)
- `short_description` (card/summary text)
- `description` (long description used heavily by AI)
- `course_type`
- `coach_name`
- `use_ai` checkbox (on by default)

Source: `myApp/templates/dashboard/add_course.html`

### Why each field matters

- `name`: primary course identity and slug seed.
- `short_description`: immediate UI copy in cards/lists.
- `description`: primary prompt context for AI structure generation.
- `course_type` + `coach_name`: prompt conditioning for style/voice.

## 2) Create Course Request

When the form is submitted:

1. Course record is created first (tenant-scoped).
2. If `use_ai` is enabled and description is present:
   - course is added to `request.session['ai_generating_courses']`
   - initial cache progress is set (`starting`)
   - a background thread starts `_generate_course_ai_content(...)`
3. user is redirected to course list/dashboard.

Source: `dashboard_add_course` in `myApp/dashboard_views.py`

## 3) Background AI Pipeline

Core worker: `_generate_course_ai_content(course_id, course_name, description, course_type, coach_name)`

### Step A: Generate structure JSON

- Calls `generate_ai_course_structure(...)` using OpenAI (`gpt-4o-mini`).
- Prompt asks for:
  - 3-6 modules
  - 3-8 lessons/module
  - practical progression
- Expects strict JSON and includes cleanup/fallback parsing.

### Step B: Persist modules + lessons

For each module/lesson from AI output:

- create `Module`
- create `Lesson` with tenant scope
- generate lesson metadata via `generate_ai_lesson_metadata(...)`
- generate lesson content blocks via `generate_ai_lesson_content(...)`
- convert to Editor.js blocks and save in `lesson.content`

### Step C: Auto-generate assessments

- Per lesson: create lesson quiz + AI questions.
- End of pipeline: create final exam + AI questions.

### Step D: Optional chatbot training webhook

- Sends lesson text/content to training webhook.
- Stores training status fields on lesson.

### Step E: Progress states

Progress is written to cache key `ai_gen_<course_id>` via `_update_ai_gen_progress(...)`.

Typical statuses:

- `starting`
- `generating_structure`
- `creating_content`
- `completed`
- `failed`

Source: `myApp/dashboard_views.py`

## 4) Right-Side Loader (Floating Progress Widget)

The dashboard base template renders widgets when `ai_generating_courses` exists in session.

Widget behavior:

- appears fixed bottom-right
- one widget per generating course
- polls `/dashboard/api/ai-generation-status/<course_id>/`
- updates progress bar + status text
- hides on completion/failure after terminal state handling

Sources:

- UI + polling script: `myApp/templates/dashboard/base.html`
- context injection: `myApp/context_processors.py` (`ai_generation_context`)
- status API: `api_ai_generation_status` in `myApp/dashboard_views.py`

## 5) Session + Cache Coordination

Two data stores are used together:

- Session (`ai_generating_courses`) controls which widgets are shown.
- Cache (`ai_gen_<course_id>`) stores live progress payload.

When status becomes terminal (`completed` or `failed`), the course is removed from session list.

## 6) Production Caveat (Important)

If production uses multiple workers and `locmem` cache, one worker may not see another worker's in-memory progress.

Mitigation already added:

- `api_ai_generation_status` now keeps polling if course still exists in session, instead of immediately returning permanent unknown.
- frontend tolerates transient `unknown` responses before hiding widgets.

Recommended long-term setup:

- Use shared cache in production:
  - `CACHE_BACKEND=db` (or Redis)
  - if DB cache: run `python manage.py createcachetable`

Source: `myProject/settings.py`, `myApp/dashboard_views.py`, `myApp/templates/dashboard/base.html`

## 7) End-to-End Sequence (Copyable Pattern)

1. user submits course form with `use_ai=true`
2. save base course row immediately
3. append `{id, name}` to session generating list
4. start background worker
5. worker updates progress cache at each stage
6. dashboard widgets poll status endpoint every ~2.5s
7. worker persists modules/lessons/quizzes/exam/content
8. on done/fail, status endpoint returns terminal state and session entry is removed

## 8) Replication Checklist for Another Project

- [ ] Create "Add Course" form with title/short/long description.
- [ ] Add `use_ai` toggle.
- [ ] Save base course first, then async generation.
- [ ] Create progress cache helper (`status`, `progress`, `current`, `error`).
- [ ] Store generating course IDs in session per user.
- [ ] Build floating loader component in dashboard shell.
- [ ] Add status polling endpoint.
- [ ] Remove finished items from session.
- [ ] Add shared cache backend in production.
- [ ] Keep AI JSON parsing defensive (strip code fences + fallback regex parse).

## 9) Key Files in This Project

- `myApp/templates/dashboard/add_course.html`
- `myApp/dashboard_views.py`
- `myApp/context_processors.py`
- `myApp/templates/dashboard/base.html`
- `myProject/settings.py`

