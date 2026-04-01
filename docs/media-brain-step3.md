# media-brain Step 3

Step 3 reads the track inventory from Step 1 and the language labels from Step 2, applies the subtitle policy decision tree, and advances each media record to its next workflow state.

## Goal

For each media record in state `needs_subtitle_review`:

- determine whether a confirmed English subtitle exists (embedded or sidecar)
- route items with English subtitles to the audio review pipeline
- route items without English subtitles to Whisper subtitle generation
- persist the policy decision for downstream auditability

## Files

- `services/media_brain/step3_subtitle_policy.py`
- `tests/test_media_brain_step3_subtitle_policy.py`

## Storage model

Step 3 writes one row per media file into a new table:

- `step3_policy_decisions`

It also advances `media_records.state` to `needs_audio_review` or `needs_subtitle_generation`.

Step 3 does **not** mutate the Step 1 track inventory or the Step 2 language labels.

## Decision tree

```
IF any subtitle track has:
    detected_language = "en"
    AND review_status IN ("trusted_existing", "detected")
THEN
    policy_decision = "has_english_subtitle"
    next state      = "needs_audio_review"
    no Whisper job queued

ELSE
    policy_decision = "needs_subtitle_generation"
    next state      = "needs_subtitle_generation"
    Whisper job queued via state transition
```

### What counts as a confirmed English subtitle

A track qualifies when:

- `detected_language` is `"en"` (ISO 639-1)
- `review_status` is `"trusted_existing"` or `"detected"`

`trusted_existing` means the container or filename already carried a reliable `eng`/`en` tag and Step 2 skipped re-detection.

`detected` means a local language detector ran and returned confidence ≥ `confidence_threshold` (default `0.90`, defined in Step 2 as `LANGUAGE_CONFIDENCE_THRESHOLD`).

Tracks with `review_status = "uncertain"` or `"needs_ocr"` do **not** qualify, even if `detected_language` is `"en"`. Low-confidence detections are never treated as confirmed English at this stage.

### Sidecar subtitles

Sidecar `.srt` / `.ass` files that were classified as English by Step 2 qualify the same way as embedded tracks. `sidecar_count` in the decision row captures how many sidecars were present regardless of their language.

## Output fields

| Column | Type | Description |
|---|---|---|
| `media_id` | TEXT | SHA-256 identifier from Step 1 |
| `policy_decision` | TEXT | `has_english_subtitle` or `needs_subtitle_generation` |
| `next_state` | TEXT | Value written to `media_records.state` |
| `english_track_key` | TEXT | `track_key` of the first qualifying English track, or NULL |
| `has_any_subtitle` | INTEGER | 1 if any embedded or sidecar subtitle exists |
| `subtitle_track_count` | INTEGER | Count of embedded subtitle tracks |
| `sidecar_count` | INTEGER | Count of sidecar subtitle files |
| `decided_at` | TEXT | UTC ISO 8601 timestamp |
| `notes` | TEXT | Human-readable reason for the decision |

## State transitions

```
needs_subtitle_review
    │
    ├─ has_english_subtitle → needs_audio_review
    │
    └─ needs_subtitle_generation → needs_subtitle_generation
```

Step 3 only processes records whose current state is `needs_subtitle_review`. Records in any other state are skipped, making Step 3 safe to rerun.

## CLI

```bash
python services/media_brain/step3_subtitle_policy.py --db-path ./media_brain.db
```

Available flags:

```
--db-path   SQLite database created by Steps 1 and 2 (default: media_brain.db)
```

Output is a JSON summary printed to stdout:

```json
{
  "processed_files": 42,
  "has_english_subtitle": 15,
  "needs_subtitle_generation": 27,
  "failed_files": 0,
  "db_path": "media_brain.db"
}
```

## Dependencies

Step 3 requires only the Python standard library. All detection work is done in Step 2.

## Tests

```bash
pytest tests/test_media_brain_step3_subtitle_policy.py -v
```

Test coverage:

| Test | Scenario |
|---|---|
| `test_evaluate_policy_english_trusted_existing` | Embedded English track with `trusted_existing` status |
| `test_evaluate_policy_english_detected` | Embedded English track with `detected` status |
| `test_evaluate_policy_uncertain_english_does_not_qualify` | Low-confidence English must not qualify |
| `test_evaluate_policy_ocr_does_not_qualify` | Image-based subtitle must not qualify |
| `test_evaluate_policy_non_english_subtitle_queues_generation` | Non-English subtitle routes to generation |
| `test_evaluate_policy_no_subtitles_at_all` | No subtitles of any kind |
| `test_evaluate_policy_sidecar_only_no_english` | Sidecar present but not English |
| `test_evaluate_policy_english_sidecar_qualifies` | Sidecar English subtitle qualifies |
| `test_evaluate_policy_first_english_track_wins` | First qualifying track is used; order is stable |
| `test_run_step3_has_english_subtitle_advances_state` | Full DB roundtrip — English path |
| `test_run_step3_no_subtitle_queues_generation` | Full DB roundtrip — no subtitles path |
| `test_run_step3_non_english_subtitle_queues_generation` | Full DB roundtrip — non-English path |
| `test_run_step3_uncertain_english_queues_generation` | Full DB roundtrip — low-confidence English path |
| `test_run_step3_only_processes_needs_subtitle_review_state` | Other states are not touched |
| `test_run_step3_is_idempotent` | Rerunning Step 3 is safe |
| `test_run_step3_multiple_files_mixed_decisions` | Mixed batch: English, non-English, no subtitles |

## Scope boundary

Implemented here:

- subtitle policy decision tree
- `has_english_subtitle` vs `needs_subtitle_generation` routing
- media record state advancement
- decision persistence in `step3_policy_decisions`
- idempotent upsert (safe to rerun)

Not implemented here:

- Whisper job submission (the state transition signals the subtitle worker)
- audio track review logic (handled in a later step)
- domain-specific policy rules (deferred; current tree is universal)
- confidence threshold override at Step 3 (threshold is applied in Step 2)
