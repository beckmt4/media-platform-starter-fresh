from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime

from .models import ArrLockState, MediaItem, MediaItemUpdate, ReviewQueueEntry


# ---------------------------------------------------------------------------
# In-memory store (default / tests)
# ---------------------------------------------------------------------------

class MemoryCatalogStore:
    """In-memory store for tests and local dev without a DB file."""

    def __init__(self) -> None:
        self._items: dict[str, MediaItem] = {}
        self._arr_locks: dict[str, ArrLockState] = {}
        self._review_queue: dict[str, ReviewQueueEntry] = {}

    def reset(self) -> None:
        self._items.clear()
        self._arr_locks.clear()
        self._review_queue.clear()

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
        data["updated_at"] = datetime.now(UTC)
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
        data["resolved_at"] = datetime.now(UTC)
        data["resolution_note"] = resolution_note
        resolved = ReviewQueueEntry.model_validate(data)
        self._review_queue[entry_id] = resolved
        return resolved


# ---------------------------------------------------------------------------
# SQLite-backed store
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id   TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS arr_locks (
    item_id TEXT PRIMARY KEY,
    data    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_queue (
    id   TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
"""


class SQLiteCatalogStore:
    """Persistent store backed by a local SQLite database.

    Each row stores the full Pydantic model as a JSON blob so the schema
    never needs migrations when non-indexed fields change.

    Thread-safe: a single connection is reused with check_same_thread=False
    and all writes are serialised through a threading.Lock.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def reset(self) -> None:
        """Delete all rows — intended for tests using an in-memory DB."""
        with self._lock:
            self._conn.executescript(
                "DELETE FROM items; DELETE FROM arr_locks; DELETE FROM review_queue;"
            )
            self._conn.commit()

    # --- helpers ---

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def _exec_write(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    # --- MediaItem ---

    def list_items(self) -> list[MediaItem]:
        rows = self._exec("SELECT data FROM items").fetchall()
        return [MediaItem.model_validate(json.loads(r[0])) for r in rows]

    def get_item(self, item_id: str) -> MediaItem | None:
        row = self._exec("SELECT data FROM items WHERE id = ?", (item_id,)).fetchone()
        return MediaItem.model_validate(json.loads(row[0])) if row else None

    def create_item(self, item: MediaItem) -> MediaItem:
        self._exec_write(
            "INSERT INTO items (id, data) VALUES (?, ?)",
            (item.id, item.model_dump_json()),
        )
        return item

    def update_item(self, item_id: str, patch: MediaItemUpdate) -> MediaItem | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                return None
            data = json.loads(row[0])
            for field, value in patch.model_dump(exclude_unset=True).items():
                data[field] = value
            data["updated_at"] = datetime.now(UTC).isoformat()
            updated = MediaItem.model_validate(data)
            self._conn.execute(
                "UPDATE items SET data = ? WHERE id = ?",
                (updated.model_dump_json(), item_id),
            )
            self._conn.commit()
        return updated

    # --- ArrLockState ---

    def get_lock(self, item_id: str) -> ArrLockState | None:
        row = self._exec(
            "SELECT data FROM arr_locks WHERE item_id = ?", (item_id,)
        ).fetchone()
        return ArrLockState.model_validate(json.loads(row[0])) if row else None

    def set_lock(self, lock: ArrLockState) -> ArrLockState:
        self._exec_write(
            "INSERT INTO arr_locks (item_id, data) VALUES (?, ?)"
            " ON CONFLICT(item_id) DO UPDATE SET data = excluded.data",
            (lock.item_id, lock.model_dump_json()),
        )
        return lock

    # --- ReviewQueue ---

    def list_queue(self, *, include_resolved: bool = False) -> list[ReviewQueueEntry]:
        if include_resolved:
            rows = self._exec("SELECT data FROM review_queue").fetchall()
        else:
            # Filter in Python — the resolved flag is inside the JSON blob.
            rows = self._exec("SELECT data FROM review_queue").fetchall()
        entries = [ReviewQueueEntry.model_validate(json.loads(r[0])) for r in rows]
        if not include_resolved:
            entries = [e for e in entries if not e.resolved]
        return entries

    def get_queue_entry(self, entry_id: str) -> ReviewQueueEntry | None:
        row = self._exec(
            "SELECT data FROM review_queue WHERE id = ?", (entry_id,)
        ).fetchone()
        return ReviewQueueEntry.model_validate(json.loads(row[0])) if row else None

    def create_queue_entry(self, entry: ReviewQueueEntry) -> ReviewQueueEntry:
        self._exec_write(
            "INSERT INTO review_queue (id, data) VALUES (?, ?)",
            (entry.id, entry.model_dump_json()),
        )
        return entry

    def resolve_queue_entry(
        self, entry_id: str, resolution_note: str | None = None
    ) -> ReviewQueueEntry | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM review_queue WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return None
            data = json.loads(row[0])
            if data.get("resolved"):
                return None
            data["resolved"] = True
            data["resolved_at"] = datetime.now(UTC).isoformat()
            data["resolution_note"] = resolution_note
            resolved = ReviewQueueEntry.model_validate(data)
            self._conn.execute(
                "UPDATE review_queue SET data = ? WHERE id = ?",
                (resolved.model_dump_json(), entry_id),
            )
            self._conn.commit()
        return resolved


# ---------------------------------------------------------------------------
# Module-level singleton — routes import this directly.
# Set CATALOG_DB_PATH to a file path to use SQLite persistence.
# Leave unset (or set to "") to use the in-memory store (tests / ephemeral).
# ---------------------------------------------------------------------------

_db_path = os.environ.get("CATALOG_DB_PATH", "").strip()

if _db_path:
    store: MemoryCatalogStore | SQLiteCatalogStore = SQLiteCatalogStore(_db_path)
else:
    store = MemoryCatalogStore()
