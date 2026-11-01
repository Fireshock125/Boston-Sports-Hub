# Celtics automatic YouTube highlights

The website already supports optional `celtics-highlights.json` alongside ESPN videos.

This workflow searches the **official NBA YouTube channel** for recent completed
Boston Celtics games, matches both team nicknames in the video title, and saves
video IDs under ESPN game IDs. It runs twice daily and can also be started manually.

## One-time setup (required)

1. Create a YouTube Data API v3 key in Google Cloud (enable the API first).
2. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Name the secret exactly `YOUTUBE_API_KEY`, paste the key, and save it.
4. Open **Actions → Celtics official NBA highlights → Run workflow**.
5. Ensure GitHub Actions has permission to write repository contents
   (**Settings → Actions → General → Workflow permissions**).

Do not place your API key in HTML, JSON, or repository files. YouTube search
is only performed in GitHub Actions. The public site reads generated IDs.

The updater needs ESPN schedules and YouTube search access. It skips games when
a reliable official highlight match cannot be found, retaining ESPN playback.
Videos can be unavailable for embedding even when an official listing exists.
