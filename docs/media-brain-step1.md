# media-brain Step 1

This document captures the repo inventory, reuse decisions, target architecture, and the Step 1 implementation scope added to `media-platform-starter-fresh`.

## Goal

Build only Step 1 of `media-brain` in the target repo:

- scan `/mnt/itv/adult/**/*.mkv` plus `.mp4` and `.avi`
- parse `ffprobe` JSON
- enumerate subtitle, audio, and video tracks
- detect sidecar `.srt` and `.ass`
- compute `media_id` from normalized path plus size hash
- write media records to `media_brain.db`
- set `state = needs_subtitle_review`

## Repo inventory

### Target repo
- `media-platform-starter-fresh`
  - **Status:** real scaffold, correct target for new work
  - **Use:** implemented Step 1 here only

### Strongest reusable references
- `Subtitle-Detection`
  - **Reusable concept:** recursive scan patterns, media-vs-sidecar thinking, SQLite-oriented workflow
  - **Not reused blindly:** language detection stack, whisper fallback, Ollama adjudication, tagging/mutation logic
- `Media_Check_Tool`
  - **Reusable concept:** `ffprobe` wrapper pattern and normalized stream extraction
  - **Not reused blindly:** pruning, OpenSubtitles integration, output mutation flow
- `nhkprep_skeleton`
  - **Reusable concept:** media prep pipeline shape, scan/probe/detect sequencing
  - **Not reused blindly:** JA/EN-specific assumptions and media-cleaning pipeline
- `missing-media`
  - **Reusable concept:** project layout and scanner/report split
  - **Not reused blindly:** TMDB-driven missing-content logic
- `anime-subtitle-pipeline`
  - **Reusable concept:** media processing discipline and local-first design
  - **Not reused blindly:** ASR/MT/LLM pipeline is a later-stage concern, not Step 1 inventory

### Not directly reusable for Step 1
- `audiobook-organizer`
  - useful project hygiene, but wrong domain for this task
- `Book_Renamer`
  - audiobook rename utility, not a match for media-brain inventory
- `DataSet_Tool`
  - unrelated dataset-building codebase
- `zfs_balance_unriad`
  - unrelated infrastructure/storage utility

### Empty, tiny, or placeholder-level for this task
- `Language-corrector`
  - effectively empty from inspection signal
- `Anime_subtiltes`
  - tiny footprint and no useful Step 1 entrypoint surfaced during inspection
  - treat as placeholder/unfinished for this task

## What was reused vs not reused

### Reused as reference patterns
- recursive file scan approach
- `ffprobe` subprocess wrapper pattern
- normalized stream inventory shape
- local-first SQLite persistence model

### Explicitly not reused
- subtitle language detection
- subtitle rewriting or tagging
- ASR, MT, LLM, OCR, or cloud/API workflows
- media mutation, pruning, or remux logic
- TMDB and OpenSubtitles integrations

## Target architecture

Implemented under:

- `services/media_brain/step1_inventory.py`
- `tests/test_media_brain_step1_inventory.py`

### Step 1 flow

1. recursively scan `/mnt/itv/adult`
2. filter to `.mkv`, `.mp4`, `.avi`
3. run `ffprobe -show_format -show_streams -print_format json`
4. bucket tracks into `video`, `audio`, `subtitle`
5. detect adjacent sidecars with matching stem:
   - `movie.srt`
   - `movie.en.srt`
   - `movie.forced.ass`
6. compute stable `media_id`
7. upsert into `media_records`
8. set `state` to `needs_subtitle_review`

## Database shape

Single-table first cut for Step 1:

- `media_id`
- `path`
- `file_name`
- `extension`
- `size_bytes`
- `ffprobe_json`
- `video_tracks_json`
- `audio_tracks_json`
- `subtitle_tracks_json`
- `sidecar_subtitles_json`
- `state`
- `scanned_at`

This is intentionally simple for Step 1. Track normalization into separate tables can happen in a later step once query requirements are clearer.

## CLI

Run from repo root:

```bash
python services/media_brain/step1_inventory.py
```

Optional arguments:

```bash
python services/media_brain/step1_inventory.py \
  --root /mnt/itv/adult \
  --db-path ./media_brain.db
```

## Tests

Added tests for:

- stable `media_id` generation
- sidecar detection
- SQLite write path with mocked `ffprobe`

Run:

```bash
pytest
```

## Scope boundary

Implemented here:

- inventory
- raw probe capture
- track enumeration
- sidecar detection
- SQLite persistence
- initial state assignment

Deliberately not implemented here:

- subtitle quality scoring
- language detection
- subtitle fixing
- media cleanup or remux
- any writes back to source media files
