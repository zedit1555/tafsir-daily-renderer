# tafsir.daily video renderer

Renders a vertical 1080x1920 video (one scene per verse: Quran text, Arabic + English tafsir, recitation) with GitHub Actions, then publishes it as a GitHub release.

Trigger: Actions → "Render tafsir video" → Run workflow (or via the GitHub API from Make).

Required repository secrets: MUKHTASAR_EMAIL, MUKHTASAR_PASSWORD, BOOK_AR, BOOK_EN.

Output: https://github.com/<OWNER>/<REPO>/releases/download/<job_id>/video.mp4
