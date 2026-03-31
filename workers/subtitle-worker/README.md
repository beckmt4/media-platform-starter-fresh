# subtitle-worker

Stateless subtitle job executor. Generates, repairs, or translates subtitle
tracks for a single media file. Never mutates the source file.

## Job types

| Type | Description | Required tools |
|------|-------------|----------------|
| `generate` | Transcribe audio with faster-whisper, write `.srt` | `ffmpeg`, `ffprobe`, `faster-whisper` (Python package) |
| `repair` | Fix malformed or mis-timed existing subtitle | None (pure Python) |
| `translate` | Translate subtitle lines to target language | None (stub) |

## Interface

**Input: `SubtitleJob`**

```json
{
  "item_id": "catalog-item-uuid",
  "file_path": "/mnt/itv/adult/SSIS-123/SSIS-123.mkv",
  "job_type": "generate",
  "target_language": "en",
  "whisper_model": "large-v3",
  "dry_run": false
}
```

**Output: `SubtitleJobResult`**

```json
{
  "job_id": "...",
  "item_id": "...",
  "status": "complete",
  "output_path": "/mnt/itv/adult/SSIS-123/SSIS-123.en.srt",
  "detected_language": "ja",
  "confidence": 0.94,
  "duration_seconds": 42.1
}
```

## Status values

| Status | Meaning |
|--------|---------|
| `complete` | Job finished, `.srt` file written |
| `skipped` | `dry_run=True` or policy skip |
| `failed` | Source file missing, ffmpeg error, or transcription error |
| `tool_unavailable` | `ffmpeg`, `ffprobe`, or `faster-whisper` not available |

## Audio track selection

For `generate` jobs, ffprobe inspects the source file and selects the English
audio stream (`language=eng/en`) when present, falling back to the first audio
stream. Audio is extracted to a temporary 16 kHz mono WAV before being fed to
faster-whisper.

## Catalog notification

On `complete`, the worker PATCHes the catalog item to append the
`subtitle-complete` tag. Requires `CATALOG_API_URL` to be set. The job result
is returned regardless of catalog reachability.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CATALOG_API_URL` | _(unset)_ | Base URL of catalog-api. When unset, no catalog notification is sent. |
| `HF_HOME` | `/models` | Hugging Face / faster-whisper model cache directory. |

## Running

```bash
cd workers/subtitle-worker
pip install -e ".[dev]"
pip install faster-whisper  # runtime dep, not included in dev extras

# Check tool availability
python -m subtitle_worker status

# Run a job (dry run)
python -m subtitle_worker run '{"item_id":"x","file_path":"/path/to/file.mkv","job_type":"generate","dry_run":true}'
```

## Running tests

```bash
pytest
```

No faster-whisper or ffmpeg installation required — tests use monkeypatching
and temporary files.

## Non-negotiables

- Source media files are never modified.
- Original and English audio tracks are always preserved.
- Output is always a new `.srt` file alongside the source (or in `output_dir`).
