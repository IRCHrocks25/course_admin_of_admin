# Google Drive Video Setup (Temporary Solution)

## How to Get Google Drive Embed URL

### Step 1: Upload Video to Google Drive
1. Upload your video file to Google Drive
2. Right-click on the video file
3. Select **"Get link"** or **"Share"**
4. Change sharing settings to **"Anyone with the link"** or **"Anyone on the internet"**
5. Copy the share link

### Step 2: Extract File ID
From the share link: `https://drive.google.com/file/d/FILE_ID_HERE/view?usp=sharing`

The `FILE_ID_HERE` is what you need.

### Step 3: Create Embed URL
Format: `https://drive.google.com/file/d/FILE_ID/preview`

Example:
- Share link: `https://drive.google.com/file/d/1ABC123xyz789/view?usp=sharing`
- Embed URL: `https://drive.google.com/file/d/1ABC123xyz789/preview`

### Step 4: Add to Lesson

**Option A: Through Dashboard**
1. Go to `/dashboard/lessons/`
2. Click **Edit** on a lesson
3. In the lesson edit page, add the Google Drive embed URL to the `google_drive_url` field
4. Save

**Option B: Through Django Shell**
```bash
python manage.py shell
```
Then:
```python
from myApp.models import Lesson
lesson = Lesson.objects.first()
lesson.google_drive_url = "https://drive.google.com/file/d/YOUR_FILE_ID/preview"
lesson.save()
print(f"Updated: {lesson.title}")
```

**Option C: Update Seed File**
Edit `myApp/management/commands/seed_data.py` and add:
```python
'google_drive_url': 'https://drive.google.com/file/d/YOUR_FILE_ID/preview',
```

## Important Notes

⚠️ **Limitations:**
- Google Drive videos may have playback restrictions
- Large files might buffer slowly
- Not ideal for production (use Vimeo/YouTube for production)

✅ **For Development:**
- Works great for testing
- No domain restrictions
- Easy to update

## Priority Order in Template

The template checks in this order:
1. `vimeo_id` (Vimeo embed)
2. `google_drive_url` (Google Drive embed) ← **NEW**
3. `video_url` (Generic iframe)
4. Placeholder (no video)

So if you have both Vimeo and Google Drive, Vimeo takes priority.

## Quick Test

After adding the Google Drive URL, visit your lesson page. The video should embed automatically!

