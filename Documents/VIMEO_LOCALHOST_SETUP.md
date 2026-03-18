# Vimeo Localhost Setup

## Do You Need to Whitelist Localhost in Vimeo?

**Short answer: Usually NO, but it depends on your video's privacy settings.**

### When Localhost Works Automatically:
- ✅ **Public videos** - Work on localhost without any setup
- ✅ **Unlisted videos** - Work on localhost without any setup
- ✅ **Videos with "Anywhere" embed settings** - Work on localhost

### When You Might Need to Whitelist:
- ⚠️ **Private videos** - May require domain whitelisting
- ⚠️ **Videos with restricted embed domains** - Need to add localhost

## How to Check/Update Vimeo Privacy Settings:

1. Go to your Vimeo video
2. Click **Settings** (gear icon)
3. Go to **Privacy** tab
4. Under **Where can this video be embedded?**
   - Select **"Anywhere"** for development (or add specific domains)
   - If using **"Specific domains"**, add:
     - `localhost`
     - `127.0.0.1`
     - `localhost:8000`
     - `127.0.0.1:8000`

## Your Video ID:
- **Video ID**: `884773301`
- **Embed URL**: `https://player.vimeo.com/video/884773301`

## Testing:

1. Run the seed file:
   ```bash
   python manage.py seed_data
   ```

2. Visit a lesson page:
   ```
   http://127.0.0.1:8000/courses/sprint-8-0/sprint-8-0-orientation/
   ```

3. If video doesn't load:
   - Check browser console for errors
   - Verify video privacy settings in Vimeo
   - Try adding localhost to Vimeo's allowed domains

## Production Deployment:

When you deploy to production, make sure to:
1. Add your production domain to Vimeo's allowed domains
2. Update video privacy settings if needed
3. Test video playback on production domain

