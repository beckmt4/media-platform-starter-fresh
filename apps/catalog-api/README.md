# catalog-api

Source-of-truth catalog and state API for the media platform.

Tracks:
- media item state (inbox → review → active / quarantine / locked)
- arr lock state (manual-source, block-upgrades, monitored flag)
- review queue (items flagged for human decision before any mutation)

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
| GET | /health | Health check (includes store backend) |
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

| Variable | Default | Description |
|---|---|---|
| `CATALOG_DB_PATH` | _(unset)_ | Path to SQLite database file. When unset, the in-memory store is used (state lost on restart). |

### Storage backends

| Backend | When | Use case |
|---------|------|----------|
| In-memory | `CATALOG_DB_PATH` unset | Development and tests |
| SQLite (WAL) | `CATALOG_DB_PATH` set | Production on Unraid (`/data/catalog.db`) |

SQLite uses WAL journal mode and a single-connection write lock. Items are
stored as JSON blobs — no schema migrations needed when fields are added.

The active backend is logged at startup:

```
catalog-api store backend=sqlite:/data/catalog.db
```
