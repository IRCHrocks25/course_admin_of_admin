# Complete Course System Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Database Models](#database-models)
3. [Views & API Endpoints](#views--api-endpoints)
4. [Core Features](#core-features)
5. [Admin Dashboard](#admin-dashboard)
6. [Student Dashboard](#student-dashboard)
7. [Access Control System](#access-control-system)
8. [Quiz System](#quiz-system)
9. [Progress Tracking](#progress-tracking)
10. [Certifications & Exams](#certifications--exams)
11. [Integrations](#integrations)
12. [Frontend Components](#frontend-components)
13. [Utilities & Helper Functions](#utilities--helper-functions)
14. [Setup & Configuration](#setup--configuration)
15. [Deployment](#deployment)

---

## System Overview

### Technology Stack
- **Backend Framework**: Django 5.1.2
- **Database**: PostgreSQL (production) / SQLite (development)
- **Frontend**: Tailwind CSS, Vanilla JavaScript
- **Video Hosting**: Vimeo, Google Drive, Cloudinary
- **AI Services**: OpenAI (for quiz generation, lesson generation)
- **File Storage**: Cloudinary (images, videos)
- **Authentication**: Django's built-in authentication

### Architecture
- **MVC Pattern**: Django follows Model-View-Template architecture
- **RESTful APIs**: API endpoints for progress tracking, favorites, chatbot
- **Modular Design**: Separate views for student and admin dashboards
- **Access Control**: Explicit access records with full audit trail

---

## Database Models

### 1. Course Model
**Location**: `myApp/models.py`

**Purpose**: Represents a course/program in the system

**Key Fields**:
```python
- name: CharField(max_length=200) - Course name
- slug: SlugField(unique=True) - URL-friendly identifier
- course_type: CharField - Choices: 'sprint', 'speaking', 'consultancy', 'special'
- status: CharField - Choices: 'active', 'locked', 'coming_soon'
- description: TextField - Full course description
- short_description: CharField(max_length=300) - Brief description for cards
- thumbnail: ImageField - Course thumbnail image
- coach_name: CharField - AI coach name for this course
- is_subscribers_only: BooleanField - Whether course requires subscription
- is_accredible_certified: BooleanField - Whether course has Accredible certification
- has_asset_templates: BooleanField - Whether course includes asset templates
- exam_unlock_days: IntegerField - Days after enrollment before exam unlocks
- special_tag: CharField - Special promotional tags (e.g., 'Black Friday 2025')

# Access Control Fields
- visibility: CharField - 'public', 'members_only', 'hidden', 'private'
- enrollment_method: CharField - 'open', 'purchase', 'invite_only', 'cohort_only', 'subscription_only'
- access_duration_type: CharField - 'lifetime', 'fixed_days', 'until_date', 'drip'
- access_duration_days: IntegerField - Duration in days (if fixed_days)
- access_until_date: DateTimeField - Expiration date (if until_date)
- prerequisite_courses: ManyToManyField - Courses that must be completed first
- required_quiz_score: IntegerField - Required quiz score to unlock
```

**Key Methods**:
- `get_lesson_count()` - Returns total number of lessons
- `get_user_progress(user)` - Returns progress percentage for a user

---

### 2. Module Model
**Purpose**: Organizes lessons into modules within a course

**Fields**:
```python
- course: ForeignKey(Course) - Parent course
- name: CharField - Module name
- description: TextField - Module description
- order: IntegerField - Display order
```

---

### 3. Lesson Model
**Purpose**: Individual lesson/video within a course

**Key Fields**:
```python
- course: ForeignKey(Course) - Parent course
- module: ForeignKey(Module, nullable) - Optional module grouping
- title: CharField - Lesson title
- slug: SlugField - URL-friendly identifier
- description: TextField - Lesson description
- video_url: URLField - Generic video URL
- video_duration: IntegerField - Duration in minutes
- order: IntegerField - Display order
- workbook_url: URLField - Link to workbook/downloads
- resources_url: URLField - Link to resources
- lesson_type: CharField - 'video', 'live', 'replay'

# Vimeo Integration
- vimeo_url: URLField - Full Vimeo URL
- vimeo_id: CharField - Extracted Vimeo ID
- vimeo_thumbnail: URLField - Vimeo thumbnail URL
- vimeo_duration_seconds: IntegerField - Duration from Vimeo

# Google Drive Integration
- google_drive_url: URLField - Google Drive embed URL
- google_drive_id: CharField - Google Drive file ID

# AI Generation Fields
- working_title: CharField - Rough title before AI polish
- rough_notes: TextField - Notes/outline for AI generation
- transcription: TextField - Auto-generated transcription
- transcription_status: CharField - 'pending', 'processing', 'completed', 'failed'
- transcription_error: TextField - Error message if transcription fails
- ai_generation_status: CharField - 'pending', 'generated', 'approved'
- ai_clean_title: CharField - AI-polished title
- ai_short_summary: TextField - AI-generated summary
- ai_full_description: TextField - AI-generated full description
- ai_outcomes: JSONField - List of learning outcomes
- ai_coach_actions: JSONField - Recommended AI coach actions
```

**Key Methods**:
- `get_vimeo_embed_url()` - Returns formatted Vimeo embed URL
- `get_formatted_duration()` - Returns duration as MM:SS
- `get_outcomes_list()` - Returns outcomes as Python list
- `get_coach_actions_list()` - Returns coach actions as Python list

---

### 4. LessonQuiz Model
**Purpose**: Quiz attached to a lesson

**Fields**:
```python
- lesson: OneToOneField(Lesson) - Related lesson
- title: CharField - Quiz title
- description: TextField - Quiz description
- is_required: BooleanField - Whether quiz must be passed to complete lesson
- passing_score: IntegerField - Required score percentage (0-100)
```

---

### 5. LessonQuizQuestion Model
**Purpose**: Individual question in a lesson quiz

**Fields**:
```python
- quiz: ForeignKey(LessonQuiz) - Parent quiz
- text: TextField - Question text
- option_a: CharField - Option A
- option_b: CharField - Option B
- option_c: CharField(blank=True) - Option C (optional)
- option_d: CharField(blank=True) - Option D (optional)
- correct_option: CharField - 'A', 'B', 'C', or 'D'
- order: IntegerField - Question order
```

---

### 6. LessonQuizAttempt Model
**Purpose**: Tracks student quiz attempts

**Fields**:
```python
- user: ForeignKey(User) - Student who attempted
- quiz: ForeignKey(LessonQuiz) - Quiz attempted
- score: FloatField - Score percentage (0-100)
- passed: BooleanField - Whether student passed
- completed_at: DateTimeField - When quiz was completed
```

---

### 7. UserProgress Model
**Purpose**: Tracks individual student progress on lessons

**Fields**:
```python
- user: ForeignKey(User) - Student
- lesson: ForeignKey(Lesson) - Lesson being tracked
- status: CharField - 'not_started', 'in_progress', 'completed'
- completed: BooleanField - Completion flag
- completed_at: DateTimeField - When lesson was completed
- progress_percentage: IntegerField - Overall progress (0-100)

# Video Watch Progress
- video_watch_percentage: FloatField - Percentage of video watched (0-100)
- last_watched_timestamp: FloatField - Last position in video (seconds)
- video_completion_threshold: FloatField - Required watch % to complete (default 90%)
- last_accessed: DateTimeField - Last time lesson was accessed (auto-updated)
- started_at: DateTimeField - When lesson was first started
```

**Key Methods**:
- `update_status()` - Automatically updates status based on video watch percentage

---

### 8. CourseEnrollment Model
**Purpose**: Tracks course enrollments

**Fields**:
```python
- user: ForeignKey(User) - Student
- course: ForeignKey(Course) - Course enrolled in
- enrolled_at: DateTimeField - Enrollment timestamp
- payment_type: CharField - 'full', 'installment'
```

---

### 9. FavoriteCourse Model
**Purpose**: Tracks user's favorited courses

**Fields**:
```python
- user: ForeignKey(User) - Student
- course: ForeignKey(Course) - Favorited course
- created_at: DateTimeField - When course was favorited
```

**Meta**: Unique constraint on (user, course)

---

### 10. Exam Model
**Purpose**: Final exam for a course

**Fields**:
```python
- course: OneToOneField(Course) - Related course
- title: CharField - Exam title
- description: TextField - Exam description
- passing_score: IntegerField - Minimum score to pass (0-100)
- max_attempts: IntegerField - Maximum attempts allowed (0 = unlimited)
- time_limit_minutes: IntegerField - Time limit (null = no limit)
- is_active: BooleanField - Whether exam is active
```

---

### 11. ExamAttempt Model
**Purpose**: Tracks exam attempts

**Fields**:
```python
- user: ForeignKey(User) - Student
- exam: ForeignKey(Exam) - Exam attempted
- score: FloatField - Score percentage (0-100)
- passed: BooleanField - Whether student passed
- started_at: DateTimeField - When exam was started
- completed_at: DateTimeField - When exam was completed
- time_taken_seconds: IntegerField - Time taken
- answers: JSONField - Student's answers
- is_final: BooleanField - Whether this is the final attempt
```

**Key Methods**:
- `attempt_number()` - Returns attempt number for this user/exam

---

### 12. Certification Model
**Purpose**: Tracks certification status and Accredible integration

**Fields**:
```python
- user: ForeignKey(User) - Student
- course: ForeignKey(Course) - Course for certification
- status: CharField - 'not_eligible', 'eligible', 'passed', 'failed'
- accredible_certificate_id: CharField - Accredible certificate ID
- accredible_certificate_url: URLField - Link to Accredible certificate
- issued_at: DateTimeField - When certificate was issued
- passing_exam_attempt: ForeignKey(ExamAttempt) - Exam attempt that resulted in certification
```

---

### 13. CourseAccess Model ⭐ **CORE ACCESS CONTROL**
**Purpose**: Explicit access records - "Access is a thing, not a side effect"

**Fields**:
```python
- user: ForeignKey(User) - Student
- course: ForeignKey(Course) - Course accessed
- access_type: CharField - 'purchase', 'manual', 'cohort', 'subscription', 'bundle'
- status: CharField - 'unlocked', 'locked', 'revoked', 'expired', 'pending'

# Source Tracking
- bundle_purchase: ForeignKey(BundlePurchase, nullable) - Source bundle
- cohort: ForeignKey(Cohort, nullable) - Source cohort
- purchase_id: CharField - External purchase ID
- granted_by: ForeignKey(User, nullable) - Admin who granted access
- granted_at: DateTimeField - When access was granted

# Expiration & Revocation
- expires_at: DateTimeField - When access expires
- revoked_at: DateTimeField - When access was revoked
- revoked_by: ForeignKey(User, nullable) - Admin who revoked access
- revocation_reason: CharField - Reason for revocation
- notes: TextField - Audit trail notes
```

**Key Methods**:
- `is_active()` - Checks if access is currently active (not expired/revoked)
- `get_source_display()` - Returns human-readable source of access

---

### 14. Bundle Model
**Purpose**: Product bundles that grant access to multiple courses

**Fields**:
```python
- name: CharField - Bundle name
- slug: SlugField(unique=True) - URL-friendly identifier
- description: TextField - Bundle description
- bundle_type: CharField - 'fixed', 'pick_your_own', 'tiered'
- courses: ManyToManyField(Course) - Courses included in bundle
- max_course_selections: IntegerField - For pick-your-own bundles
- price: DecimalField - Bundle price
- is_active: BooleanField - Whether bundle is active
```

---

### 15. BundlePurchase Model
**Purpose**: Tracks bundle purchases

**Fields**:
```python
- user: ForeignKey(User) - Purchaser
- bundle: ForeignKey(Bundle) - Bundle purchased
- purchase_id: CharField - External purchase/order ID
- purchase_date: DateTimeField - Purchase timestamp
- selected_courses: ManyToManyField(Course) - For pick-your-own bundles
- notes: TextField - Additional notes
```

---

### 16. Cohort Model
**Purpose**: Groups of students (e.g., "Black Friday 2025 Buyers")

**Fields**:
```python
- name: CharField(unique=True) - Cohort name
- description: TextField - Cohort description
- is_active: BooleanField - Whether cohort is active
```

**Key Methods**:
- `get_member_count()` - Returns number of members

---

### 17. CohortMember Model
**Purpose**: Links users to cohorts

**Fields**:
```python
- cohort: ForeignKey(Cohort) - Cohort
- user: ForeignKey(User) - Member
- joined_at: DateTimeField - When user joined
- remove_access_on_leave: BooleanField - Whether to revoke access on removal
```

**Meta**: Unique constraint on (cohort, user)

---

### 18. LearningPath Model
**Purpose**: Curated learning journeys (e.g., "7-Figure Launch Path")

**Fields**:
```python
- name: CharField - Learning path name
- description: TextField - Path description
- courses: ManyToManyField(Course, through='LearningPathCourse') - Courses in path
- is_active: BooleanField - Whether path is active
```

---

### 19. LearningPathCourse Model
**Purpose**: Ordered courses in a learning path

**Fields**:
```python
- learning_path: ForeignKey(LearningPath)
- course: ForeignKey(Course)
- order: IntegerField - Course order in path
- is_required: BooleanField - Whether course must be completed to unlock next
```

**Meta**: Unique constraint on (learning_path, course)

---

## Views & API Endpoints

### Public-Facing Views
**Location**: `myApp/views.py`

#### 1. `home(request)`
- **URL**: `/`
- **Template**: `landing.html`
- **Purpose**: Landing page

#### 2. `login_view(request)`
- **URL**: `/login/`
- **Method**: GET, POST
- **Purpose**: User authentication

#### 3. `logout_view(request)`
- **URL**: `/logout/`
- **Purpose**: User logout

#### 4. `courses(request)`
- **URL**: `/courses/`
- **Template**: `courses.html`
- **Purpose**: Course catalog page
- **Features**:
  - Shows courses by visibility rules
  - Displays "Continue Learning" and "Learn More" sections
  - Favorite course functionality
  - Filtering and sorting

#### 5. `course_detail(request, course_slug)`
- **URL**: `/courses/<slug>/`
- **Template**: `course_detail.html`
- **Purpose**: Course detail page

#### 6. `lesson_detail(request, course_slug, lesson_slug)`
- **URL**: `/courses/<slug>/<lesson_slug>/`
- **Template**: `lesson.html`
- **Purpose**: Lesson video player page
- **Features**:
  - Video player (Vimeo/Google Drive/Cloudinary)
  - Progress tracking
  - Lesson completion
  - AI chatbot integration
  - Next/Previous lesson navigation
  - Quiz link (if available)

#### 7. `lesson_quiz_view(request, course_slug, lesson_slug)`
- **URL**: `/courses/<slug>/<lesson_slug>/quiz/`
- **Template**: `lesson_quiz.html`
- **Method**: GET, POST
- **Purpose**: Display and submit lesson quiz
- **Features**:
  - Multiple-choice questions
  - Score calculation
  - Pass/fail determination
  - Required quiz blocking lesson completion
  - Confetti animation on pass

### Student Dashboard Views

#### 8. `student_dashboard(request)`
- **URL**: `/my-dashboard/`
- **Template**: `student/dashboard.html`
- **Purpose**: Student's personal dashboard
- **Features**:
  - Overall stats (courses enrolled, completed, lessons completed, certifications)
  - "My Courses" section with progress
  - Favorite course toggle
  - Filter by favorites
  - "Continue Learning" vs "Start Course" buttons
  - AI Tools links

#### 9. `student_course_progress(request, course_slug)`
- **URL**: `/my-dashboard/course/<slug>/`
- **Template**: `student/course_progress.html`
- **Purpose**: Detailed course progress view
- **Features**:
  - Course overview
  - Lesson-by-lesson progress
  - Completion status
  - Quiz results

#### 10. `student_certifications(request)`
- **URL**: `/my-certifications/`
- **Template**: `student/certifications.html`
- **Purpose**: Display student's certifications
- **Features**:
  - List of earned certifications
  - Trophy achievements (Bronze, Silver, Gold, Platinum, Diamond, Ultimate)
  - Accredible certificate links
  - Unlockable trophies based on certification count

### API Endpoints

#### 11. `update_video_progress(request, lesson_id)`
- **URL**: `/api/lessons/<id>/progress/`
- **Method**: POST (JSON)
- **Purpose**: Update video watch progress
- **Request Body**:
  ```json
  {
    "watch_percentage": 75.5,
    "timestamp": 120.5
  }
  ```
- **Response**:
  ```json
  {
    "success": true,
    "watch_percentage": 75.5,
    "status": "in_progress",
    "completed": false
  }
  ```

#### 12. `complete_lesson(request, lesson_id)`
- **URL**: `/api/lessons/<id>/complete/`
- **Method**: POST
- **Purpose**: Mark lesson as complete
- **Validation**: Checks if required quiz is passed
- **Response**:
  ```json
  {
    "success": true,
    "message": "Lesson marked as complete",
    "lesson_id": 123
  }
  ```

#### 13. `toggle_favorite_course(request, course_id)`
- **URL**: `/api/courses/<id>/favorite/`
- **Method**: POST
- **Purpose**: Toggle favorite status for a course
- **Response**:
  ```json
  {
    "success": true,
    "is_favorited": true,
    "message": "Course favorited"
  }
  ```

#### 14. `chatbot_webhook(request)`
- **URL**: `/api/chatbot/`
- **Method**: POST (JSON)
- **Purpose**: AI chatbot integration
- **Request Body**:
  ```json
  {
    "action": "free_form",
    "action_text": "Generate social posts",
    "user_message": "Create 5 social media posts from this lesson",
    "lesson_id": 123,
    "lesson_title": "Session #1",
    "course_name": "Virtual Rockstar"
  }
  ```
- **Response**: AI-generated response (varies by action)

### Admin Dashboard Views
**Location**: `myApp/dashboard_views.py`

#### 15. `dashboard_home(request)`
- **URL**: `/dashboard/`
- **Template**: `dashboard/home.html`
- **Purpose**: Admin dashboard overview
- **Features**: Quick stats, recent activity feed

#### 16. `dashboard_analytics(request)`
- **URL**: `/dashboard/analytics/`
- **Template**: `dashboard/analytics.html`
- **Purpose**: Comprehensive analytics dashboard
- **Metrics**:
  - Student analytics (total, active, new, inactive)
  - Enrollment analytics (total, trends, by course)
  - Progress analytics (completion rates, updates)
  - Certification analytics
  - Course performance overview
  - Enrollment/certification trends (30-day charts)
  - Top 5 courses by enrollment
  - Most active students

#### 17. `dashboard_courses(request)`
- **URL**: `/dashboard/courses/`
- **Template**: `dashboard/courses.html`
- **Purpose**: List all courses

#### 18. `dashboard_add_course(request)`
- **URL**: `/dashboard/courses/add/`
- **Template**: `dashboard/add_course.html`
- **Method**: GET, POST
- **Purpose**: Create new course

#### 19. `dashboard_course_detail(request, course_slug)`
- **URL**: `/dashboard/courses/<slug>/`
- **Template**: `dashboard/course_detail.html`
- **Method**: GET, POST
- **Purpose**: Edit course details

#### 20. `dashboard_delete_course(request, course_slug)`
- **URL**: `/dashboard/courses/<slug>/delete/`
- **Method**: POST
- **Purpose**: Delete course

#### 21. `dashboard_lessons(request)`
- **URL**: `/dashboard/lessons/`
- **Template**: `dashboard/lessons.html`
- **Purpose**: List all lessons across courses

#### 22. `dashboard_add_lesson(request)`
- **URL**: `/dashboard/lessons/add/`
- **Purpose**: Create new lesson

#### 23. `dashboard_edit_lesson(request, lesson_id)`
- **URL**: `/dashboard/lessons/<id>/edit/`
- **Purpose**: Edit lesson

#### 24. `dashboard_delete_lesson(request, lesson_id)`
- **URL**: `/dashboard/lessons/<id>/delete/`
- **Method**: POST
- **Purpose**: Delete lesson

#### 25. `dashboard_upload_quiz(request)`
- **URL**: `/dashboard/lessons/upload-quiz/`
- **Template**: `dashboard/upload_quiz.html`
- **Method**: GET, POST
- **Purpose**: Upload/create quiz
- **Features**:
  - File upload (CSV, PDF)
  - AI generation (OpenAI)
  - Preloader for AI generation

#### 26. `dashboard_lesson_quiz(request, lesson_id)`
- **URL**: `/dashboard/lessons/<id>/quiz/`
- **Template**: `dashboard/lesson_quiz.html`
- **Method**: GET, POST
- **Purpose**: Manage quiz for a lesson
- **Actions**:
  - `save_quiz` - Save quiz settings
  - `add_question` - Add new question
  - `edit_question` - Edit existing question (via modal)
  - `delete_question` - Delete question

#### 27. `dashboard_delete_quiz(request, lesson_id)`
- **URL**: `/dashboard/lessons/<id>/quiz/delete/`
- **Method**: POST
- **Purpose**: Delete entire quiz

#### 28. `dashboard_quizzes(request)`
- **URL**: `/dashboard/quizzes/`
- **Template**: `dashboard/quizzes.html`
- **Purpose**: List all quizzes

#### 29. `dashboard_students(request)`
- **URL**: `/dashboard/students/`
- **Template**: `dashboard/students.html`
- **Purpose**: List all students
- **Features**: Search, filter, pagination

#### 30. `dashboard_student_detail(request, user_id, course_slug=None)`
- **URL**: `/dashboard/students/<id>/` or `/dashboard/students/<id>/<course_slug>/`
- **Template**: `dashboard/student_detail.html`
- **Purpose**: Detailed student view
- **Features**:
  - Student profile
  - Course access management
  - Progress overview
  - Grant/revoke access
  - Bundle access
  - Cohort management

#### 31. `dashboard_course_progress(request, course_slug)`
- **URL**: `/dashboard/courses/<slug>/progress/`
- **Template**: `dashboard/course_progress.html`
- **Purpose**: Course-level progress analytics

#### 32. `grant_course_access_view(request, user_id)`
- **URL**: `/dashboard/students/<id>/grant-access/`
- **Method**: POST
- **Purpose**: Grant manual course access

#### 33. `revoke_course_access_view(request, user_id)`
- **URL**: `/dashboard/students/<id>/revoke-access/`
- **Method**: POST
- **Purpose**: Revoke course access

#### 34. `grant_bundle_access_view(request, user_id)`
- **URL**: `/dashboard/students/<id>/grant-bundle/`
- **Method**: POST
- **Purpose**: Grant bundle access (creates BundlePurchase and CourseAccess records)

#### 35. `add_to_cohort_view(request, user_id)`
- **URL**: `/dashboard/students/<id>/add-cohort/`
- **Method**: POST
- **Purpose**: Add user to cohort

#### 36. `bulk_access_management(request)`
- **URL**: `/dashboard/access/bulk/`
- **Template**: `dashboard/bulk_access.html`
- **Purpose**: Bulk grant access to multiple users/courses

#### 37. `bulk_grant_access_view(request)`
- **URL**: `/dashboard/access/bulk/grant/`
- **Method**: POST
- **Purpose**: Process bulk access grants

#### 38. `dashboard_bundles(request)`
- **URL**: `/dashboard/bundles/`
- **Template**: `dashboard/bundles.html`
- **Purpose**: List all bundles

#### 39. `dashboard_add_bundle(request)`
- **URL**: `/dashboard/bundles/add/`
- **Template**: `dashboard/add_bundle.html`
- **Method**: GET, POST
- **Purpose**: Create new bundle

#### 40. `dashboard_edit_bundle(request, bundle_id)`
- **URL**: `/dashboard/bundles/<id>/edit/`
- **Template**: `dashboard/edit_bundle.html`
- **Method**: GET, POST
- **Purpose**: Edit bundle

#### 41. `dashboard_delete_bundle(request, bundle_id)`
- **URL**: `/dashboard/bundles/<id>/delete/`
- **Method**: POST
- **Purpose**: Delete bundle

---

## Core Features

### 1. Course Management
- **Create/Edit/Delete Courses**: Full CRUD operations
- **Course Types**: Sprint, Speaking, Consultancy, Special
- **Status Management**: Active, Locked, Coming Soon
- **Thumbnails**: Image upload via Cloudinary
- **Descriptions**: Full and short descriptions
- **Special Tags**: Promotional tags (e.g., "Black Friday 2025")

### 2. Lesson Management
- **Create/Edit/Delete Lessons**: Full CRUD operations
- **Video Hosting**: Vimeo, Google Drive, Cloudinary support
- **Module Organization**: Group lessons into modules
- **AI Generation**: OpenAI-powered lesson content generation
- **Transcription**: Video transcription (placeholder - configurable)
- **Outcomes & Coach Actions**: AI-generated learning outcomes and actions

### 3. Progress Tracking
- **Real-time Progress**: Video watch percentage tracking
- **Automatic Status Updates**: Status updates based on watch percentage
- **Completion Threshold**: Configurable (default 90%)
- **Last Accessed Tracking**: Tracks when lessons were last accessed
- **Progress Percentage**: Overall lesson progress (0-100%)

### 4. Quiz System
- **Lesson Quizzes**: Optional quizzes attached to lessons
- **Required Quizzes**: Block lesson completion until passed
- **Multiple Choice**: Support for 2-4 options per question
- **Scoring**: Automatic score calculation
- **Passing Score**: Configurable passing score (default 70%)
- **Attempt Tracking**: Tracks all quiz attempts
- **AI Generation**: OpenAI-powered quiz question generation
- **File Upload**: CSV and PDF quiz import

### 5. Access Control System ⭐ **CRITICAL FEATURE**
- **Explicit Access Records**: "Access is a thing, not a side effect"
- **Full Audit Trail**: Tracks who granted access, when, why, and source
- **Multiple Access Types**: Purchase, Manual, Cohort, Subscription, Bundle
- **Expiration Management**: Time-based access expiration
- **Revocation**: Ability to revoke access with reason tracking
- **Source Tracking**: Links access to purchases, bundles, cohorts
- **Status Management**: Unlocked, Locked, Revoked, Expired, Pending

### 6. Favorite Courses
- **Toggle Favorites**: One-click favorite/unfavorite
- **Filter by Favorites**: View only favorited courses
- **Visual Indicators**: Highlighted favorite icons
- **Persistent Storage**: Saved in database

### 7. Certifications
- **Accredible Integration**: Accredible certificate generation
- **Trophy System**: 6 tiers of unlockable trophies
  - Bronze (1 cert)
  - Silver (2 certs)
  - Gold (3 certs)
  - Platinum (5 certs)
  - Diamond (10 certs)
  - Ultimate (20+ certs)
- **Certificate URLs**: Direct links to Accredible certificates
- **Status Tracking**: Not Eligible, Eligible, Passed, Failed

### 8. Exams
- **Final Exams**: Course completion exams
- **Attempt Limiting**: Configurable max attempts (0 = unlimited)
- **Time Limits**: Optional time limits
- **Score Tracking**: Pass/fail determination
- **Unlock Rules**: Based on payment type and course completion

### 9. Bundles
- **Fixed Bundles**: Curated set of courses
- **Pick Your Own**: Student chooses N courses
- **Tiered Bundles**: Bronze/Silver/Gold tiers
- **Bundle Purchases**: Tracks bundle purchases
- **Automatic Access**: Grants access to all courses in bundle

### 10. Cohorts
- **Group Management**: Create and manage student groups
- **Cohort Members**: Add/remove members
- **Access on Join**: Automatic course access on cohort join
- **Access on Leave**: Optional access revocation on removal

### 11. Learning Paths
- **Curated Journeys**: Structured learning sequences
- **Course Ordering**: Define course order in path
- **Required Courses**: Mark courses as required to unlock next
- **Progressive Unlocking**: Sequential course unlocking

### 12. Analytics Dashboard
- **Student Analytics**: Total, active, new, inactive students
- **Enrollment Analytics**: Trends, by course, time periods
- **Progress Analytics**: Completion rates, updates
- **Certification Analytics**: Certificates issued, trends
- **Course Performance**: Students per course, completion rates
- **Charts**: 30-day enrollment and certification trends
- **Top Lists**: Top courses, most active students

### 13. Live Activity Feed
- **Real-time Updates**: Auto-refresh activity feed
- **Activity Types**: Lesson completions, quiz attempts, certifications, progress updates
- **Aggregation**: Combines activities from multiple models
- **Timeline View**: Chronological activity display
- **Student Details**: Links to student profiles

### 14. AI Integration
- **Quiz Generation**: OpenAI-powered quiz question generation
- **Lesson Generation**: AI-generated lesson content
- **Chatbot**: AI chatbot for lesson assistance
- **Actions**: Pre-defined actions (social posts, summaries, etc.)

### 15. Preloaders & Loading States
- **Universal Preloader**: Full-screen loading overlay
- **Form Preloaders**: Automatic preloader on form submission
- **AI Generation Preloader**: Special preloader for AI operations
- **Inline Loaders**: Loading indicators for favorite toggles
- **Progress Indicators**: Video progress, quiz submission

---

## Admin Dashboard

### Navigation Structure
- **Overview**: Dashboard home with quick stats
- **Analytics**: Comprehensive analytics page
- **Courses**: Course management
- **Lessons**: Lesson management
- **Quizzes**: Quiz management
- **Students**: Student management
- **Bundles**: Bundle management
- **View Site**: Link to public site

### Key Pages

#### Dashboard Home (`/dashboard/`)
- Total students count
- Active students (last 30 days)
- New students (last 7 days)
- Total enrollments
- Total course accesses
- Total progress updates
- Total certifications
- Recent activity feed (auto-refresh)

#### Analytics (`/dashboard/analytics/`)
- **Key Metrics Cards**: Total students, enrollments, certifications, completion rate
- **Secondary Metrics**: New students 7d, inactive, active access grants, progress updates 7d
- **Enrollment Trend**: 30-day daily enrollment chart
- **Certification Trend**: 30-day daily certification chart
- **Course Performance Table**: Detailed metrics per course
- **Top 5 Courses**: By enrollment
- **Most Active Students**: 7-day activity

#### Course Management
- List all courses
- Create new course
- Edit course details
- Delete course
- View course progress

#### Lesson Management
- List all lessons
- Create new lesson
- Edit lesson
- Delete lesson
- Manage lesson quiz
- Upload quiz (file or AI)

#### Quiz Management
- List all quizzes
- View quiz details
- Edit quiz settings
- Add/edit/delete questions
- Edit question modal

#### Student Management
- List all students (search, filter)
- View student detail
- Grant/revoke course access
- Grant bundle access
- Add to cohort
- View student progress per course

#### Bundle Management
- List all bundles
- Create bundle
- Edit bundle
- Delete bundle
- Bundle includes course selection

---

## Student Dashboard

### Navigation
- **My Dashboard**: Personal dashboard
- **My Certifications**: Certifications and trophies
- **Courses**: Course catalog

### Key Pages

#### Student Dashboard (`/my-dashboard/`)
- **Overall Stats Cards**:
  - Enrolled Courses
  - Completed Courses
  - Lessons Completed (X/Y)
  - Certifications Earned
- **AI Tools Section**: Links to external AI tools
- **My Courses Section**:
  - Filter by favorites
  - Sort options
  - Course cards with:
    - Thumbnail
    - Course name
    - Progress percentage
    - Favorite button
    - Action buttons (Start Course / Continue Learning / View Progress)
    - Certification status
- **Available to Unlock**: Courses available but not yet accessed
- **Favorite Toggle**: Heart icon to favorite/unfavorite

#### Course Progress (`/my-dashboard/course/<slug>/`)
- Course overview
- Lesson-by-lesson progress
- Completion status
- Quiz results
- Next lesson link

#### Certifications (`/my-certifications/`)
- List of earned certifications
- Accredible certificate links
- Trophy Achievements section:
  - 6 trophy tiers
  - Visual unlock status
  - Hover effects on unlocked trophies
  - Progress to next tier

---

## Access Control System

### Core Concept
**"Access is a thing, not a side effect"**

Every student's access to a course is explicitly tracked with:
- Full audit trail (who, when, why)
- Source tracking (purchase, bundle, cohort, manual)
- Expiration management
- Revocation support

### Access Types
1. **Purchase**: Direct course purchase
2. **Manual**: Admin-granted access
3. **Cohort**: Access via cohort membership
4. **Subscription**: Access via subscription/membership
5. **Bundle**: Access via bundle purchase

### Access Status
- **Unlocked**: Active access
- **Locked**: Inactive access
- **Revoked**: Access was revoked
- **Expired**: Access expired (time-based)
- **Pending**: Access pending activation

### Utility Functions
**Location**: `myApp/utils/access.py`

#### `has_course_access(user, course)`
- **Returns**: `(has_access: bool, access_record: CourseAccess or None, reason: str)`
- **Checks**: Active access, expiration, revocation

#### `grant_course_access(user, course, access_type, ...)`
- **Returns**: Created `CourseAccess` object
- **Tracks**: Source, grantor, timestamp, expiration

#### `revoke_course_access(user, course, revoked_by, reason, notes)`
- **Returns**: Updated `CourseAccess` object
- **Updates**: Status to 'revoked', tracks revoker, reason, timestamp

#### `get_user_accessible_courses(user)`
- **Returns**: QuerySet of courses user has active access to

#### `get_courses_by_visibility(user)`
- **Returns**: Dict with keys: 'my_courses', 'available_to_unlock', 'not_available'

#### `check_course_prerequisites(user, course)`
- **Returns**: `(met: bool, missing_prerequisites: list)`
- **Checks**: Prerequisite courses completion

#### `grant_bundle_access(user, bundle_purchase)`
- **Grants**: Access to all courses in bundle
- **Creates**: CourseAccess records for each course

---

## Quiz System

### Quiz Structure
1. **LessonQuiz**: Container for quiz
   - Title, description
   - Is required (blocks lesson completion)
   - Passing score (0-100%)

2. **LessonQuizQuestion**: Individual questions
   - Question text
   - 2-4 options (A, B, C, D)
   - Correct answer
   - Order

3. **LessonQuizAttempt**: Student attempts
   - Score percentage
   - Pass/fail status
   - Completion timestamp

### Quiz Creation Methods

#### 1. Manual Creation
- Admin creates quiz via dashboard
- Add questions one by one
- Edit questions via modal

#### 2. File Upload
- **CSV Format**:
  ```csv
  question,option_a,option_b,option_c,option_d,correct_answer
  "What is 2+2?","3","4","5","6","B"
  ```
- **PDF Format**: Parsed PDF with numbered questions and options

#### 3. AI Generation
- Uses OpenAI API
- Analyzes lesson content (title, description, transcription)
- Generates questions based on content
- Configurable number of questions (3, 5, 10, 15)

### Quiz Flow
1. Student views lesson
2. If quiz exists and is required, lesson completion is blocked
3. Student takes quiz
4. Answers are submitted
5. Score is calculated
6. Pass/fail is determined
7. If passed, lesson can be completed
8. If failed, student can retake (no limit)

---

## Progress Tracking

### Video Progress Tracking
**Implementation**: JavaScript tracks video playback events

1. **Video Player Integration**: 
   - Vimeo: Uses Vimeo Player API
   - Google Drive: Uses iframe events
   - Generic: Uses HTML5 video events

2. **Progress Updates**:
   - Sends periodic updates to `/api/lessons/<id>/progress/`
   - Updates `video_watch_percentage` (0-100%)
   - Updates `last_watched_timestamp` (seconds)
   - Updates `last_accessed` (auto-updated)

3. **Automatic Status Updates**:
   - `update_status()` method called on save
   - If `video_watch_percentage >= video_completion_threshold` (90%):
     - Status → 'completed'
     - `completed = True`
     - `completed_at = now()`
   - If `video_watch_percentage > 0`:
     - Status → 'in_progress'
     - `started_at = now()` (if not set)
   - Otherwise:
     - Status → 'not_started'

### Lesson Completion
**Endpoint**: `/api/lessons/<id>/complete/`

1. **Validation**:
   - Checks if required quiz exists
   - Checks if quiz is passed
   - Blocks completion if quiz not passed

2. **Completion**:
   - Creates/updates `UserProgress`
   - Sets `completed = True`
   - Sets `status = 'completed'`
   - Sets `completed_at = now()`
   - Sets `progress_percentage = 100`

3. **Navigation**:
   - Automatically redirects to next lesson if available
   - Shows completion message if no next lesson

---

## Certifications & Exams

### Certification Flow
1. **Eligibility Check**:
   - Course must be completed (all lessons)
   - Exam must be available (based on payment type and days)
   - Exam must be passed (if exists)

2. **Exam Attempt**:
   - Student takes exam
   - Score is calculated
   - Pass/fail is determined
   - Attempt is tracked

3. **Certification Generation**:
   - If exam passed, certification is issued
   - Accredible certificate ID is generated (if configured)
   - Certificate URL is created
   - `status = 'passed'`
   - `issued_at = now()`

### Trophy System
**Unlockable Tiers**:
1. **Bronze**: 1 certification
2. **Silver**: 2 certifications
3. **Gold**: 3 certifications
4. **Platinum**: 5 certifications
5. **Diamond**: 10 certifications
6. **Ultimate**: 20+ certifications

**Implementation**: Static SVG icons, unlocked based on `user_cert_count`

---

## Integrations

### 1. Vimeo Integration
- **Video Hosting**: Vimeo video URLs
- **Metadata Extraction**: Vimeo ID, thumbnail, duration
- **Embed Player**: Vimeo embed iframe
- **Progress Tracking**: Vimeo Player API events
- **Resume Playback**: Saves and resumes from last watched timestamp

**Fields**:
- `vimeo_url`: Full Vimeo URL
- `vimeo_id`: Extracted ID
- `vimeo_thumbnail`: Thumbnail URL
- `vimeo_duration_seconds`: Duration

### 2. Google Drive Integration
- **Video Hosting**: Google Drive video URLs
- **Embed Support**: Google Drive embed iframe
- **File ID Extraction**: Google Drive file ID

**Fields**:
- `google_drive_url`: Google Drive embed URL
- `google_drive_id`: File ID

### 3. Cloudinary Integration
- **Image Hosting**: Course thumbnails, assets
- **Video Hosting**: Alternative video hosting
- **URL Format**: `https://res.cloudinary.com/<cloud_name>/...`

### 4. OpenAI Integration
- **Quiz Generation**: Generates quiz questions from lesson content
- **Lesson Generation**: Generates lesson descriptions, outcomes, actions
- **Chatbot**: AI assistant for lesson assistance
- **API Key**: `OPENAI_API_KEY` environment variable

**Functions**:
- `generate_ai_quiz(lesson, quiz, num_questions)`: Generate quiz questions
- `generate_lesson_ai(...)`: Generate lesson content

### 5. Accredible Integration
- **Certificates**: Accredible certificate generation
- **Certificate IDs**: `accredible_certificate_id`
- **Certificate URLs**: `accredible_certificate_url`
- **Status**: Integration status tracking

---

## Frontend Components

### Landing Page
**Template**: `landing.html`

**Sections**:
1. **Hero Section** (`_hero.html`):
   - Background video (Cloudinary)
   - Purple-to-light gradient overlay
   - Left-aligned content
   - Login/Join buttons
   - Floating purple/blue blobs

2. **Program Highlights** (`_highlights.html`):
   - Background image (Cloudinary)
   - Course features
   - Floating blobs

3. **About** (`_about.html`):
   - About content
   - Text balance (no orphan words)
   - Floating blobs

4. **Community** (`_community.html`):
   - Community features
   - Floating blobs

5. **Results** (`_results.html`):
   - Success stories
   - Floating blobs

6. **How It Works** (`_how_it_works.html`):
   - Process steps
   - Floating blobs

7. **Join** (`_join.html`):
   - Call to action
   - Floating blobs

**JavaScript** (`_scripts.html`):
- Staggered fade-in animations
- Parallax video effect
- Mouse cursor glow
- Floating particles/blobs
- Animated gradient text
- Magnetic buttons
- Video speed control
- Page load transition
- Scroll-triggered animations

### Course Cards
- **Thumbnail**: Course thumbnail image
- **Title**: Course name
- **Description**: Short description
- **Progress Bar**: Visual progress indicator
- **Favorite Button**: Heart icon
- **Action Buttons**: Start/Continue/View Progress
- **Status Badges**: Active, Locked, Coming Soon
- **Certification Status**: Eligible, Certified, Not Eligible

### Video Player
- **Multiple Sources**: Vimeo, Google Drive, Cloudinary
- **Responsive**: Aspect ratio maintained
- **Progress Tracking**: Real-time progress updates
- **Resume Playback**: Auto-resume from last position
- **Completion Button**: Mark lesson complete
- **Next/Previous**: Navigation to adjacent lessons

### Quiz Interface
- **Question Display**: Numbered questions
- **Multiple Choice**: Radio buttons for options
- **Required Quiz**: Blocks lesson completion
- **Score Display**: Shows score after submission
- **Pass/Fail**: Visual feedback
- **Confetti Animation**: Celebratory animation on pass

### Preloaders
- **Universal Preloader**: Full-screen overlay
  - Animated spinner (cyan/purple gradient)
  - Dynamic text
  - Backdrop blur
- **AI Generation Preloader**: Special preloader for AI operations
  - Robot icon
  - "AI is Generating..." text
  - Animated progress bar
- **Inline Loaders**: Spinner icons for favorite toggles

---

## Utilities & Helper Functions

### Access Control Utilities
**Location**: `myApp/utils/access.py`

See [Access Control System](#access-control-system) section for details.

### Transcription Utilities
**Location**: `myApp/utils/transcription.py`

#### `transcribe_video(video_file_path)`
- **Purpose**: Transcribe video to text
- **Returns**: `{'success': bool, 'transcription': str, 'error': str}`
- **Status**: Placeholder (configurable with OpenAI Whisper, AssemblyAI, etc.)

#### `extract_audio_from_video(video_path, audio_path)`
- **Purpose**: Extract audio from video using ffmpeg
- **Requirements**: ffmpeg installed
- **Returns**: `bool` (success/failure)

### Management Commands
**Location**: `myApp/management/commands/`

#### `seed_data.py`
- **Purpose**: Seed database with main course and lessons
- **Usage**: `python manage.py seed_data`
- **Creates**: Admin user, "VIRTUAL ROCKSTAR™" course, 12 lessons

#### `seed_additional_courses.py`
- **Purpose**: Seed additional sample courses
- **Usage**: `python manage.py seed_additional_courses`
- **Creates**: 2 additional courses with lessons

#### `seed_lesson1_quiz.py`
- **Purpose**: Seed quiz for Lesson 1
- **Usage**: `python manage.py seed_lesson1_quiz`
- **Creates**: Quiz with 3 questions

#### `add_google_drive.py`
- **Purpose**: Add Google Drive URLs to lessons
- **Usage**: `python manage.py add_google_drive`

#### `check_videos.py`
- **Purpose**: Check video URLs and metadata
- **Usage**: `python manage.py check_videos`

#### `fix_vimeo_ids.py`
- **Purpose**: Fix Vimeo ID extraction
- **Usage**: `python manage.py fix_vimeo_ids`

#### `fix_video_urls.py`
- **Purpose**: Fix video URL formats
- **Usage**: `python manage.py fix_video_urls`

---

## Setup & Configuration

### Environment Variables
**File**: `.env`

```env
# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com

# Database
DATABASE_URL=postgresql://user:password@host:port/dbname
# Or for SQLite (development):
# DATABASE_URL=sqlite:///db.sqlite3

# OpenAI (for AI features)
OPENAI_API_KEY=sk-...

# Cloudinary (for media hosting)
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# Accredible (for certificates)
ACCREDIBLE_API_KEY=your-accredible-key
ACCREDIBLE_GROUP_ID=your-group-id
```

### Required Packages
**File**: `requirements.txt`

```txt
Django==5.1.2
django-environ==0.11.2
dj-database-url==2.3.0
openai==1.54.0
python-dotenv==1.0.1
Pillow==11.0.0
cloudinary==1.45.0
```

### Database Setup
1. **Create Database**:
   ```bash
   # PostgreSQL
   createdb course_system_db
   
   # Or use DATABASE_URL
   ```

2. **Run Migrations**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

3. **Create Superuser**:
   ```bash
   python manage.py createsuperuser
   ```

4. **Seed Data** (optional):
   ```bash
   python manage.py seed_data
   python manage.py seed_additional_courses
   python manage.py seed_lesson1_quiz
   ```

### Static Files
```bash
python manage.py collectstatic
```

### Media Files
- **Local**: `MEDIA_ROOT` in settings
- **Cloudinary**: Configured via environment variables

---

## Deployment

### Railway Deployment
1. **Environment Variables**: Set all required env vars
2. **Database**: Use Railway PostgreSQL addon
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `python manage.py migrate && python manage.py collectstatic --noinput && gunicorn myProject.wsgi:application`

### Production Checklist
- [ ] Set `DEBUG = False`
- [ ] Set `SECRET_KEY` (strong, random)
- [ ] Configure `ALLOWED_HOSTS`
- [ ] Set up `CSRF_TRUSTED_ORIGINS`
- [ ] Use PostgreSQL database
- [ ] Set up Cloudinary for media
- [ ] Configure OpenAI API key
- [ ] Set up SSL/HTTPS
- [ ] Configure static file serving (WhiteNoise or CDN)
- [ ] Set up error logging (Sentry, etc.)
- [ ] Configure email backend (for notifications)
- [ ] Set up monitoring (Uptime monitoring)

### Database Migrations
```bash
# Create migration
python manage.py makemigrations

# Apply migration
python manage.py migrate

# Rollback (if needed)
python manage.py migrate app_name migration_number
```

---

## Key Design Patterns

### 1. Explicit Access Control
- Every access is a `CourseAccess` record
- No implicit access (e.g., "if enrolled, then access")
- Full audit trail

### 2. Status-Based Workflows
- Progress tracking uses status fields
- Automatic status updates via methods
- Clear state transitions

### 3. Utility Functions
- Access control logic in `utils/access.py`
- Reusable functions for common operations
- Single source of truth

### 4. Model Methods
- Business logic in model methods
- `update_status()`, `is_active()`, etc.
- Reduces code duplication

### 5. API Endpoints
- RESTful API design
- JSON responses
- Error handling

---

## Future Enhancements

### Planned Features
1. **Video Transcription**: Implement actual transcription service
2. **Payment Integration**: Stripe/PayPal for course purchases
3. **Email Notifications**: Course completion, certification emails
4. **Social Sharing**: Share certificates, progress
5. **Mobile App**: React Native app for mobile access
6. **Live Sessions**: Integration with Zoom/Google Meet
7. **Discussion Forums**: Course-specific discussions
8. **Assignments**: File upload assignments
9. **Gamification**: Points, badges, leaderboards
10. **Advanced Analytics**: Predictive analytics, recommendations

### Technical Improvements
1. **Caching**: Redis caching for frequently accessed data
2. **CDN**: CDN for static/media files
3. **Background Tasks**: Celery for async tasks (transcription, emails)
4. **API Versioning**: Versioned API endpoints
5. **Rate Limiting**: API rate limiting
6. **Search**: Elasticsearch for course/lesson search
7. **Notifications**: Real-time notifications (WebSockets)
8. **Multi-language**: i18n support

---

## Troubleshooting

### Common Issues

#### 1. Video Not Playing
- **Check**: Video URL format
- **Check**: CORS settings for iframe embeds
- **Check**: Video hosting service status

#### 2. Progress Not Updating
- **Check**: JavaScript console for errors
- **Check**: API endpoint is accessible
- **Check**: CSRF token is included in requests

#### 3. Access Not Working
- **Check**: `CourseAccess` record exists
- **Check**: Access status is 'unlocked'
- **Check**: Access hasn't expired
- **Check**: Access wasn't revoked

#### 4. Quiz Not Saving
- **Check**: Form validation
- **Check**: Database connection
- **Check**: Required fields are filled

#### 5. AI Generation Failing
- **Check**: `OPENAI_API_KEY` is set
- **Check**: OpenAI API quota
- **Check**: Lesson has enough content for generation

---

## Support & Maintenance

### Logging
- Django logging configured
- Error tracking (optional: Sentry)
- Activity logging for audits

### Backup Strategy
- Database backups (daily)
- Media file backups (Cloudinary handles)
- Migration history preserved

### Updates
- Regular Django updates
- Security patches
- Feature additions

---

## License & Credits

- **Framework**: Django 5.1.2
- **Frontend**: Tailwind CSS, Font Awesome
- **Video**: Vimeo, Google Drive, Cloudinary
- **AI**: OpenAI
- **Database**: PostgreSQL

---

**Document Version**: 1.0  
**Last Updated**: 2025-01-01  
**Maintained By**: Development Team

---

## Quick Reference

### URLs
- Landing: `/`
- Courses: `/courses/`
- Lesson: `/courses/<slug>/<lesson_slug>/`
- Quiz: `/courses/<slug>/<lesson_slug>/quiz/`
- Student Dashboard: `/my-dashboard/`
- Certifications: `/my-certifications/`
- Admin Dashboard: `/dashboard/`
- Analytics: `/dashboard/analytics/`

### API Endpoints
- Progress: `POST /api/lessons/<id>/progress/`
- Complete: `POST /api/lessons/<id>/complete/`
- Favorite: `POST /api/courses/<id>/favorite/`
- Chatbot: `POST /api/chatbot/`

### Key Models
- Course, Lesson, Module
- UserProgress, CourseAccess
- LessonQuiz, LessonQuizQuestion, LessonQuizAttempt
- Certification, Exam, ExamAttempt
- Bundle, BundlePurchase
- Cohort, CohortMember
- LearningPath

---

**End of Documentation**

