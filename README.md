# Downloader application

The Python package lives in `app/downloader/`.

Run the local web app from the project root:

```console
python main.py
```

This starts a loopback-only web server at `http://127.0.0.1:8765/` and opens
the interface in your browser. Use `--port 0` to select an available port or
`--no-browser` to leave the browser closed. To launch the package module
instead, run this from inside `app/`:

```console
python -m downloader
```

The **Gallery** tab shows supported image and video files in the configured
download folder. The **Rule34** tab contains the tag search and download queue.
Use **Config** to update the download folder, Rule34 request rate, and (if
needed) Rule34 credentials. Saved credentials are never returned to the browser;
leave both credential fields blank to keep the existing values.

Enter space-separated Rule34 tags in the search box and choose **Search and
download**. The app fetches results in pages of up to 1,000, continuing with
Rule34's `pid` until all matching pages have been read. New files are saved in
the configured download folder, and completed post IDs are recorded in history
so they are skipped on later searches. Each media file also gets a `.json`
sidecar using the same base filename (for example, `rule34_123.jpg` and
`rule34_123.json`). The sidecar stores the post `id`, `tags` (as a list),
`source`, editable `title` and `description`, and `downloaded_at` as an
ISO-8601 UTC timestamp recorded when the download completes. The Gallery's
full view shows these fields, and title/description edits are saved to the
sidecar. The Rule34 API response does not provide the post's displayed
"Posted" date; older files without `downloaded_at` show an unknown download
time rather than an estimated file modification time.

The browser UI is bundled with the Python package and makes no third-party
requests. The local server binds only to `127.0.0.1`; downloads themselves
still require a connection to Rule34. Progress updates stream from the backend,
and cancellation is checked between search pages, downloads, rate-limit waits,
and streamed file chunks. An active network read can take up to its configured
30-second timeout to finish before cancellation takes effect.

The browser talks to a same-origin local API: `POST /api/tasks` with
`{"tags":"..."}` starts a task, `GET /api/tasks/{id}/events` streams progress
as Server-Sent Events, and `DELETE /api/tasks/{id}` requests cancellation.
Progress events include the search/download phase, completed and total counts,
and downloaded/skipped/failed counts. Terminal events report completion,
cancellation, or an actionable error.

Searches are restricted to posts rated explicit and filter several common
underage-related tags. Review results responsibly.

## Local data files

- `app/config.json` contains application settings, including the download
  directory, paths to the keys and download history files, and per-site request
  limits. For example, `rate_limits.rule34.requests_per_second: 1` allows at
  most one request start per second to Rule34, including post-file downloads.
- `app/keys.json` stores local service credentials under
  `services.rule34.api_key` and `services.rule34.user_id`. Both are required
  for the authenticated Rule34 API. The file is ignored by Git; use
  `app/keys.example.json` as a schema example and never put real credentials
  in the example file.
- `app/history.json` stores downloaded IDs grouped by site (for example,
  `"rule34": ["18960447"]`) so the app can skip duplicates. Existing legacy
  Rule34 history is migrated to this format when read.
