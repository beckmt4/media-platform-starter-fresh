from __future__ import annotations

from datetime import datetime, timezone

from .models import ArrLockState, MediaItem, MediaItemUpdate, ReviewQueueEntry


class CatalogStore:
    """In-memory store for the catalog-api skeleton.

    Replace with a persistent backend (SQLite, Postgres, etc.) before
    running in production. All mutation methods update `updated_at` on
    affected MediaItem records.
    """

    def __init__(self) -> None:
        self._items: dict[str, MediaItem] = {}
        self._arr_locks: dict[str, ArrLockState] = {}
        self._review_queue: dict[str, ReviewQueueEntry] = {}

    # --- MediaItem ---

    def list_items(self) -> list[MediaItem]:
        return list(self._items.values())

    def get_item(self, item_id: str) -> MediaItem | None:
        return self._items.get(item_id)

    def create_item(self, item: MediaItem) -> MediaItem:
        self._items[item.id] = item
        return item

    def update_item(self, item_id: str, patch: MediaItemUpdate) -> MediaItem | None:
        item = self._items.get(item_id)
        if item is None:
            return None
        data = item.model_dump()
        for field, value in patch.model_dump(exclude_unset=True).items():
            data[field] = value
        data["updated_at"] = datetime.now(timezone.utc)
        updated = MediaItem.model_validate(data)
        self._items[item_id] = updated
        return updated

    # --- ArrLockState ---

    def get_lock(self, item_id: str) -> ArrLockState | None:
        return self._arr_locks.get(item_id)

    def set_lock(self, lock: ArrLockState) -> ArrLockState:
        self._arr_locks[lock.item_id] = lock
        return lock

    # --- ReviewQueue ---

    def list_queue(self, *, include_resolved: bool = False) -> list[ReviewQueueEntry]:
        return [
            e for e in self._review_queue.values()
            if include_resolved or not e.resolved
        ]

    def get_queue_entry(self, entry_id: str) -> ReviewQueueEntry | None:
        return self._review_queue.get(entry_id)

    def create_queue_entry(self, entry: ReviewQueueEntry) -> ReviewQueueEntry:
        self._review_queue[entry.id] = entry
        return entry

    def resolve_queue_entry(
        self, entry_id: str, resolution_note: str | None = None
    ) -> ReviewQueueEntry | None:
        entry = self._review_queue.get(entry_id)
        if entry is None or entry.resolved:
            return None
        data = entry.model_dump()
        data["resolved"] = True
        data["resolved_at"] = datetime.now(timezone.utc)
        data["resolution_note"] = resolution_note
        resolved = ReviewQueueEntry.model_validate(data)
        self._review_queue[entry_id] = resolved
        return resolved


# Module-level singleton used by the FastAPI app.
store = CatalogStore()
