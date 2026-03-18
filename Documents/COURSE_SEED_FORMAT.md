# Course and Lesson Seed File Format

This document explains the format for seeding courses and lessons into the database.

## File Format: JSON

The seed file should be a JSON file with the following structure:

## Course Fields

| Field | Type | Required | Description | Options/Examples |
|-------|------|----------|-------------|------------------|
| `name` | string | Yes | Full course name | "Assets Mastery", "Financial Literacy" |
| `slug` | string | Yes | URL-friendly identifier (lowercase, hyphens) | "assets-mastery", "financial-literacy" |
| `course_type` | string | Yes | Type of course | `"sprint"`, `"speaking"`, `"consultancy"`, `"special"` |
| `status` | string | Yes | Course status | `"active"`, `"locked"`, `"coming_soon"` |
| `description` | string | Yes | Full course description | Long text describing the course |
| `short_description` | string | Yes | Short description (max 300 chars) | Brief summary for cards/previews |
| `coach_name` | string | Yes | Name of the coach/instructor | "Daniel Wood", "Expert Name" |
| `is_subscribers_only` | boolean | Yes | Subscriber-only access | `true` or `false` |
| `is_accredible_certified` | boolean | Yes | Offers certification | `true` or `false` |
| `has_asset_templates` | boolean | Yes | Includes asset templates | `true` or `false` |
| `exam_unlock_days` | integer | Yes | Days before exam unlocks | `120` (default) |
| `special_tag` | string | No | Special tag (e.g., "Black Friday") | `""` or tag text |
| `visibility` | string | Yes | Who can see the course | `"public"`, `"members_only"`, `"hidden"`, `"private"` |
| `enrollment_method` | string | Yes | How students get access | `"open"`, `"purchase"`, `"invite_only"`, `"cohort_only"`, `"subscription_only"` |
| `access_duration_type` | string | Yes | Access duration rule | `"lifetime"`, `"fixed_days"`, `"until_date"`, `"drip"` |
| `access_duration_days` | integer | No | Fixed duration in days | `null` or number (if `access_duration_type` is `"fixed_days"`) |
| `access_until_date` | string | No | Access expires date | `null` or ISO date string (if `access_duration_type` is `"until_date"`) |

## Module Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Module name |
| `description` | string | No | Module description |
| `order` | integer | Yes | Display order (0, 1, 2, ...) |
| `lessons` | array | Yes | Array of lesson objects |

## Lesson Fields

| Field | Type | Required | Description | Notes |
|-------|------|----------|-------------|-------|
| `title` | string | Yes | Lesson title | "Session #1 - Introduction" |
| `slug` | string | Yes | URL-friendly identifier | "session-1-introduction" |
| `order` | integer | Yes | Display order within module | 1, 2, 3, ... |
| `description` | string | Yes | Lesson description | What the lesson covers |
| `video_duration` | integer | Yes | Duration in minutes | 45, 60, etc. |
| `vimeo_duration_seconds` | integer | Yes | Duration in seconds | 2700 (for 45 min) |
| `google_drive_url` | string | No | Google Drive embed URL | `"https://drive.google.com/file/d/FILE_ID/preview"` |
| `google_drive_id` | string | No | Google Drive file ID | Extract from URL |
| `video_url` | string | No | Alternative video URL | Leave empty if using Google Drive |
| `vimeo_url` | string | No | Vimeo URL | Leave empty if using Google Drive |
| `vimeo_id` | string | No | Vimeo video ID | Leave empty if using Google Drive |
| `workbook_url` | string | No | Workbook/download URL | Optional |
| `resources_url` | string | No | Resources/download URL | Optional |
| `lesson_type` | string | Yes | Type of lesson | `"video"`, `"live"`, `"replay"` |
| `ai_clean_title` | string | No | Clean title for display | Usually same as `title` |
| `ai_short_summary` | string | No | Short summary | Brief overview |
| `ai_full_description` | string | No | Full description | Detailed description |
| `ai_outcomes` | array | No | List of learning outcomes | Array of strings |
| `ai_coach_actions` | array | No | Recommended AI actions | Array of strings |

## Example Structure

```json
{
  "courses": [
    {
      "name": "Assets Mastery",
      "slug": "assets-mastery",
      "course_type": "sprint",
      "status": "active",
      "description": "Learn to see money through the lens of ownership. Move beyond income dependency and into asset thinking.",
      "short_description": "Shift from income dependency to ownership",
      "coach_name": "Daniel Wood",
      "is_subscribers_only": false,
      "is_accredible_certified": true,
      "has_asset_templates": true,
      "exam_unlock_days": 120,
      "special_tag": "",
      "visibility": "public",
      "enrollment_method": "open",
      "access_duration_type": "lifetime",
      "access_duration_days": null,
      "access_until_date": null,
      "modules": [
        {
          "name": "Assets Mastery Core",
          "description": "Core content for Assets Mastery",
          "order": 0,
          "lessons": [
            {
              "title": "Introduction to Asset Thinking",
              "slug": "introduction-asset-thinking",
              "order": 1,
              "description": "Learn the fundamentals of asset-based thinking.",
              "video_duration": 45,
              "vimeo_duration_seconds": 2700,
              "google_drive_url": "https://drive.google.com/file/d/1vjh0c7ReJn4YjFsgcBCSJKW4xhJg3JOp/preview",
              "google_drive_id": "1vjh0c7ReJn4YjFsgcBCSJKW4xhJg3JOp",
              "video_url": "",
              "vimeo_url": "",
              "vimeo_id": "",
              "workbook_url": "",
              "resources_url": "",
              "lesson_type": "video",
              "ai_clean_title": "Introduction to Asset Thinking",
              "ai_short_summary": "Learn the fundamentals of asset-based thinking and move beyond income dependency.",
              "ai_full_description": "This lesson introduces you to the core concept of asset thinking. You'll learn how to identify real assets, avoid costly traps, and make decisions grounded in logic, not emotion.",
              "ai_outcomes": [
                "Understand what qualifies as a real asset",
                "Build decision rules that remove emotion from money choices",
                "Identify common financial traps to avoid"
              ],
              "ai_coach_actions": [
                "Summarize in 5 bullets",
                "Turn this into a 3-step action plan",
                "Generate 3 email hooks from this content",
                "Give me a comprehension quiz"
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

## Notes

1. **Slugs**: Must be unique per course. Use lowercase, hyphens, no spaces.
2. **Google Drive URLs**: Use the `/preview` format: `https://drive.google.com/file/d/FILE_ID/preview`
3. **Google Drive ID**: Extract from the URL (the part between `/d/` and `/preview`)
4. **Duration**: `video_duration` is in minutes, `vimeo_duration_seconds` is in seconds (multiply minutes by 60)
5. **Order**: Start at 1 for lessons, 0 for modules
6. **Arrays**: `ai_outcomes` and `ai_coach_actions` are arrays of strings

## Quick Reference: Duration Conversion

- 30 minutes = 1800 seconds
- 45 minutes = 2700 seconds
- 60 minutes = 3600 seconds

## Quick Reference: Course Types

- `"sprint"` - Sprint course
- `"speaking"` - Speaking course
- `"consultancy"` - Consultancy course
- `"special"` - Special course

## Quick Reference: Status Options

- `"active"` - Course is live and available
- `"locked"` - Course exists but is locked
- `"coming_soon"` - Course is coming soon

