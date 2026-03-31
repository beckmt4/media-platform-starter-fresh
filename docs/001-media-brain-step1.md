# media-brain Step 1

Step 1 builds the first durable inventory layer for adult media review.

## Scope

This step is intentionally limited to inventory and state seeding.

It does the following:

1. scans `/mnt/itv/adult` recursively for:
   - `.mkv`
   - `.mp4`
   - `.avi`
2. runs `ffprobe` for every discovered media file
3. records all `video`, `audio`, and `subtitle` streams
4. detects matching `.srt` and `.ass` sidecars in the same directory
5. computes `media_id` from canonical path + size hash
6. writes normalized rows to `media_brain.db`
7. sets `state=needs_subtitle_review`

## Out of scope

This step does **not**:

- generate subtitles
- rewrite container metadata
- rename files
- edit sidecars
- delete tracks
- call cloud services
- infer final subtitle quality

## Data model

### media_records

Top-level row for each media file.

Key fields:

- `media_id`
- `file_path`
- `file_name`
- `extension`
- `file_size`
- `size_hash`
- `state`
- `ffprobe_json`
- timestamps

### media_streams

One row per ffprobe stream with:

- stream index
- stream type
- codec
- language tag
- title
- width / height
- channels
- default / forced flags
- raw stream JSON

### sidecar_subtitles

One row per matching sidecar subtitle:

- sidecar path
- extension
- optional language hint from filename

### scan_runs

Run-level summary table for basic observability.

## Matching rules for sidecars

A sidecar is attached to a media file when it is in the same directory and its
filename is either:

- the same stem, or
- the same stem followed by `.` and extra tokens

Examples for `Example.Title.mkv`:

- `Example.Title.srt`
- `Example.Title.en.srt`
- `Example.Title.forced.ass`

## Why the state is forced to review

This first stage is a staging gate, not an automation gate.

Everything lands in `needs_subtitle_review` so later stages can decide whether
the title needs:

- subtitle language tagging
- sidecar repair
- subtitle generation
- manual review
- no action

## Re-run behavior

The scanner uses upsert semantics.

If the same file is re-scanned:

- `media_records` is updated
- `media_streams` rows are replaced for that `media_id`
- `sidecar_subtitles` rows are replaced for that `media_id`
- a new `scan_runs` row is inserted

That keeps the latest inventory without duplicating stream rows.

## Command examples

```bash
cd services/media-brain
pip install -e ".[dev]"
media-brain status
media-brain scan
```
