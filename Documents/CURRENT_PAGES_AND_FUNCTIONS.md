# Current Pages and Functions Map

Last updated: 2026-03-18  
Purpose: Master list of current routes/pages and what each does, so we can update them for multi-tenant behavior.

## 1) Public + Student-Facing Pages

| Route | View Function | Access | Template/Response | Current Function | Multi-Tenant Update Notes |
|---|---|---|---|---|---|
| `/` | `home` | Public | `landing.html` | Main landing page | Serve tenant branding/content by domain/subdomain |
| `/login/` | `login_view` | Public | `login.html` | User login form + auth | Tenant-specific login branding and tenant membership validation |
| `/logout/` | `logout_view` | Authenticated | Redirect | Ends session | Keep; ensure tenant session context cleared safely |
| `/courses/` | `courses` | Public/Auth | `learning_hub.html` | Unified catalog/dashboard (guest + logged-in) | Filter courses by `request.tenant` only |
| `/courses/<course_slug>/` | `course_detail` | Authenticated | `course_detail.html` | Course overview + lessons + enrollment/access state | Resolve course by tenant + slug, not global slug |
| `/courses/<course_slug>/enroll/` | `enroll_course` | Authenticated | Redirect/messages | Self-enroll/open-enrollment flow | Create `CourseAccess`/`CourseEnrollment` with tenant from request |
| `/courses/<course_slug>/<lesson_slug>/` | `lesson_detail` | Authenticated | `lesson.html` | Lesson view with video/content/progress | Query lesson with tenant boundary and tenant-scoped slug logic |
| `/courses/<course_slug>/<lesson_slug>/quiz/` | `lesson_quiz_view` | Authenticated | `lesson_quiz.html` | Submit/view lesson quiz | Ensure quiz and attempts are tenant-scoped |
| `/my-dashboard/` | `student_dashboard` | Authenticated | Redirect | Redirects to `/courses/` for logged-in users | Keep redirect; tenant context should be preserved |
| `/my-dashboard/course/<course_slug>/` | `student_course_progress` | Authenticated | `student/course_progress.html` | Detailed per-course progress view | Filter enrollment/progress/exam/certification by tenant |
| `/my-certifications/` | `student_certifications` | Authenticated | `student/certifications.html` | User cert history + eligible courses | Restrict to tenant-owned certifications/courses |

## 2) Admin Dashboard Pages (Current Staff/Admin Area)

| Route | View Function | Access | Template/Response | Current Function | Multi-Tenant Update Notes |
|---|---|---|---|---|---|
| `/dashboard/` | `dashboard_home` | Staff | `dashboard/home.html` | Admin overview stats | Tenant admin should see tenant-only metrics |
| `/dashboard/analytics/` | `dashboard_analytics` | Staff | `dashboard/analytics.html` | Analytics and trends | Split into tenant analytics + super-admin global analytics |
| `/dashboard/courses/` | `dashboard_courses` | Staff | `dashboard/courses.html` | Course list/manage | Scope to tenant courses only |
| `/dashboard/courses/add/` | `dashboard_add_course` | Staff | `dashboard/add_course.html` | Create course (optional AI generation) | Assign `tenant=request.tenant` always |
| `/dashboard/courses/<course_slug>/` | `dashboard_course_detail` | Staff | `dashboard/course_detail.html` | Edit course + resources | Resolve by tenant + slug |
| `/dashboard/courses/<course_slug>/lessons/` | `dashboard_course_lessons` | Staff | `dashboard/course_lessons.html` | Lessons within a course | Tenant-scoped course lookup |
| `/dashboard/lessons/` | `dashboard_lessons` | Staff | `dashboard/lessons.html` | All lessons list | Tenant-filtered lessons only |
| `/dashboard/lessons/add/` | `dashboard_add_lesson` | Staff | `dashboard/select_course.html` (or redirect) | Select course and route to creator lesson flow | Only tenant courses selectable |
| `/dashboard/lessons/upload-quiz/` | `dashboard_upload_quiz` | Staff | `dashboard/upload_quiz.html` | Upload/generate quiz content | Tenant-scoped lesson/quiz selection |
| `/dashboard/lessons/<lesson_id>/edit/` | `dashboard_edit_lesson` | Staff | Redirect | Redirects to creator AI lesson page | Validate lesson belongs to tenant |
| `/dashboard/quizzes/` | `dashboard_quizzes` | Staff | `dashboard/quizzes.html` | Quiz management page | Tenant-only quizzes/attempts |
| `/dashboard/students/` | `dashboard_students` | Staff | `dashboard/students.html` | Student list and activity | Tenant-specific users/memberships only |
| `/dashboard/students/progress/` | `dashboard_student_progress` | Staff | `dashboard/student_progress.html` | Enrollment/progress overview | Tenant-scoped enrollment/progress |
| `/dashboard/students/<user_id>/` | `dashboard_student_detail` | Staff | `dashboard/student_detail.html` | Student deep-dive across courses | Limit to tenant users and tenant courses |
| `/dashboard/students/<user_id>/<course_slug>/` | `dashboard_student_detail` | Staff | `dashboard/student_detail.html` | Student + selected course detail | Tenant-safe user/course lookup |
| `/dashboard/courses/<course_slug>/progress/` | `dashboard_course_progress` | Staff | `dashboard/course_progress.html` | Progress board per course | Tenant-safe course lookup |
| `/dashboard/bundles/` | `dashboard_bundles` | Staff | `dashboard/bundles.html` | Bundle listing | Tenant-scoped bundles only |
| `/dashboard/bundles/add/` | `dashboard_add_bundle` | Staff | `dashboard/add_bundle.html` | Create bundle | Assign tenant and tenant-scoped slug uniqueness |
| `/dashboard/bundles/<bundle_id>/edit/` | `dashboard_edit_bundle` | Staff | `dashboard/edit_bundle.html` | Edit bundle details/courses | Tenant ownership validation |

