# subtitle-worker

Stateless subtitle job executor. Generates, repairs, or translates subtitle
tracks for a single media file. Never mutates the source file.

## Status

Stub — job interface and validation are complete. Actual faster-whisper
execution is not implemented. The worker returns `complete` with a placeholder
output path when all tools are available.

## Job types

| Type | Description | Required tools |
|------|-------------|----------------|
| `generate` | Run faster-whisper on the audio track | `whisper` (faster-whisper CLI) |
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
| `complete` | Job finished successfully |
| `skipped` | `dry_run=True` or policy skip |
| `failed` | Source file missing or runtime error |
| `tool_unavailable` | `whisper` not on PATH |

## Running

```bash
cd workers/subtitle-worker
pip install -e ".[dev]"

# Check tool availability
python -m subtitle_worker status

# Run a job (dry run)
python -m subtitle_worker run '{"item_id":"x","file_path":"/path/to/file.mkv","job_type":"generate","dry_run":true}'
```

## Running tests

```bash
pytest
```

No faster-whisper installation required — tests use monkeypatching and temp files.

## Non-negotiables

- Source media files are never modified.
- Original and English audio tracks are always preserved.
- Output is always a new file alongside (or in `output_dir`).
