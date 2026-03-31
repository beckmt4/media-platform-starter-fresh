# media-brain Step 1 (spec-complete)

This document closes the remaining Step 1 spec gaps by adding:

- HDR detection for video tracks
- a real HTTP scan endpoint

## What was missing before

The earlier Step 1 implementation already handled:

- recursive file scan for `.mkv`, `.mp4`, `.avi`
- `ffprobe` JSON capture
- subtitle/audio/video enumeration
- sidecar `.srt` / `.ass` detection
- `media_id` computation
- SQLite persistence with `state = needs_subtitle_review`

But it did **not** fully satisfy the written spec because:

- video tracks did not expose HDR status
- the tool was a CLI/module, not an actual scan endpoint

## Files added

- `services/media_brain/step1_scan_endpoint.py`
- `tests/test_media_brain_step1_scan_endpoint.py`

## Step 1 endpoint

Start the endpoint server:

```bash
python services/media_brain/step1_scan_endpoint.py --serve --host 127.0.0.1 --port 8787
```

Health check:

```bash
GET /healthz
```

Scan endpoint:

```bash
POST /media-brain/scan
Content-Type: application/json

{
  "scan_root": "/mnt/itv/adult",
  "db_path": "./media_brain.db"
}
```

Example response:

```json
{
  "scanned_files": 1507,
  "inserted_or_updated": 1507,
  "failed_files": 0,
  "db_path": "media_brain.db",
  "state": "needs_subtitle_review"
}
```

## CLI compatibility

The same module can still run a one-off scan without serving HTTP:

```bash
python services/media_brain/step1_scan_endpoint.py \
  --root /mnt/itv/adult \
  --db-path ./media_brain.db
```

## HDR logic

Each video track now stores:

- `hdr` — boolean
- `hdr_format` — one of:
  - `hdr10`
  - `hlg`
  - `dolby_vision`
  - `hdr`
  - `null` when not HDR

It also stores supporting fields when present:

- `pix_fmt`
- `color_transfer`
- `color_primaries`
- `color_space`

Current HDR detection uses `ffprobe` metadata such as:

- `color_transfer = smpte2084` → HDR10
- `color_transfer = arib-std-b67` → HLG
- Dolby Vision side-data
- mastering/content-light metadata

## Database impact

No new table is required.

The existing `video_tracks_json` payload is enriched with HDR metadata, so rerunning Step 1 updates records in place.

## Tests

Run:

```bash
pytest tests/test_media_brain_step1_scan_endpoint.py -v
```

Coverage includes:

- HDR10 detection
- HLG detection
- DB write path including HDR fields
- endpoint request/response handling

## Practical note

The earlier `services/media_brain/step1_inventory.py` remains in the repo for backward compatibility, but the spec-complete Step 1 implementation is now:

- `services/media_brain/step1_scan_endpoint.py`
