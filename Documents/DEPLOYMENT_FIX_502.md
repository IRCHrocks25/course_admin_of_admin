# Fix for 502 Error During AI Course Generation

## Problem
When generating a course using AI in production, the request was timing out with a 502 error. The logs showed:
```
[CRITICAL] WORKER TIMEOUT (pid:50)
```

This happened because:
1. The AI course generation makes many synchronous OpenAI API calls (1 for course structure + 2 per lesson)
2. With 12-30 lessons, that's 25-61 API calls total
3. Gunicorn's default timeout is 30 seconds, which was insufficient

## Solution Implemented

### 1. Gunicorn Configuration File
Created `gunicorn_config.py` with increased timeout (5 minutes) to handle long-running requests.

**To use the config file, update your Railway start command:**
```bash
python manage.py migrate && python manage.py collectstatic --noinput && gunicorn myProject.wsgi:application -c gunicorn_config.py
```

Or if using environment variables in Railway:
- Set `GUNICORN_CMD_ARGS` to `-c gunicorn_config.py`

### 2. Background Thread Processing
Modified `dashboard_add_course` view to process AI generation in a background thread instead of synchronously. This means:
- The course is created immediately
- The HTTP request returns right away (no timeout)
- AI generation happens in the background
- Users see a message that generation is in progress

## Changes Made

1. **gunicorn_config.py** - New file with timeout configuration
2. **myApp/dashboard_views.py** - Modified to use background threading for AI generation

## Deployment Steps

1. **Update Railway Start Command:**
   - Go to Railway project settings
   - Update the start command to:
     ```
     python manage.py migrate && python manage.py collectstatic --noinput && gunicorn myProject.wsgi:application -c gunicorn_config.py
     ```

2. **Deploy the changes:**
   - The code changes are already in place
   - Just update the start command in Railway

## How It Works Now

1. User submits course creation form with AI generation enabled
2. Course is created immediately in the database
3. Background thread starts processing AI generation
4. User sees success message: "AI content generation has started in the background"
5. User can navigate away or refresh the course page later to see generated content
6. Background thread completes generation (may take 2-5 minutes depending on number of lessons)

## Monitoring

- Check application logs for background thread messages:
  - `[Background] Successfully generated AI content...`
  - `[Background] Error generating AI content...`

## Alternative: Using Celery (Future Enhancement)

For production at scale, consider using Celery for background tasks instead of threads:
- More robust error handling
- Task retry capabilities
- Better monitoring
- Distributed task processing

Celery is already in `requirements.txt`, so it can be set up when needed.