## 3) Creator Flow Pages

| Route | View Function | Access | Template/Response | Current Function | Multi-Tenant Update Notes |
|---|---|---|---|---|---|
| `/creator/` | `creator_dashboard` | Staff | `creator/dashboard.html` | Creator home for lesson creation flow | Restrict to tenant-owned course creation |
| `/creator/courses/<course_slug>/lessons/` | `course_lessons` | Staff | `creator/course_lessons.html` | Lesson list in creator flow | Tenant + course slug resolution |
| `/creator/courses/<course_slug>/add-lesson/` | `add_lesson` | Staff | `creator/add_lesson.html` | Draft lesson from inputs/video/transcription | Ensure lesson created with tenant |
| `/creator/courses/<course_slug>/lessons/<lesson_id>/generate/` | `generate_lesson_ai` | Staff | `creator/generate_lesson_ai.html` | AI content generation/edit for lesson | Tenant-safe lesson retrieval and writes |

## 4) Action/API Endpoints (No Page Render)

| Route | View Function | Method | Access | Current Function | Multi-Tenant Update Notes |
|---|---|---|---|---|---|
| `/creator/verify-vimeo/` | `verify_vimeo_url` | POST | Staff | Validate Vimeo URL and metadata | Use tenant integration config if required |
| `/creator/upload-video-transcribe/` | `upload_video_transcribe` | POST | Staff | Upload + transcription trigger | Use tenant-specific AI/transcription config |
| `/creator/lessons/<lesson_id>/transcription-status/` | `check_transcription_status` | POST | Staff | Poll transcription status | Tenant ownership check on lesson |
| `/dashboard/api/ai-generation-status/<course_id>/` | `api_ai_generation_status` | GET | Staff | Poll AI course generation status | Tenant-check course before exposing status |
| `/dashboard/courses/<course_slug>/delete/` | `dashboard_delete_course` | POST | Staff | Delete course | Tenant ownership enforcement |
| `/dashboard/lessons/<lesson_id>/delete/` | `dashboard_delete_lesson` | POST | Staff | Delete lesson | Tenant ownership enforcement |
| `/dashboard/lessons/<lesson_id>/quiz/delete/` | `dashboard_delete_quiz` | POST | Staff | Delete lesson quiz | Tenant ownership enforcement |
| `/dashboard/bundles/<bundle_id>/delete/` | `dashboard_delete_bundle` | POST | Staff | Delete bundle | Tenant ownership enforcement |
| `/dashboard/access/bulk/` | `bulk_access_management` | GET | Staff | Bulk access management page render | Tenant-scoped target users/courses |
| `/dashboard/access/bulk/grant/` | `bulk_grant_access_view` | POST | Staff | Bulk grant course access | Tenant-safe granting only within same tenant |
| `/dashboard/students/<user_id>/grant-access/` | `grant_course_access_view` | POST | Staff | Grant individual course access | Enforce user/course tenant match |
| `/dashboard/students/<user_id>/revoke-access/` | `revoke_course_access_view` | POST | Staff | Revoke course access | Enforce user/course tenant match |
| `/dashboard/students/<user_id>/grant-bundle/` | `grant_bundle_access_view` | POST | Staff | Grant bundle access | Bundle and selected courses must be same tenant |
| `/dashboard/students/<user_id>/add-cohort/` | `add_to_cohort_view` | POST | Staff | Add user to cohort | Cohort/user tenant checks |
| `/api/chatbot/` | `chatbot_webhook` | POST | Authenticated | Send chat payload to chatbot webhook | Tenant-specific webhook endpoint/config |
| `/api/lessons/<lesson_id>/train-chatbot/` | `train_lesson_chatbot` | POST | Staff | Train chatbot from lesson transcript | Use tenant-specific chatbot config |
| `/api/lessons/<lesson_id>/chatbot/` | `lesson_chatbot` | POST | Authenticated | Chat against lesson context | Tenant check + tenant-specific inference config |
| `/api/lessons/<lesson_id>/progress/` | `update_video_progress` | POST | Authenticated | Persist lesson video progress | Validate lesson belongs to user tenant |
| `/api/lessons/<lesson_id>/complete/` | `complete_lesson` | POST | Authenticated | Mark lesson complete | Same tenant and access enforcement |
| `/api/courses/<course_id>/favorite/` | `toggle_favorite_course` | POST | Authenticated | Toggle favorite course state | Tenant-safe course selection |

## 5) Platform/Admin Built-ins

| Route | Handler | Current Function | Multi-Tenant Update Notes |
|---|---|---|---|
| `/admin/` | Django admin site | Framework admin backend | Keep for super-admin/internal ops only, or gate by role |

## 6) Recommended Update Workflow (How to Use This Document)

For each route above during multi-tenant rollout:

1. Add tenant resolution (`request.tenant`) dependency
2. Replace global lookups with tenant-scoped lookups
3. Enforce ownership checks before read/write/delete
4. Make integrations read tenant-level config (`TenantConfig`)
5. Add tests for cross-tenant access denial (must fail)

