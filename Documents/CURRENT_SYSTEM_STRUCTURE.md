# Current System Structure (Pre Multi-Tenant / White-Label)

Last updated: 2026-03-18

## 1) High-Level Overview

This is a Django monolith with one main project (`myProject`) and one primary app (`myApp`).

- Framework: Django 5.x
- Runtime: WSGI (Gunicorn), optional ASGI file present
- DB: `DATABASE_URL` (PostgreSQL in deployment), SQLite fallback locally
- Static/media: WhiteNoise + local static/media paths
- Auth: Django built-in auth (`User`) + role checks via decorators (`login_required`, `staff_member_required`)

The current system is effectively **single-tenant**: all courses, users, branding, and settings live in shared/global tables with no tenant boundary model.

## 2) Repository Layout

```text
Course_Admin_of_Admin/
├── myProject/                  # Django project config (settings, urls, wsgi/asgi)
├── myApp/                      # Main domain app
│   ├── models.py               # Core data model (courses, access, quizzes, exams, certs)
│   ├── views.py                # Public/student flows + creator + chatbot endpoints
│   ├── dashboard_views.py      # Admin dashboard flows + analytics + AI generation
│   ├── admin.py                # Django admin registrations
│   ├── context_processors.py   # Dashboard AI-generation widget context
│   ├── utils/
│   │   ├── access.py           # Access control service helpers
│   │   └── transcription.py    # Video transcription helper path
│   ├── templates/              # Landing, student, dashboard, creator templates
│   └── management/commands/    # Data seeding + Vimeo/Drive utility commands
├── static/
│   └── js/main.js
├── Documents/                  # Product/implementation docs
├── manage.py
├── requirements.txt
├── Procfile                    # release + web commands
└── gunicorn_config.py
```

## 3) Application Modules and Responsibilities

### `myProject`

- `settings.py`:
  - Environment loading via `python-dotenv`
  - `myApp` is the only custom installed app
  - `DATABASE_URL` parsing via `dj_database_url`
  - WhiteNoise static settings
  - DB cache backend (`DatabaseCache`)
- `urls.py`:
  - Public routes (home, login, courses, lesson pages)
  - Student dashboard routes (`my-dashboard`, certifications, progress)
  - Admin dashboard routes (`dashboard/...`)
  - Creator routes (`creator/...`)
  - API routes (`api/...`) for chatbot/progress/favorites

### `myApp`

- `views.py`:
  - Public pages + auth
  - Learning hub for guests and logged-in users
  - Course enrollment and lesson consumption
  - Lesson quiz submission
  - Creator lesson build flow (upload/transcribe/generate)
  - Chatbot endpoints and lesson progress APIs
- `dashboard_views.py`:
  - Admin dashboard home/analytics
  - Course/lesson/quiz CRUD and AI generation
  - Student/access management (grant/revoke/bulk)
  - Bundle management
- `utils/access.py`:
  - Access control utilities (`has_course_access`, batch checks, grant/revoke helpers)

## 4) Core Data Model (Current)

Major model groups in `myApp/models.py`:

- **Content**
  - `Course`, `Module`, `Lesson`, `CourseResource`
- **Assessment**
  - `LessonQuiz`, `LessonQuizQuestion`, `LessonQuizAttempt`
  - `Exam`, `ExamQuestion`, `ExamAttempt`
- **Learning tracking**
  - `UserProgress`, `CourseEnrollment`, `FavoriteCourse`
- **Certification**
  - `Certification`
- **Access control**
  - `CourseAccess`, `Bundle`, `BundlePurchase`, `CohortMember`, `Cohort`, `LearningPath`, `LearningPathCourse`

Important current characteristics:

- Course and bundle slugs are globally unique.
- Access is represented explicitly through `CourseAccess` (good foundation).
- No tenant foreign keys on core entities.
- No tenant-specific user or branding model.
- One duplicated class definition exists: `Cohort` appears twice in `models.py` (cleanup recommended before larger refactors).

## 5) Route Surface (Functional Grouping)

- Public: `/`, `/login`, `/courses`, `/courses/<course>/<lesson>`
- Student: `/my-dashboard`, `/my-dashboard/course/<slug>`, `/my-certifications`
- Admin: `/dashboard/...` (courses, lessons, quizzes, students, analytics, access, bundles)
- Creator: `/creator/...` (lesson creation + AI generation support)
- APIs:
  - `/api/chatbot/`
  - `/api/lessons/<id>/train-chatbot/`
  - `/api/lessons/<id>/chatbot/`
  - `/api/lessons/<id>/progress/`
  - `/api/lessons/<id>/complete/`
  - `/api/courses/<id>/favorite/`

## 6) External Integrations in Code

- OpenAI (lesson generation / quiz generation)
- Webhook-based chatbot training and chatbot interaction
- Vimeo metadata + Vimeo embed handling
- Google Drive video URL handling
- Accredible fields present in certification model

Most integration settings are global environment variables or hardcoded endpoint mappings, not tenant-scoped.

## 7) Deployment and Runtime

- `Procfile`:
  - `release`: migrate + create cache table + collectstatic
  - `web`: gunicorn (`myProject.wsgi:application`)
- `gunicorn_config.py`: sync workers, extended timeout for AI generation
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are statically configured for specific domains

## 8) Multi-Tenant / White-Label Readiness Snapshot

### Already useful foundations

- Central access model (`CourseAccess`) for entitlement logic
- Separation between student/public and admin/dashboard endpoints
- Course visibility/access-rule fields already exist

### Current blockers for true multi-tenancy

- No `Tenant` model and no tenant foreign key on domain tables
- No tenant-aware auth/session/domain routing
- Global slug uniqueness (will collide across brands)
- Global templates/static assets (no per-tenant theme/brand layer)
- Global env/config and webhook mappings (not tenant-specific)
- Analytics aggregate globally by default

## 9) Suggested Next Doc to Create

For your migration plan, the next document should be:

`Documents/MULTI_TENANT_TARGET_ARCHITECTURE.md`

It should define:

1. Tenant boundary model and data ownership
2. Tenant resolution strategy (subdomain/custom domain/header)
3. Required schema changes per model
4. Tenant-aware routing, permissions, and admin isolation
5. White-label theme/config strategy
6. Migration sequence with low-risk rollout phases

