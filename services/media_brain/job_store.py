"""Job store for media_brain processing jobs and state transitions.

Provides two tables:
  processing_jobs    — durable record of every worker job dispatched
  state_transitions  — audit trail of every media_record state change

These tables are written by Steps 3, 4, and any future steps that mutate
media_records.state.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_job_tables(connection: sqlite3.Connection) -> None:
    """Create processing_jobs and state_transitions tables if they do not exist."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_jobs (
            job_id        TEXT PRIMARY KEY,
            media_id      TEXT NOT NULL,
            job_type      TEXT NOT NULL,
            status        TEXT NOT NULL,
            worker_url    TEXT,
            created_at    TEXT NOT NULL,
            started_at    TEXT,
            completed_at  TEXT,
            error_message TEXT,
            notes         TEXT,
            FOREIGN KEY(media_id) REFERENCES media_records(media_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_processing_jobs_media_id
        ON processing_jobs(media_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_processing_jobs_status
        ON processing_jobs(status)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS state_transitions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id        TEXT NOT NULL,
            from_state      TEXT NOT NULL,
            to_state        TEXT NOT NULL,
            job_id          TEXT,
            reason          TEXT,
            transitioned_at TEXT NOT NULL,
            FOREIGN KEY(media_id) REFERENCES media_records(media_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_state_transitions_media_id
        ON state_transitions(media_id)
        """
    )


def record_state_transition(
    connection: sqlite3.Connection,
    media_id: str,
    from_state: str,
    to_state: str,
    *,
    job_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Append one row to state_transitions."""
    connection.execute(
        """
        INSERT INTO state_transitions
            (media_id, from_state, to_state, job_id, reason, transitioned_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (media_id, from_state, to_state, job_id, reason, _utc_now()),
    )


def upsert_processing_job(
    connection: sqlite3.Connection,
    job_id: str,
    media_id: str,
    job_type: str,
    status: str,
    *,
    worker_url: str | None = None,
) -> None:
    """Insert or update one row in processing_jobs."""
    connection.execute(
        """
        INSERT INTO processing_jobs
            (job_id, media_id, job_type, status, worker_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            status     = excluded.status,
            worker_url = excluded.worker_url
        """,
        (job_id, media_id, job_type, status, worker_url, _utc_now()),
    )


def mark_job_running(connection: sqlite3.Connection, job_id: str) -> None:
    """Set a job's status to 'running' and record its start time."""
    connection.execute(
        "UPDATE processing_jobs SET status = 'running', started_at = ? WHERE job_id = ?",
        (_utc_now(), job_id),
    )


def mark_job_complete(
    connection: sqlite3.Connection,
    job_id: str,
    *,
    notes: str | None = None,
) -> None:
    """Set a job's status to 'complete' and record its completion time."""
    connection.execute(
        "UPDATE processing_jobs SET status = 'complete', completed_at = ?, notes = ? WHERE job_id = ?",
        (_utc_now(), notes, job_id),
    )


def mark_job_failed(
    connection: sqlite3.Connection,
    job_id: str,
    error_message: str,
) -> None:
    """Set a job's status to 'failed' with an error message."""
    connection.execute(
        "UPDATE processing_jobs SET status = 'failed', completed_at = ?, error_message = ? WHERE job_id = ?",
        (_utc_now(), error_message, job_id),
    )
