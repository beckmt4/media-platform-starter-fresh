# media-brain Step 2

Step 2 adds per-track subtitle language detection on top of the Step 1 inventory database.

## Goal

For each subtitle track discovered in Step 1:

- trust valid existing language tags and skip re-detection
- detect language for `und`, missing, or suspicious tags
- extract up to 2000 characters of subtitle text
- use a local Python detector (`langdetect` or `lingua`)
- fall back to Whisper audio language detection when text is unavailable or too short
- mark low-confidence results as `uncertain`
- flag image-based subtitles for future OCR work
- store one row per subtitle track in SQLite

## Files

- `services/media_brain/step2_subtitle_language.py`
- `tests/test_media_brain_step2_subtitle_language.py`

## Storage model

Step 2 does **not** mutate the Step 1 JSON blobs in `media_records`.

Instead, it creates and maintains a separate table:

- `subtitle_track_language_labels`

This keeps Step 1 inventory immutable and makes Step 2 safe to rerun.

## Review states

Each subtitle track is stored with one of these `review_status` values:

- `trusted_existing` — existing language tag was present and trusted; no detection run
- `detected` — language detected with confidence above threshold
- `uncertain` — detection confidence below threshold, or no text/audio signal available
- `needs_ocr` — image-based subtitle codec; text detection cannot run

## Detector modes

Step 2 supports three detector modes, configured via `Step2Config.detector_mode` or `--detector-mode`:

| Mode | Behaviour |
|---|---|
| `auto` | Prefer `lingua` when installed; fall back to `langdetect` |
| `lingua` | Use `lingua-language-detector` only; raise if not installed |
| `langdetect` | Use `langdetect` only; raise if not installed |

Default: `auto`

The engine that produced the result is persisted in `detector_engine`.

## Configuration

`Step2Config` controls all runtime behaviour:

| Field | Default | Description |
|---|---|---|
| `detector_mode` | `auto` | Detector to use (`auto`, `lingua`, `langdetect`) |
| `confidence_threshold` | `0.90` | Minimum confidence to store result as `detected` |
| `min_sample_length` | `20` | Minimum cleaned-text chars before running text detection |
| `whisper_fallback_enabled` | `False` | Enable Whisper audio language detection fallback |
| `whisper_model` | `base` | faster-whisper model size (placeholder) |

## Detection logic

### Trusted tags

If the track language tag is present and trusted, Step 2 stores the normalized language and skips detection.

Examples:

- `eng` → `en`
- `jpn` → `ja`
- `fra` → `fr`

### Suspicious tags

These are treated as not trustworthy and go through detection:

- `und`
- `unk`
- `unknown`
- `mis`
- `mul`
- empty or missing tags

### Text subtitle tracks

For text-capable subtitles, Step 2:

1. extracts subtitle text
2. cleans timestamps and markup
3. limits the sample to 2000 characters
4. checks sample length against `min_sample_length`
5. if sample is long enough: runs the configured text detector
6. if sample is too short: runs Whisper fallback (if enabled), otherwise stores `uncertain`
7. stores: detected language, confidence, engine name, review status

If confidence is greater than `confidence_threshold` (default `0.90`), the result is stored as `detected`.
Otherwise it is stored as `uncertain` for manual review.

### Whisper fallback

When text detection cannot reasonably run — because:

- embedded subtitle extraction fails
- extracted/cleaned subtitle text is empty or shorter than `min_sample_length`

…Step 2 can optionally call faster-whisper for audio language detection.

Whisper fallback is **disabled by default**. Enable it with `--whisper-fallback` or `Step2Config(whisper_fallback_enabled=True)`.

Requirements:
- language detection only — no transcription output is produced
- local-only (cpu, int8)
- engine name `whisper_language` is persisted in `detector_engine`
- if Whisper itself fails or returns low confidence, result is stored as `uncertain`

### Image-based subtitle tracks

These are not passed through text language detection.

They are stored as:

- `review_status = needs_ocr`
- `ocr_state = future`

Currently recognized image-based codecs:

- `hdmv_pgs_subtitle`
- `dvd_subtitle`
- `dvb_subtitle`
- `xsub`

## Embedded vs sidecar subtitles

### Embedded subtitles

Text-capable embedded subtitle tracks are extracted with `ffmpeg` to a temporary text file before detection.

### Sidecar subtitles

Sidecar `.srt` and `.ass` files are read directly.

If a sidecar filename already contains a trusted language suffix like `movie.en.srt`, Step 2 treats that as trusted and skips redetection.

## CLI

```bash
python services/media_brain/step2_subtitle_language.py --db-path ./media_brain.db
```

Available flags:

```
--db-path             SQLite database created by Step 1 (default: media_brain.db)
--temp-root           Temporary directory for subtitle extraction
--detector-mode       auto | lingua | langdetect (default: auto)
--confidence-threshold  Minimum confidence for detected status (default: 0.90)
--min-sample-length   Minimum sample chars before text detection (default: 20)
--whisper-fallback    Enable Whisper audio language detection fallback
--whisper-model       faster-whisper model size (default: base)
```

Example with Whisper fallback:

```bash
python services/media_brain/step2_subtitle_language.py \
  --db-path ./media_brain.db \
  --detector-mode lingua \
  --whisper-fallback \
  --whisper-model small
```

## Dependencies

Install the text detector(s) before running Step 2:

```bash
# langdetect only (lightweight)
pip install "media-platform[subtitle-detect]"

# or directly:
pip install langdetect

# lingua (more accurate, higher memory)
pip install lingua-language-detector

# Whisper fallback (optional)
pip install faster-whisper
```

Or install the optional dependency groups from `pyproject.toml`:

```bash
pip install -e ".[subtitle-detect]"
pip install -e ".[subtitle-whisper]"
```

## Tests

```bash
pytest tests/test_media_brain_step2_subtitle_language.py -v
```

## Scope boundary

Implemented here:

- trusted-tag skip logic
- text subtitle extraction
- text cleanup
- local language detection via `langdetect`, `lingua`, or `auto`
- Whisper audio language detection fallback (detection only, no transcription)
- low-confidence manual-review queueing
- image-subtitle OCR deferral
- SQLite persistence per subtitle track
- configurable detector mode and confidence threshold

Not implemented here:

- OCR
- automatic retagging back into media containers
- automatic language correction for sidecar filenames
- media state promotion to a later workflow stage
- Whisper full transcription
