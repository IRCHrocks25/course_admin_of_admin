# Debug Vimeo Embed Issue

## Quick Checks:

1. **Check if migrations ran:**
   ```bash
   python manage.py showmigrations myApp
   ```
   Look for migrations that add `vimeo_id`, `vimeo_url`, etc.

2. **If migrations are missing, run:**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

3. **Check if seed data has vimeo_id:**
   ```bash
   python manage.py shell
   ```
   Then in shell:
   ```python
   from myApp.models import Lesson
   lesson = Lesson.objects.first()
   print(f"Vimeo ID: {lesson.vimeo_id}")
   print(f"Vimeo URL: {lesson.vimeo_url}")
   ```

4. **If vimeo_id is empty, update it manually:**
   ```python
   lesson = Lesson.objects.first()
   lesson.vimeo_id = "884773301"
   lesson.vimeo_url = "https://vimeo.com/884773301"
   lesson.save()
   ```

5. **Check browser console** for any JavaScript errors or CORS issues

6. **Verify Vimeo privacy settings:**
   - Video must allow embedding
   - Check if domain restrictions are set

## The Template Checks:
- First: `{% if lesson.vimeo_id %}` - Uses Vimeo embed
- Second: `{% elif lesson.video_url %}` - Uses generic iframe
- Third: Shows placeholder

Make sure `lesson.vimeo_id` is set to "884773301" in the database!

