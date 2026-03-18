# Fix Vimeo Embed Error

## The Problem
You're seeing: "Hey There! To play your video here, change its privacy settings so it can be embedded on: 127.0.0.1:8000"

This means Vimeo is blocking the embed because localhost isn't in the allowed domains.

## Solution: Update Vimeo Privacy Settings

### Step 1: Go to Your Vimeo Video
1. Log into your Vimeo account
2. Go to your video: https://vimeo.com/884773301
3. Click the **Settings** (gear icon) or **Edit** button

### Step 2: Update Privacy Settings
1. Click on **Privacy** tab
2. Scroll down to **"Where can this video be embedded?"**
3. You have two options:

   **Option A: Allow Anywhere (Easiest for Development)**
   - Select **"Anywhere"**
   - This allows embedding on any domain (including localhost)
   - ✅ Best for development/testing

   **Option B: Specific Domains (More Secure)**
   - Select **"Specific domains"**
   - Click **"Add domain"**
   - Add these domains one by one:
     - `localhost`
     - `127.0.0.1`
     - `localhost:8000`
     - `127.0.0.1:8000`
   - Click **Save**

### Step 3: Save and Refresh
1. Click **Save** on the Vimeo settings page
2. Go back to your lesson page
3. **Hard refresh** the page (Ctrl+F5 or Cmd+Shift+R)
4. The video should now embed!

## Alternative: Test with a Public Vimeo Video

If you want to test immediately, you can temporarily use a public Vimeo video:
- Find any public Vimeo video
- Get its ID from the URL
- Update the seed file with that ID
- Run `python manage.py seed_data` again

## For Production

When you deploy to production, make sure to:
1. Add your production domain to Vimeo's allowed domains
2. Update the video privacy settings to include your production URL
3. Test video playback on the production site

## Quick Check

After updating settings, the embed URL should work:
```
https://player.vimeo.com/video/884773301?badge=0&autopause=0&player_id=0&app_id=58479
```

Try opening this URL directly in your browser - if it works there, it should work in your site after updating privacy settings.

