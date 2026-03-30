from __future__ import annotations

import logging
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .models import (
    ArrLockState,
    MediaItem,
    MediaItemUpdate,
    ReviewQueueEntry,
    ReviewQueueResolve,
)
from .store import store

# --- Structured logging ---
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("catalog_api")

app = FastAPI(title="catalog-api", version="0.1.0")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Media items
# ---------------------------------------------------------------------------

@app.get("/items", response_model=list[MediaItem], tags=["items"])
def list_items() -> list[MediaItem]:
    return store.list_items()


@app.post("/items", response_model=MediaItem, status_code=201, tags=["items"])
def create_item(item: MediaItem) -> MediaItem:
    created = store.create_item(item)
    log.info("item created id=%s title=%r domain=%s", created.id, created.title, created.domain)
    return created


@app.get("/items/{item_id}", response_model=MediaItem, tags=["items"])
def get_item(item_id: str) -> MediaItem:
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@app.patch("/items/{item_id}", response_model=MediaItem, tags=["items"])
def update_item(item_id: str, patch: MediaItemUpdate) -> MediaItem:
    updated = store.update_item(item_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="item not found")
    log.info("item updated id=%s", item_id)
    return updated


# ---------------------------------------------------------------------------
# Arr lock state
# ---------------------------------------------------------------------------

@app.get("/items/{item_id}/lock", response_model=ArrLockState, tags=["locks"])
def get_lock(item_id: str) -> ArrLockState:
    if store.get_item(item_id) is None:
        raise HTTPException(status_code=404, detail="item not found")
    lock = store.get_lock(item_id)
    if lock is None:
        raise HTTPException(status_code=404, detail="lock state not found")
    return lock


@app.put("/items/{item_id}/lock", response_model=ArrLockState, tags=["locks"])
def set_lock(item_id: str, lock: ArrLockState) -> ArrLockState:
    if store.get_item(item_id) is None:
        raise HTTPException(status_code=404, detail="item not found")
    if lock.item_id != item_id:
        raise HTTPException(status_code=422, detail="item_id mismatch")
    saved = store.set_lock(lock)
    log.info("lock set item_id=%s block_upgrades=%s", item_id, saved.block_upgrades)
    return saved


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

@app.get("/review-queue", response_model=list[ReviewQueueEntry], tags=["review-queue"])
def list_queue(include_resolved: bool = False) -> list[ReviewQueueEntry]:
    return store.list_queue(include_resolved=include_resolved)


@app.post("/review-queue", response_model=ReviewQueueEntry, status_code=201, tags=["review-queue"])
def create_queue_entry(entry: ReviewQueueEntry) -> ReviewQueueEntry:
    if store.get_item(entry.item_id) is None:
        raise HTTPException(status_code=404, detail="item not found")
    created = store.create_queue_entry(entry)
    log.info(
        "review queue entry created id=%s item_id=%s reason=%r",
        created.id, created.item_id, created.reason,
    )
    return created


@app.post(
    "/review-queue/{entry_id}/resolve",
    response_model=ReviewQueueEntry,
    tags=["review-queue"],
)
def resolve_queue_entry(entry_id: str, body: ReviewQueueResolve) -> ReviewQueueEntry:
    resolved = store.resolve_queue_entry(entry_id, resolution_note=body.resolution_note)
    if resolved is None:
        raise HTTPException(status_code=404, detail="entry not found or already resolved")
    log.info("review queue entry resolved id=%s", entry_id)
    return resolved
