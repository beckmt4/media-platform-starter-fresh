# transcode-worker

Stateless video transcode job executor. Re-encodes the video stream of a
single media file using ffmpeg. Audio and subtitle streams are always copied
unchanged. Never overwrites the source file.

## Status

Stub — job interface, encoder selection, and all safety guards are complete.
Actual ffmpeg execution is not implemented. The worker returns `complete` with
source file size when all tools are available.

## Interface

**Input: `TranscodeJob`**

```json
{
  "item_id": "catalog-item-uuid",
  "file_path": "/mnt/dtv/Domestic_Movies/Movie.2023.mkv",
  "output_path": "/mnt/container/media-work/inbox/Movie.2023.hevc.mkv",
  "target_codec": "hevc",
  "container": "mkv",
  "allow_nvenc": true,
  "dry_run": false
}
```

**Output: `TranscodeJobResult`**

```json
{
  "job_id": "...",
  "item_id": "...",
  "status": "complete",
  "output_path": "/mnt/container/media-work/inbox/Movie.2023.hevc.mkv",
  "codec_used": "hevc_nvenc",
  "size_bytes_before": 10737418240,
  "size_bytes_after": 4294967296,
  "duration_seconds": 3612.5
}
```

## Status values

| Status | Meaning |
|--------|---------|
| `complete` | Job finished, output file written |
| `skipped` | `dry_run=True` |
| `failed` | Source missing, in-place attempt, or runtime error |
| `tool_unavailable` | `ffmpeg` or `ffprobe` not on PATH |

## Encoder selection

| Condition | Encoder |
|-----------|---------|
| `allow_nvenc=True` and `nvidia-smi` on PATH | `hevc_nvenc` |
| Otherwise | `libx265` |

## Running

```bash
cd workers/transcode-worker
pip install -e ".[dev]"

# Check tool availability
python -m transcode_worker status

# Dry-run a job
python -m transcode_worker run '{"item_id":"x","file_path":"/src.mkv","output_path":"/out.mkv","dry_run":true}'
```

## Running tests

```bash
pytest
```

No ffmpeg installation required — all tool calls are monkeypatched.

## Non-negotiables

- Source file is never deleted or overwritten (`output_path` must differ from `file_path`).
- Audio and subtitle streams are always copied (`-c:a copy -c:s copy`).
- Caller updates catalog state after verifying the output — the worker does not touch catalog-api.
