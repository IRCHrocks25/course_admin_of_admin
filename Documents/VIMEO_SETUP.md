# Vimeo Video Setup Guide

## What Fields Are Needed to Display Vimeo Videos?

To display a Vimeo video in your lessons, you need to populate these fields in the `Lesson` model:

### Required Field:
- **`vimeo_id`** - The Vimeo video ID (e.g., "123456789" from URL `https://vimeo.com/123456789`)

### Optional Fields (but recommended):
- **`vimeo_url`** - Full Vimeo URL (e.g., `https://vimeo.com/123456789`)
- **`vimeo_thumbnail`** - Thumbnail image URL (for previews in lists)
- **`vimeo_duration_seconds`** - Video duration in seconds (for display)

## How to Get Your Vimeo Video ID

1. Go to your Vimeo video page
2. Look at the URL: `https://vimeo.com/123456789`
3. The number at the end (`123456789`) is your `vimeo_id`

## Example:

If your Vimeo URL is: `https://vimeo.com/76979871`

Then:
- `vimeo_id` = `"76979871"`
- `vimeo_url` = `"https://vimeo.com/76979871"`
- `vimeo_thumbnail` = `"https://i.vimeocdn.com/video/76979871_640.jpg"` (generic format)
- `vimeo_duration_seconds` = `2520` (42 minutes = 42 * 60)

## How the Video Displays

The lesson page checks for `vimeo_id` first. If it exists, it creates an embed URL:
```
https://player.vimeo.com/video/{vimeo_id}
```

This is automatically embedded in an iframe on the lesson page.

## Running the Seed File

1. **First, update the seed file** with your actual Vimeo video IDs:
   - Open `myApp/management/commands/seed_data.py`
   - Find `SAMPLE_VIMEO_ID = "76979871"`
   - Replace with your actual Vimeo video ID

2. **Run the seed command**:
   ```bash
   python manage.py seed_data
   ```

3. **This will create**:
   - Admin user (username: `admin`, password: `admin123`)
   - Sample courses (Sprint 8.0, Public Speaking Mastery)
   - Sample lessons with Vimeo videos
   - Modules and course structure

## Updating Existing Lessons

You can update lessons through:
1. **Dashboard** (`/dashboard/`) - Go to Lessons → Edit
2. **Creator Flow** (`/creator/`) - Add lesson with Vimeo URL
3. **Django Admin** (`/admin/`) - Direct database editing

## Testing

After seeding, visit:
- Dashboard: `http://127.0.0.1:8000/dashboard/`
- Courses: `http://127.0.0.1:8000/courses/`
- Sample Lesson: `http://127.0.0.1:8000/courses/sprint-8-0/sprint-8-0-orientation/`

