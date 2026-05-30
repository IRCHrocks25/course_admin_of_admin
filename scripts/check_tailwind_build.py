#!/usr/bin/env python
"""
Fail loudly if the committed Tailwind CSS is stale.

Rebuilds the CSS from templates/config into a temp file and byte-compares it to the
committed static/css/tailwind.css. If they differ, someone changed templates (adding
Tailwind classes) without re-running `npm run build:css` and committing the result —
which would silently ship unstyled/missing utilities to production.

Used by .githooks/pre-commit and the GitHub Actions workflow. Exit code 1 on mismatch.

The build command below MUST stay in sync with the `build:css` script in package.json.
"""
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMITTED = os.path.join(REPO_ROOT, "static", "css", "tailwind.css")
CONFIG = "tailwind.config.js"
INPUT = os.path.join("static", "src", "tailwind.css")


def _run_tailwind(out_path):
    # Prefer the locally-installed binary; fall back to npx.
    local_bin = os.path.join(
        REPO_ROOT, "node_modules", ".bin",
        "tailwindcss.cmd" if os.name == "nt" else "tailwindcss",
    )
    base = [local_bin] if os.path.exists(local_bin) else ["npx", "tailwindcss"]
    cmd = base + ["-c", CONFIG, "-i", INPUT, "-o", out_path, "--minify"]
    return subprocess.run(
        cmd, cwd=REPO_ROOT, shell=(os.name == "nt"),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def main():
    if not os.path.exists(COMMITTED):
        sys.exit("[tailwind] static/css/tailwind.css is missing — run `npm run build:css` and commit it.")

    with tempfile.TemporaryDirectory() as tmp:
        fresh = os.path.join(tmp, "fresh.css")
        result = _run_tailwind(fresh)
        if result.returncode != 0:
            print(result.stdout.decode("utf-8", "replace"))
            sys.exit("[tailwind] build failed — see output above.")

        committed_bytes = open(COMMITTED, "rb").read()
        fresh_bytes = open(fresh, "rb").read()

    if committed_bytes != fresh_bytes:
        sys.exit(
            "[tailwind] STALE BUILD: static/css/tailwind.css does not match a fresh build.\n"
            "           You changed templates/config without rebuilding the CSS.\n"
            "           Fix: run `npm run build:css` and commit static/css/tailwind.css."
        )

    print("[tailwind] OK — committed CSS matches a fresh build.")


if __name__ == "__main__":
    main()
