from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Query

from .models import (
    DirectoryScanRequest,
    DirectoryScanResponse,
    FileScanRequest,
    ItemListResponse,
    MediaBrainState,
    MediaItem,
)
from .scanner import MediaBrainScanner
from .store import MediaBrainStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("media_brain.main")

app = FastAPI(title="media-brain", version="0.1.0")

_DB_PATH = os.environ.get("MEDIA_BRAIN_DB_PATH", "/data/media_brain.db")

_store: MediaBrainStore | None = None
_scanner = MediaBrainScanner()


def _get_store() -> MediaBrainStore:
    global _store
    if _store is None:
        _store = MediaBrainStore(_DB_PATH)
    return _store


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    store = _get_store()
    total = store.count()
    return {"status": "ok", "total_items": total}


# ---------------------------------------------------------------------------
# Scan endpoints
# ---------------------------------------------------------------------------

@app.post("/scan/file", response_model=MediaItem)
def scan_file(req: FileScanRequest) -> MediaItem:
    """Scan a single media file and persist the result."""
    log.info("scan_file: %s", req.file_path)
    item = _scanner.scan_file(req.file_path, mediainfo_json=req.mediainfo_json)
    _get_store().upsert(item)
    return item


@app.post("/scan/directory", response_model=DirectoryScanResponse)
def scan_directory(req: DirectoryScanRequest) -> DirectoryScanResponse:
    """Recursively scan a directory for media files and persist results."""
    log.info("scan_directory: %s extensions=%s recursive=%s", req.directory, req.extensions, req.recursive)
    items = _scanner.scan_directory(req.directory, req.extensions, req.recursive)
    store = _get_store()
    for item in items:
        store.upsert(item)

    errors = sum(1 for i in items if i.state == MediaBrainState.error)
    log.info("scan_directory: done total=%d errors=%d", len(items), errors)

    return DirectoryScanResponse(
        directory=req.directory,
        total_files=len(items),
        scanned=len(items) - errors,
        errors=errors,
        items=items,
    )


# ---------------------------------------------------------------------------
# Item retrieval
# ---------------------------------------------------------------------------

@app.get("/items", response_model=ItemListResponse)
def list_items(
    state: MediaBrainState | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ItemListResponse:
    store = _get_store()
    items = store.list_items(state=state, limit=limit, offset=offset)
    total = store.count(state=state)
    return ItemListResponse(total=total, items=items)


@app.get("/items/{media_id}", response_model=MediaItem)
def get_item(media_id: str) -> MediaItem:
    item = _get_store().get(media_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"media_id not found: {media_id}")
    return item


@app.patch("/items/{media_id}/state", response_model=MediaItem)
def update_item_state(media_id: str, state: MediaBrainState) -> MediaItem:
    """Manually transition an item's state (e.g. 'reviewed')."""
    store = _get_store()
    updated = store.update_state(media_id, state)
    if not updated:
        raise HTTPException(status_code=404, detail=f"media_id not found: {media_id}")
    item = store.get(media_id)
    return item  # type: ignore[return-value]
