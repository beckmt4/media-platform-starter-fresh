# catalog-api

Source-of-truth catalog and state API for the media platform.

Tracks:
- media item state (inbox → review → active / quarantine / locked)
- arr lock state (manual-source, block-upgrades, monitored flag)
- review queue (items flagged for human decision before any mutation)

## Status

Skeleton — in-memory store only. No persistence, no file-system access, no live media.

## Running locally

```bash
cd apps/catalog-api
pip install -e ".[dev]"
uvicorn catalog_api.main:app --reload
```

API docs available at `http://localhost:8000/docs`.

## Running tests

```bash
cd apps/catalog-api
pytest
```

## Linting

```bash
ruff check catalog_api tests
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| GET | /items | List all media items |
| POST | /items | Register a new media item |
| GET | /items/{id} | Get a single media item |
| PATCH | /items/{id} | Update state, tags, or flags |
| GET | /items/{id}/lock | Get arr lock state |
| PUT | /items/{id}/lock | Set arr lock state |
| GET | /review-queue | List unresolved review queue entries |
| POST | /review-queue | Add an item to the review queue |
| POST | /review-queue/{id}/resolve | Resolve a review queue entry |

## Configuration

Copy `config.sample.yaml` to `config.yaml` and adjust. The `storage.backend`
key controls which store is used (`memory` is the skeleton default).

## Next steps

- Swap the in-memory store for SQLite or Postgres.
- Add pagination to list endpoints.
- Wire up to `services/media-policy-engine` for policy-driven state transitions.
- Add authentication for homelab network boundary.
