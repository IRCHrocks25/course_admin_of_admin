# Live Student Activity Feedback System - Technical Documentation

## Overview
This document explains how the live feedback system tracks and displays real-time student activity, including lesson completions, progress updates, exam attempts, and certifications.

---

## Table of Contents
1. [System Architecture](#system-architecture)
2. [Data Models](#data-models)
3. [Progress Tracking](#progress-tracking)
4. [Activity Feed Generation](#activity-feed-generation)
5. [Frontend Display](#frontend-display)
6. [Auto-Refresh Mechanism](#auto-refresh-mechanism)
7. [API Endpoints](#api-endpoints)
8. [How It Works - Step by Step](#how-it-works---step-by-step)

---

## System Architecture

### Components
1. **UserProgress Model** - Tracks individual lesson progress
2. **Activity Feed Function** - Aggregates activities from multiple sources
3. **API Endpoints** - Receive progress updates from frontend
4. **Dashboard Views** - Display activity feed to admins
5. **Auto-Refresh JavaScript** - Updates feed without page reload

### Data Flow
```
Student watches video → JavaScript tracks progress → API endpoint updates database 
→ Activity feed function aggregates → Dashboard displays → Auto-refresh updates view
```

---

## Data Models

### UserProgress Model
**Location:** `myApp/models.py`

**Key Fields:**
- `user` - ForeignKey to User
- `lesson` - ForeignKey to Lesson
- `status` - Choices: 'not_started', 'in_progress', 'completed'
- `completed` - Boolean flag
- `completed_at` - DateTime when lesson was completed
- `video_watch_percentage` - Float (0-100) tracking how much video was watched
- `last_watched_timestamp` - Float (seconds) last position in video
- `video_completion_threshold` - Float (default 90%) required to mark complete
- `last_accessed` - DateTime (auto-updated) for tracking recent activity
- `progress_percentage` - Integer (0-100) overall lesson progress

**Key Method:**
```python
def update_status(self):
    """Automatically update status based on progress"""
    if self.video_watch_percentage >= self.video_completion_threshold:
        self.status = 'completed'
        self.completed = True
        if not self.completed_at:
            self.completed_at = timezone.now()
    elif self.video_watch_percentage > 0:
        self.status = 'in_progress'
        if not self.started_at:
            self.started_at = timezone.now()
    else:
        self.status = 'not_started'
    self.save()
```

**How It Works:**
- Automatically updates lesson status based on video watch percentage
- Marks as completed when 90% of video is watched (configurable threshold)
- Sets timestamps for tracking when lessons were started/completed

---

## Progress Tracking

### 1. Video Progress Tracking (Real-time)

**Endpoint:** `POST /api/lessons/<lesson_id>/progress/`

**Location:** `myApp/views.py` - `update_video_progress()`

**How It Works:**
1. **Frontend JavaScript** tracks video playback:
   - Monitors video `timeupdate` events
   - Calculates watch percentage: `(currentTime / duration) * 100`
   - Sends periodic updates to backend (typically every 5-10 seconds)

2. **Backend Processing:**
   ```python
   def update_video_progress(request, lesson_id):
       # Receives JSON data:
       # {
       #   "watch_percentage": 45.5,
       #   "timestamp": 120.5  # seconds into video
       # }
       
       # Gets or creates UserProgress record
       user_progress, created = UserProgress.objects.get_or_create(
           user=request.user,
           lesson=lesson,
           defaults={...}
       )
       
       # Updates progress fields
       user_progress.video_watch_percentage = watch_percentage
       user_progress.last_watched_timestamp = timestamp
       user_progress.progress_percentage = int(watch_percentage)
       
       # Auto-updates status (not_started → in_progress → completed)
       user_progress.update_status()
   ```

3. **Automatic Status Updates:**
   - When `video_watch_percentage >= 90%` → Status becomes 'completed'
   - When `video_watch_percentage > 0` → Status becomes 'in_progress'
   - Sets `completed_at` timestamp when threshold is reached

**Key Features:**
- ✅ Real-time tracking (updates every few seconds)
- ✅ Automatic completion detection (90% threshold)
- ✅ Tracks exact video position
- ✅ Updates `last_accessed` timestamp for activity feed

### 2. Manual Lesson Completion

**Endpoint:** `POST /api/lessons/<lesson_id>/complete/`

**Location:** `myApp/views.py` - `complete_lesson()`

**How It Works:**
1. Student clicks "Mark as Complete" button
2. System checks if lesson has required quiz:
   - If quiz exists and is required → Must pass quiz first
   - If no quiz or quiz passed → Proceeds with completion
3. Marks lesson as completed:
   ```python
   user_progress.completed = True
   user_progress.status = 'completed'
   user_progress.completed_at = datetime.now()
   user_progress.progress_percentage = 100
   ```

**Quiz Requirement:**
- If lesson has `LessonQuiz` with `is_required=True`
- System checks for passed quiz attempt before allowing completion
- Returns error if quiz not passed

---

## Activity Feed Generation

### Function: `get_student_activity_feed()`

**Location:** `myApp/dashboard_views.py`

**Purpose:** Aggregates all student activities into a unified feed

**Data Sources:**

#### 1. Lesson Completions
```python
recent_completions = UserProgress.objects.filter(
    completed=True,
    completed_at__isnull=False
).select_related('user', 'lesson', 'lesson__course').order_by('-completed_at')[:limit]

# Creates activity:
{
    'type': 'lesson_completed',
    'timestamp': progress.completed_at,
    'user': progress.user,
    'course': progress.lesson.course,
    'lesson': progress.lesson,
    'data': {
        'watch_percentage': progress.video_watch_percentage,
    }
}
```

#### 2. Exam Attempts
```python
recent_exams = ExamAttempt.objects.select_related(
    'user', 'exam', 'exam__course'
).order_by('-started_at')[:limit]

# Creates activity:
{
    'type': 'exam_attempt',
    'timestamp': attempt.started_at,
    'user': attempt.user,
    'course': attempt.exam.course,
    'data': {
        'score': attempt.score,
        'passed': attempt.passed,
        'attempt_number': attempt.attempt_number(),
    }
}
```

#### 3. Certifications Issued
```python
recent_certs = Certification.objects.filter(
    issued_at__isnull=False
).select_related('user', 'course').order_by('-issued_at')[:limit]

# Creates activity:
{
    'type': 'certification_issued',
    'timestamp': cert.issued_at,
    'user': cert.user,
    'course': cert.course,
    'data': {
        'certificate_id': cert.accredible_certificate_id,
    }
}
```

#### 4. Progress Updates (Significant Progress Only)
```python
recent_progress = UserProgress.objects.filter(
    video_watch_percentage__gt=0,
    last_accessed__isnull=False
).select_related('user', 'lesson', 'lesson__course').order_by('-last_accessed')[:limit]

# Only includes if:
# - Watch percentage >= 50% OR
# - Lesson is completed
# (This prevents spam from minor progress updates)

# Creates activity:
{
    'type': 'progress_update',
    'timestamp': progress.last_accessed,
    'user': progress.user,
    'course': progress.lesson.course,
    'lesson': progress.lesson,
    'data': {
        'watch_percentage': progress.video_watch_percentage,
        'status': progress.status,
    }
}
```

**Sorting:**
- All activities are sorted by timestamp (most recent first)
- Returns top N activities (default: 20, configurable)

**Performance Optimizations:**
- Uses `select_related()` to avoid N+1 queries
- Limits results per source before combining
- Filters out insignificant progress updates (<50%)

---

## Frontend Display

### Dashboard Home Page
**Location:** `myApp/templates/dashboard/home.html`

**Features:**
- Shows last 10 activities in sidebar
- Color-coded icons by activity type:
  - 🟢 Green: Lesson completed
  - 🟣 Purple: Exam attempt
  - 🟡 Yellow: Certification issued
  - 🔵 Cyan: Progress update

**Display Format:**
```html
<div class="flex items-start gap-3">
    <!-- Icon based on activity type -->
    <div class="w-8 h-8 rounded-lg bg-green-500/20 text-green-400">
        <i class="fas fa-check-circle"></i>
    </div>
    
    <!-- Activity details -->
    <div>
        <span class="font-semibold">Student Name</span>
        completed <span class="text-cyan-electric">Lesson Title</span>
        <div class="text-xs text-gray-400">
            <i class="fas fa-clock"></i> 5 minutes ago
        </div>
    </div>
</div>
```

### Students Page - Full Activity Feed
**Location:** `myApp/templates/dashboard/students.html`

**Features:**
- Shows up to 50 activities
- Scrollable feed with timeline design
- More detailed information:
  - Watch percentage for lessons
  - Exam scores and attempt numbers
  - Certificate IDs
  - Course and lesson context

**Visual Design:**
- Timeline-style layout with left border
- Color-coded activity types
- Hover effects for better UX
- Badges showing additional data (scores, percentages)

---

## Auto-Refresh Mechanism

### Implementation
**Location:** `myApp/templates/dashboard/students.html`

**JavaScript Code:**
```javascript
// Auto-refresh activity feed every 30 seconds
setInterval(function() {
    // Only refresh if page is visible
    if (!document.hidden) {
        // Fetch updated page content
        fetch(window.location.href)
            .then(response => response.text())
            .then(html => {
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, 'text/html');
                const newFeed = doc.getElementById('activity-feed');
                
                if (newFeed) {
                    // Update only the activity feed section
                    document.getElementById('activity-feed').innerHTML = newFeed.innerHTML;
                }
            })
            .catch(error => console.error('Error refreshing feed:', error));
    }
}, 30000); // 30 seconds
```

**How It Works:**
1. **Interval Timer:** Runs every 30 seconds
2. **Visibility Check:** Only refreshes if page is visible (not in background tab)
3. **Fetch Strategy:** Fetches entire page HTML
4. **DOM Parsing:** Extracts only the activity feed section
5. **Selective Update:** Updates only the feed div, not entire page
6. **Error Handling:** Catches and logs errors without breaking page

**Benefits:**
- ✅ No page reload required
- ✅ Smooth user experience
- ✅ Only updates when page is visible (saves resources)
- ✅ Non-intrusive (doesn't interrupt user)

**Alternative Approach (Future Enhancement):**
Could use WebSockets or Server-Sent Events (SSE) for real-time updates without polling.

---

## API Endpoints

### 1. Update Video Progress
**Endpoint:** `POST /api/lessons/<lesson_id>/progress/`

**Request Body:**
```json
{
    "watch_percentage": 45.5,
    "timestamp": 120.5
}
```

**Response:**
```json
{
    "success": true,
    "watch_percentage": 45.5,
    "status": "in_progress",
    "completed": false
}
```

**Usage:**
- Called automatically by frontend JavaScript
- Typically every 5-10 seconds during video playback
- Updates progress in real-time

### 2. Complete Lesson
**Endpoint:** `POST /api/lessons/<lesson_id>/complete/`

**Request Body:** Empty (uses authenticated user)

**Response:**
```json
{
    "success": true,
    "message": "Lesson marked as complete",
    "lesson_id": 123
}
```

**Error Response (if quiz required):**
```json
{
    "success": false,
    "error": "You must pass the lesson quiz before completing this lesson.",
    "quiz_required": true,
    "quiz_url": "/courses/course-slug/lesson-slug/quiz/"
}
```

**Usage:**
- Called when student clicks "Mark as Complete" button
- Validates quiz requirements if applicable
- Marks lesson as completed immediately

---

## How It Works - Step by Step

### Scenario: Student Watches a Lesson

#### Step 1: Student Opens Lesson
1. Student navigates to lesson page
2. Video player loads
3. JavaScript initializes progress tracking

#### Step 2: Video Playback Begins
1. Student starts watching video
2. JavaScript `timeupdate` event fires
3. Calculates watch percentage: `(currentTime / duration) * 100`
4. Sends first progress update to API

#### Step 3: Progress Updates (Every 5-10 seconds)
1. JavaScript continues tracking video position
2. Sends periodic updates to `/api/lessons/<id>/progress/`
3. Backend updates `UserProgress` record:
   - Updates `video_watch_percentage`
   - Updates `last_watched_timestamp`
   - Updates `last_accessed` (auto-updated)
   - Calls `update_status()` to check if threshold reached

#### Step 4: Threshold Reached (90% watched)
1. `update_status()` detects `video_watch_percentage >= 90%`
2. Automatically sets:
   - `status = 'completed'`
   - `completed = True`
   - `completed_at = timezone.now()`
3. Lesson is now marked as complete

#### Step 5: Activity Feed Update
1. `get_student_activity_feed()` function runs (when dashboard loads)
2. Queries `UserProgress` for recent completions
3. Finds the newly completed lesson
4. Creates activity entry:
   ```python
   {
       'type': 'lesson_completed',
       'timestamp': completed_at,
       'user': student,
       'course': course,
       'lesson': lesson,
       'data': {'watch_percentage': 92.5}
   }
   ```

#### Step 6: Dashboard Display
1. Dashboard template receives activity feed
2. Renders activity in feed section
3. Shows: "Student Name completed Lesson Title"
4. Displays timestamp: "5 minutes ago"

#### Step 7: Auto-Refresh
1. JavaScript timer fires after 30 seconds
2. Fetches updated page content
3. Extracts new activity feed
4. Updates feed section without page reload
5. New activities appear automatically

---

## Activity Types

### 1. Lesson Completed
**Trigger:** When `video_watch_percentage >= 90%` OR manual completion

**Display:**
- 🟢 Green icon with checkmark
- Shows: "Student completed Lesson Title"
- Includes watch percentage badge
- Timestamp: When lesson was completed

### 2. Exam Attempt
**Trigger:** When student submits exam

**Display:**
- 🟣 Purple icon with clipboard
- Shows: "Student passed/attempted exam for Course Name"
- Includes score and attempt number
- Timestamp: When exam was submitted

### 3. Certification Issued
**Trigger:** When certification is issued (after passing exam)

**Display:**
- 🟡 Yellow icon with certificate
- Shows: "Student earned certification for Course Name"
- Includes certificate ID if available
- Timestamp: When certification was issued

### 4. Progress Update
**Trigger:** When student watches >=50% of video OR completes lesson

**Display:**
- 🔵 Cyan icon with chart
- Shows: "Student updated progress in Lesson Title"
- Includes watch percentage badge
- Timestamp: Last accessed time

---

## Data Flow Diagram

```
┌─────────────────┐
│  Student Browser │
│  (Video Player)  │
└────────┬────────┘
         │
         │ JavaScript tracks video
         │ Sends progress every 5-10s
         ▼
┌─────────────────┐
│  API Endpoint   │
│ /api/lessons/   │
│ <id>/progress/  │
└────────┬────────┘
         │
         │ Updates UserProgress
         │ Auto-updates status
         ▼
┌─────────────────┐
│   Database      │
│  UserProgress   │
│     Model       │
└────────┬────────┘
         │
         │ Queried by
         │ get_student_activity_feed()
         ▼
┌─────────────────┐
│ Dashboard View  │
│  (dashboard_    │
│   analytics)    │
└────────┬────────┘
         │
         │ Renders template
         │ with activity feed
         ▼
┌─────────────────┐
│  Admin Dashboard │
│  (Activity Feed) │
└─────────────────┘
         │
         │ Auto-refresh
         │ every 30 seconds
         ▼
┌─────────────────┐
│ Updated Feed    │
│ (No page reload)│
└─────────────────┘
```

---

## Key Features

### ✅ Real-Time Tracking
- Progress updates every 5-10 seconds during video playback
- No manual refresh needed
- Automatic completion detection

### ✅ Automatic Status Updates
- Status changes automatically based on watch percentage
- Sets timestamps for tracking
- Handles edge cases (0%, partial, complete)

### ✅ Activity Aggregation
- Combines multiple activity types
- Sorted by timestamp (most recent first)
- Filters out insignificant updates

### ✅ Live Dashboard Updates
- Auto-refreshes every 30 seconds
- Only updates when page is visible
- Smooth, non-intrusive updates

### ✅ Comprehensive Tracking
- Tracks video watch percentage
- Tracks exact video position
- Tracks completion timestamps
- Tracks last access times

---

## Configuration

### Video Completion Threshold
**Location:** `UserProgress.video_completion_threshold`

**Default:** 90%

**How to Change:**
```python
# In models.py or migration
video_completion_threshold = models.FloatField(
    default=90.0,
    help_text="Required watch percentage to complete (default 90%)"
)
```

**Per-Lesson Override:**
Can be customized per lesson if needed (future enhancement)

### Auto-Refresh Interval
**Location:** `myApp/templates/dashboard/students.html`

**Current:** 30 seconds (30000ms)

**How to Change:**
```javascript
setInterval(function() {
    // ... refresh code ...
}, 30000); // Change this number (milliseconds)
```

### Activity Feed Limit
**Location:** `get_student_activity_feed(limit=20)`

**Default:** 20 activities

**Usage:**
```python
# Dashboard home: 10 activities
student_activities = get_student_activity_feed(limit=10)

# Students page: 50 activities
activity_feed = get_student_activity_feed(limit=50)
```

### Progress Update Filter
**Location:** `get_student_activity_feed()` function

**Current Filter:** Only shows progress if `watch_percentage >= 50%` OR `completed=True`

**Purpose:** Prevents spam from minor progress updates

---

## Performance Considerations

### Database Queries
- Uses `select_related()` to avoid N+1 queries
- Limits results per source before combining
- Orders by indexed fields (`completed_at`, `started_at`, `last_accessed`)

### Caching Opportunities
- Activity feed could be cached for 30 seconds (matches refresh interval)
- Could use Redis for real-time activity streaming
- Could pre-calculate common queries

### Optimization Tips
1. **Index Database Fields:**
   ```python
   # Add indexes to UserProgress model
   class Meta:
       indexes = [
           models.Index(fields=['-completed_at']),
           models.Index(fields=['-last_accessed']),
           models.Index(fields=['user', 'completed']),
       ]
   ```

2. **Batch Updates:**
   - Current: Updates on every progress call
   - Could batch updates (e.g., only update if change > 5%)

3. **Pagination:**
   - Current: Loads all activities at once
   - Could paginate for better performance with many students

---

## Future Enhancements

### 1. Real-Time WebSocket Updates
- Replace polling with WebSocket connections
- Push updates immediately when activities occur
- Better performance and real-time feel

### 2. Activity Notifications
- Email/SMS notifications for significant milestones
- Push notifications for admins
- Student achievement notifications

### 3. Advanced Filtering
- Filter by activity type
- Filter by date range
- Filter by course/student
- Search functionality

### 4. Analytics Integration
- Track activity patterns
- Identify peak activity times
- Analyze engagement metrics
- Predict completion rates

### 5. Student-Facing Activity Feed
- Show students their own activity history
- Display achievements and milestones
- Social features (if applicable)

---

## Troubleshooting

### Issue: Activities Not Appearing
**Possible Causes:**
1. `completed_at` is NULL (only shows if timestamp exists)
2. Progress updates < 50% (filtered out)
3. Auto-refresh not working (check JavaScript console)
4. Database not updating (check API responses)

**Solutions:**
- Check `UserProgress.completed_at` field
- Verify API endpoints are being called
- Check browser console for JavaScript errors
- Verify database updates are happening

### Issue: Auto-Refresh Not Working
**Possible Causes:**
1. JavaScript disabled
2. Page visibility API not supported
3. Network errors
4. CORS issues

**Solutions:**
- Check browser console for errors
- Verify JavaScript is enabled
- Check network tab for failed requests
- Test in different browser

### Issue: Progress Not Updating
**Possible Causes:**
1. Video player not sending updates
2. API endpoint errors
3. Authentication issues
4. Database connection problems

**Solutions:**
- Check browser network tab for API calls
- Verify user is authenticated
- Check API response for errors
- Verify database is accessible

---

## Code Locations Summary

| Component | File | Function/Class |
|-----------|------|----------------|
| Progress Model | `myApp/models.py` | `UserProgress` |
| Progress Tracking API | `myApp/views.py` | `update_video_progress()` |
| Completion API | `myApp/views.py` | `complete_lesson()` |
| Activity Feed | `myApp/dashboard_views.py` | `get_student_activity_feed()` |
| Dashboard Display | `myApp/templates/dashboard/home.html` | Activity feed section |
| Students Page Feed | `myApp/templates/dashboard/students.html` | Full activity feed |
| Auto-Refresh JS | `myApp/templates/dashboard/students.html` | `setInterval()` function |

---

## Testing the System

### Manual Testing Steps

1. **Test Video Progress Tracking:**
   - Open a lesson as a student
   - Watch video for 30+ seconds
   - Check browser Network tab for `/api/lessons/<id>/progress/` calls
   - Verify updates are being sent

2. **Test Completion Detection:**
   - Watch video to 90%+
   - Check database: `UserProgress.completed` should be `True`
   - Check `completed_at` timestamp is set

3. **Test Activity Feed:**
   - Complete a lesson as a student
   - Go to dashboard as admin
   - Check activity feed for new entry
   - Wait 30 seconds, verify auto-refresh works

4. **Test Multiple Activity Types:**
   - Complete a lesson → Should show "lesson_completed"
   - Take an exam → Should show "exam_attempt"
   - Earn certification → Should show "certification_issued"
   - Watch 50%+ of video → Should show "progress_update"

---

## Summary

The live feedback system provides real-time visibility into student activity through:

1. **Automatic Progress Tracking** - JavaScript tracks video playback and sends updates
2. **Smart Status Updates** - System automatically marks lessons complete at 90% threshold
3. **Activity Aggregation** - Combines multiple activity sources into unified feed
4. **Live Dashboard Updates** - Auto-refreshes every 30 seconds without page reload
5. **Comprehensive Tracking** - Tracks lessons, exams, certifications, and progress

This system enables administrators to:
- Monitor student engagement in real-time
- Identify students who need support
- Track course completion rates
- Celebrate student achievements
- Make data-driven decisions

---

**Document Version:** 1.0  
**Date:** 2025-01-27  
**Status:** Complete

