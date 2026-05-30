# Tailwind CSS build

The app no longer uses the `cdn.tailwindcss.com` runtime CDN. Tailwind is now
**compiled to a static file** and served by WhiteNoise.

## How it works today (commit-built CSS)

- **Config:** `tailwind.config.js` (ported from the old inline `tailwind.config`
  blocks — custom colors `navy-dark`, `navy-mid`, `cyan-electric`, `purple-accent`,
  `emerald-glow`, Inter font, and a **safelist** for class names that are built
  dynamically in JS and can't be seen by the content scanner).
- **Input:** `static/src/tailwind.css` (just the `@tailwind` directives).
- **Output:** `static/css/tailwind.css` — **committed to git** and served via
  `{% static 'css/tailwind.css' %}` in the 6 page heads (`base.html`,
  `dashboard/base.html`, `landing/_head.html`, `landing.html`,
  `force_password_change.html`, `superadmin/notification_preview.html`).
- The existing `collectstatic` step in the `Procfile` release phase hashes and
  compresses it for production. **No Node is required at deploy time.**

### When you change templates
If you add/remove Tailwind classes in any template, rebuild and commit:

```bash
npm install        # first time only
npm run build:css  # regenerates static/css/tailwind.css
git add static/css/tailwind.css
```

`npm run watch:css` rebuilds on save during development.

### Stale-build guard (so a forgotten rebuild fails loudly)
- **CI (authoritative):** `.github/workflows/tailwind.yml` runs `npm ci` then
  `scripts/check_tailwind_build.py`, which rebuilds and byte-compares against the
  committed CSS. A forgotten rebuild **fails the PR/push**.
- **Local (early warning):** `.githooks/pre-commit` runs the same check. Activate
  it once per clone:
  ```bash
  git config core.hooksPath .githooks
  ```

### Dynamically-composed classes (safelist)
The content scanner only sees class names that appear *literally* in source.
These are built at runtime and are covered by the `safelist` in
`tailwind.config.js` — **add to the safelist if you introduce more**:
- `generate_lesson_ai.html` → `bg-{cyan-electric|purple-accent}/10`,
  `border-{…}/20`, `text-{…}` (built in `addTestMessage`).
- `lesson.html` / `students.html` → `from-cyan-electric to-purple-accent` avatar
  gradients.

---

## Follow-up: move to a release-phase build on Railway (Option 2)

Commit-built CSS is simple and deploy-safe, but requires remembering to rebuild.
To build on Railway at deploy time instead (so the committed file is no longer the
source of truth), wire it up like this — **test on a Railway deploy before relying
on it**, since it changes the build pipeline:

1. **Make Node available in the build image.** Railway's Python (nixpacks) image
   does not include Node by default. Add a `nixpacks.toml` at the repo root:
   ```toml
   [phases.setup]
   nixPkgs = ["...", "nodejs_22"]   # "..." keeps nixpacks' auto-detected Python pkgs
   ```
   (Alternatively use a Dockerfile, or Railway's "Node + Python" community builder.)

2. **Build the CSS in the release phase**, before `collectstatic`. In `Procfile`:
   ```
   release: npm ci && npm run build:css && python manage.py migrate && python manage.py createcachetable && python manage.py collectstatic --noinput
   ```

3. Once the release build is confirmed working on Railway, you can **stop
   committing `static/css/tailwind.css`** (add it to `.gitignore`) and **drop the
   CI/pre-commit stale-build guard** — the build then always runs fresh on deploy.

### Risks to verify before switching
- The release phase now fails the deploy if `npm ci` or the build fails (e.g. Node
  not actually present, lockfile drift). Confirm a full deploy succeeds first.
- Build time is added to every deploy (~2–5s for Tailwind + npm install).
- Keep the safelist current regardless of approach.
