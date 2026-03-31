# media-brain

Bulk media file inspector. Scans directories or individual files using `mediainfo`,
extracts all track metadata (video, audio, subtitle), detects sidecar subtitle files,
assigns a stable `media_id`, and persists results to `media_brain.db`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check + item count |
| `POST` | `/scan/file` | Scan one file, persist result |
| `POST` | `/scan/directory` | Bulk scan a directory |
| `GET` | `/items` | List items (filter by `state`, paginate) |
| `GET` | `/items/{media_id}` | Fetch one item by media_id |
| `PATCH` | `/items/{media_id}/state` | Transition item state |

## States

- `needs_subtitle_review` — default after scan; item awaits subtitle policy evaluation
- `reviewed` — subtitle review complete
- `error` — scan failed (mediainfo missing, file not found, etc.)

## media_id

`SHA256("<absolute_path>:<file_size_bytes>")` — stable across re-scans as long as
the file is not replaced. Changes if the file size changes (e.g. after re-encode).

## Running locally

```bash
MEDIA_BRAIN_DB_PATH=/data/media_brain.db uvicorn media_brain.main:app --host 0.0.0.0 --port 8004
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## Dependencies

- `mediainfo` must be on `PATH` for real scans. Tests inject JSON to skip the subprocess.
