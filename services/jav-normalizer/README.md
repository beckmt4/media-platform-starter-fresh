# jav-normalizer

JAV title ID parser and normalizer. Extracts structured title metadata from
raw filenames or title strings. No file system access, no network calls.

## Status

Stub — regex-based ID parsing only. Enrichment (metadata lookup from external
databases) is out of scope for this stub.

## What it does

1. Accepts a raw filename, title string, or file path.
2. Strips noise tokens (resolution tags, release group brackets, extensions).
3. Extracts the studio code and title number using a regex pattern.
4. Returns a canonical ID in `STUDIO-NUMBER` form (e.g. `SSIS-123`).
5. Strips known suffix flags (`C`, `UC`, `R`) and reports them separately.
6. Returns `no_id_found` when no recognisable pattern is present.
7. Returns `ambiguous` when multiple candidate IDs are found in one string.

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

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /normalize | Parse and normalize a raw title string |

## Next steps

- Add enrichment: submit canonical ID to a local metadata cache or scraper.
- Handle hyphenated studio codes (e.g. `E-BODY`, `S-CUTE`).
- Add a `/normalize/batch` endpoint for manifest-level processing.
- Wire into the catalog-api ingestion workflow.
