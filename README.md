# Downloader application

The Python package lives in `downloader/`.

Run the desktop app from the project root:

```console
python main.py
```

To launch the package module instead, run this from inside `app/`:

```console
python -m downloader
```

Enter space-separated Rule34 tags in the search box and choose **Search and
download**. The app fetches results in pages of up to 1,000, continuing with
Rule34's `pid` until all matching pages have been read. New files are saved in
the configured download folder, and completed post IDs are recorded in history
so they are skipped on later searches. Each media file also gets a `.json`
sidecar with the complete post record returned by Rule34, using the same base
filename (for example, `rule34_123.jpg` and `rule34_123.json`).

Searches are restricted to posts rated explicit and filter several common
underage-related tags. The confirmation checkbox is not an age-verification
mechanism; review results responsibly.

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
