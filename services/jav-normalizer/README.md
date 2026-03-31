# jav-normalizer

JAV title ID parser, normalizer, and metadata enricher. Extracts structured
title metadata from raw filenames or title strings, then optionally fetches
full metadata from a self-hosted local metadata service.

## What it does

1. Accepts a raw filename, title string, or file path.
2. Strips noise tokens (resolution tags, release group brackets, extensions).
3. Extracts the studio code and title number using a regex pattern.
4. Returns a canonical ID in `STUDIO-NUMBER` form (e.g. `SSIS-123`).
5. Strips known suffix flags (`C`, `UC`, `R`) and reports them separately.
6. Returns `no_id_found` when no recognisable pattern is present.
7. Returns `ambiguous` when multiple candidate IDs are found in one string.
8. Optionally enriches the canonical ID by calling a local metadata service
   (`JAV_METADATA_URL`) for title, studio, cast, genres, and cover art.

## ID format

```
[STUDIO_CODE]-[TITLE_NUMBER][-SUFFIX]
```

| Part | Rules |
|------|-------|
| Studio code | 1–6 uppercase letters (e.g. `SSIS`, `IPX`, `PRED`, `BF`) |
| Title number | 3–5 digits, preserved as-is (leading zeros kept) |
| Suffix | Optional: `C` (censored), `UC` (uncensored), `R` (remaster) |

## Example inputs → outputs

| Input | Canonical ID | Notes |
|-------|-------------|-------|
| `SSIS-123.mkv` | `SSIS-123` | Standard |
| `ssis123.mkv` | `SSIS-123` | Lowercase, no hyphen |
| `[PRED-456] Title.mkv` | `PRED-456` | Bracketed |
| `ABW-001.1080p.BluRay.x265.mkv` | `ABW-001` | Noise stripped |
| `PRED-456-UC.mkv` | `PRED-456` | UC suffix stripped |
| `FC2-PPV-12345.mkv` | `FC2-12345` or `PPV-12345` | May be ambiguous |
| `Some Movie.mkv` | — | `no_id_found` |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /normalize | Parse and normalize a raw title string |
| POST | /enrich | Fetch metadata for a canonical ID from the local metadata service |
| POST | /normalize-and-enrich | Parse then enrich in one call; enrich is skipped if no ID found |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `JAV_METADATA_URL` | _(unset)_ | Base URL of a self-hosted metadata service (e.g. `http://javinfo-api:8800`). When unset, `/enrich` returns `unavailable`. |

The enricher calls `GET {JAV_METADATA_URL}/movie/{canonical_id}` and maps the
JSON response to `JavMetadata`. All fields are optional — the enricher never
raises on partial or empty responses.

### Enrich status values

| Status | Meaning |
|--------|---------|
| `ok` | Metadata returned successfully |
| `not_found` | Service responded with 404 — ID not in its database |
| `unavailable` | `JAV_METADATA_URL` not configured |
| `error` | Network failure, timeout, or invalid JSON response |

## Running locally

```bash
cd services/jav-normalizer
pip install -e ".[dev]"
uvicorn jav_normalizer.main:app --reload --port 8003
```

## Running tests

```bash
cd services/jav-normalizer
pytest
```

No metadata service required — enricher calls are monkeypatched in tests.
