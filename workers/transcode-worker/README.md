# transcode-worker

Stateless video transcode job executor. Re-encodes the video stream of a
single media file using ffmpeg. Audio and subtitle streams are always copied
unchanged. Never overwrites the source file.

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
| `failed` | Source missing, in-place attempt, ffmpeg error, or timeout |
| `tool_unavailable` | `ffmpeg` or `ffprobe` not on PATH |

## Encoder selection

| Condition | Encoder |
|-----------|---------|
| `allow_nvenc=True` and `nvidia-smi` on PATH | `hevc_nvenc` |
| Otherwise | `libx265` |

## Catalog notification

On `complete`, the worker PATCHes the catalog item to append the
`transcode-complete` tag. Requires `CATALOG_API_URL` to be set. The job
result is returned regardless of catalog reachability.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CATALOG_API_URL` | _(unset)_ | Base URL of catalog-api. When unset, no catalog notification is sent. |
| `PREFER_NVENC` | `false` | Set to `true` to prefer NVIDIA NVENC (CA Apps UI toggle). |

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

No ffmpeg installation required — all subprocess calls are monkeypatched.

## Non-negotiables

- Source file is never deleted or overwritten (`output_path` must differ from `file_path`).
- Audio and subtitle streams are always copied (`-c:a copy -c:s copy`).
- Partial output files are deleted on ffmpeg error or timeout.
- Hard timeout: 2 hours per job (`subprocess.TimeoutExpired` → `failed`).
