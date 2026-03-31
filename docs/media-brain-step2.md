# media-brain Step 2

Step 2 adds per-track subtitle language detection on top of the Step 1 inventory database.

## Goal

For each subtitle track discovered in Step 1:

- trust valid existing language tags and skip re-detection
- detect language for `und`, missing, or suspicious tags
- extract up to 2000 characters of subtitle text
- use a local Python detector (`langdetect`)
- mark low-confidence results as `uncertain`
- flag image-based subtitles for future OCR work
- store one row per subtitle track in SQLite

## Files added

- `services/media_brain/step2_subtitle_language.py`
- `tests/test_media_brain_step2_subtitle_language.py`

## Storage model

Step 2 does **not** mutate the Step 1 JSON blobs in `media_records`.

Instead, it creates and maintains a separate table:

- `subtitle_track_language_labels`

This keeps Step 1 inventory immutable and makes Step 2 safe to rerun.

## Review states

Each subtitle track is stored with one of these `review_status` values:

- `trusted_existing`
- `detected`
- `uncertain`
- `needs_ocr`

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
4. runs `langdetect`
5. stores:
   - detected language
   - confidence
   - engine name
   - review status

If confidence is greater than `0.90`, the result is stored as `detected`.

Otherwise it is stored as `uncertain` for manual review.

### Image-based subtitle tracks

These are not passed through text language detection.

They are stored as:

- `review_status = needs_ocr`
- `ocr_state = future`

Currently recognized image-based codecs include:

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

Optional temp root:

```bash
python services/media_brain/step2_subtitle_language.py \
  --db-path ./media_brain.db \
  --temp-root ./temp/media_brain_step2
```

## Dependency

Install the local detector before running Step 2:

```bash
pip install langdetect
```

## Tests

Run the Step 2 tests with:

```bash
pytest tests/test_media_brain_step2_subtitle_language.py -v
```

## Scope boundary

Implemented here:

- trusted-tag skip logic
- text subtitle extraction
- text cleanup
- local language detection
- low-confidence manual-review queueing
- image-subtitle OCR deferral
- SQLite persistence per subtitle track

Not implemented here:

- OCR
- Whisper language detection fallback
- automatic retagging back into media containers
- automatic language correction for sidecar filenames
- media state promotion to a later workflow stage
