# subtitle-intel

Subtitle inspection service. Reads container metadata via mediainfo and returns
per-track facts (language, confidence, track type) that feed into the
`media-policy-engine` evaluator.

## Status

Stub — metadata-only language detection. Tracks with no language tag return
`detected_language="unknown"` and `confidence=0.0`. A production implementation
would submit those tracks to a faster-whisper pass for audio-based detection.

## What it does

1. Accepts a file path (and optionally a pre-parsed mediainfo JSON blob).
2. Runs `mediainfo --Output=JSON` on the file (skipped when JSON is supplied).
3. Extracts all `Text` tracks from the output.
4. Normalises ISO 639-2 language tags to ISO 639-1.
5. Classifies each track as `forced`, `sdh`, `signs_songs`, or `full` based
   on the container forced flag and track title keywords.
6. Returns a `ScanResult` with per-track `SubtitleTrackInfo` records.

## Track type classification

| Condition | Type |
|-----------|------|
| `Forced: Yes` in container | `forced` |
| Title contains "SDH", "Hearing Impaired", "CC" | `sdh` |
| Title contains "Signs", "Songs" | `signs_songs` |
| Otherwise | `full` |

## Output alignment with media-policy-engine

`SubtitleTrackInfo` maps directly to `SubtitleTrackFacts` in the policy engine:

| subtitle-intel | media-policy-engine |
|----------------|---------------------|
| `track_index` | `track_index` |
| `detected_language` | `language` |
| `confidence` | `confidence` |
| `track_type` | `track_type` |

## Running locally

```bash
cd services/subtitle-intel
pip install -e ".[dev]"
uvicorn subtitle_intel.main:app --reload --port 8002
```

Requires `mediainfo` on PATH for live file scanning. Not required for tests.

## Running tests

```bash
cd services/subtitle-intel
pytest
```

All tests use fixture JSON files — no mediainfo installation required.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /scan | Scan a file or parse supplied mediainfo JSON |

## Next steps

- Submit `confidence=0.0` tracks to a faster-whisper language detection pass.
- Add a `/scan/batch` endpoint for multi-file manifests.
- Wire output to `media-policy-engine /evaluate` in the orchestration workflow.
