from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Generator

from .models import AudioTrackInfo, MediaBrainState, MediaItem, SubtitleTrackInfo, VideoTrackInfo

log = logging.getLogger("media_brain.store")

_DDL = """
CREATE TABLE IF NOT EXISTS media_items (
    media_id            TEXT PRIMARY KEY,
    file_path           TEXT NOT NULL,
    file_size           INTEGER NOT NULL,
    state               TEXT NOT NULL DEFAULT 'needs_subtitle_review',
    container_format    TEXT,
    duration_seconds    REAL,
    video_tracks        TEXT NOT NULL DEFAULT '[]',
    audio_tracks        TEXT NOT NULL DEFAULT '[]',
    subtitle_tracks     TEXT NOT NULL DEFAULT '[]',
    sidecar_files       TEXT NOT NULL DEFAULT '[]',
    scanned_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    error_message       TEXT
);

CREATE INDEX IF NOT EXISTS idx_media_items_state ON media_items (state);
CREATE INDEX IF NOT EXISTS idx_media_items_file_path ON media_items (file_path);
"""


class MediaBrainStore:
    """SQLite-backed store for MediaItem records."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_DDL)
        log.info("store: initialised db at %s", self._db_path)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, item: MediaItem) -> None:
        """Insert or replace a MediaItem."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO media_items (
                    media_id, file_path, file_size, state, container_format,
                    duration_seconds, video_tracks, audio_tracks, subtitle_tracks,
                    sidecar_files, scanned_at, updated_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_id) DO UPDATE SET
                    file_path        = excluded.file_path,
                    file_size        = excluded.file_size,
                    state            = excluded.state,
                    container_format = excluded.container_format,
                    duration_seconds = excluded.duration_seconds,
                    video_tracks     = excluded.video_tracks,
                    audio_tracks     = excluded.audio_tracks,
                    subtitle_tracks  = excluded.subtitle_tracks,
                    sidecar_files    = excluded.sidecar_files,
                    updated_at       = excluded.updated_at,
                    error_message    = excluded.error_message
                """,
                (
                    item.media_id,
                    item.file_path,
                    item.file_size,
                    item.state,
                    item.container_format,
                    item.duration_seconds,
                    json.dumps([t.model_dump() for t in item.video_tracks]),
                    json.dumps([t.model_dump() for t in item.audio_tracks]),
                    json.dumps([t.model_dump() for t in item.subtitle_tracks]),
                    json.dumps(item.sidecar_files),
                    item.scanned_at.isoformat(),
                    now,
                    item.error_message,
                ),
            )
        log.debug("store: upserted media_id=%s state=%s", item.media_id, item.state)

    def update_state(self, media_id: str, state: MediaBrainState) -> bool:
        """Update only the state field. Returns True if the row existed."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE media_items SET state = ?, updated_at = ? WHERE media_id = ?",
                (state, now, media_id),
            )
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, media_id: str) -> MediaItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM media_items WHERE media_id = ?", (media_id,)
            ).fetchone()
        return _row_to_item(row) if row else None

    def get_by_path(self, file_path: str) -> MediaItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM media_items WHERE file_path = ?", (file_path,)
            ).fetchone()
        return _row_to_item(row) if row else None

    def list_items(
        self,
        state: MediaBrainState | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[MediaItem]:
        with self._connect() as conn:
            if state is not None:
                rows = conn.execute(
                    "SELECT * FROM media_items WHERE state = ? ORDER BY scanned_at DESC LIMIT ? OFFSET ?",
                    (state, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM media_items ORDER BY scanned_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return [_row_to_item(r) for r in rows]

    def count(self, state: MediaBrainState | None = None) -> int:
        with self._connect() as conn:
            if state is not None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM media_items WHERE state = ?", (state,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM media_items").fetchone()
        return row[0]


# ---------------------------------------------------------------------------
# Row deserialisation
# ---------------------------------------------------------------------------

def _row_to_item(row: sqlite3.Row) -> MediaItem:
    return MediaItem(
        media_id=row["media_id"],
        file_path=row["file_path"],
        file_size=row["file_size"],
        state=MediaBrainState(row["state"]),
        container_format=row["container_format"],
        duration_seconds=row["duration_seconds"],
        video_tracks=[VideoTrackInfo(**t) for t in json.loads(row["video_tracks"])],
        audio_tracks=[AudioTrackInfo(**t) for t in json.loads(row["audio_tracks"])],
        subtitle_tracks=[SubtitleTrackInfo(**t) for t in json.loads(row["subtitle_tracks"])],
        sidecar_files=json.loads(row["sidecar_files"]),
        scanned_at=datetime.fromisoformat(row["scanned_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        error_message=row["error_message"],
    )
