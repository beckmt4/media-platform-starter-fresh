"""Step 4 dispatcher for media_brain.

Reads records in state 'needs_subtitle_generation' from media_brain.db and
submits a generate job to the subtitle-worker HTTP API for each one.

State transitions written here:
  needs_subtitle_generation → subtitle_generation_queued  (HTTP 200/201)
  needs_subtitle_generation → (unchanged, retryable)       (HTTP error)

Idempotency: only records in needs_subtitle_generation are selected.
Re-running after a partial failure retries only the failed records.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("media_brain.step4_dispatch")

SOURCE_STATE = "needs_subtitle_generation"
QUEUED_STATE = "subtitle_generation_queued"

# Default worker URL; override with SUBTITLE_WORKER_URL environment variable.
_DEFAULT_WORKER_URL = "http://localhost:8100"

# The subtitle worker's /jobs endpoint runs transcription synchronously.
# A 2-hour file chunked into 30-min segments can take 30-60+ min on CPU.
_HTTP_TIMEOUT = 3600  # seconds; set SUBTITLE_DISPATCH_TIMEOUT env var to override

DEFAULT_DB_PATH = Path("media_brain.db")

# Job defaults sent to the subtitle worker.
_JOB_TYPE = "generate"
_TARGET_LANGUAGE = "en"
_WHISPER_MODEL = "large-v3"


class DispatchError(RuntimeError):
    """Raised when the entire dispatch batch cannot begin (not per-record errors)."""


@dataclass(slots=True)
class DispatchSummary:
    """Result of a single dispatch run."""

    dispatched: int   # jobs successfully POSTed and state advanced
    skipped: int      # records skipped due to dry_run
    failed: int       # records where HTTP call failed (state unchanged)
    db_path: Path


def _http_post(url: str, payload: dict) -> dict:
    """POST JSON to *url* and return the parsed response body.

    Raises:
        urllib.error.URLError: on connection failure.
        ValueError: on a non-2xx HTTP status.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    timeout = int(os.environ.get("SUBTITLE_DISPATCH_TIMEOUT", _HTTP_TIMEOUT))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        if status not in (200, 201):
            raise ValueError(f"unexpected HTTP {status} from {url}")
        return json.loads(resp.read())


def fetch_pending_dispatch(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all media records that are waiting for subtitle generation dispatch."""
    connection.row_factory = sqlite3.Row
    return connection.execute(
        """
        SELECT media_id, path
        FROM media_records
        WHERE state = ?
        ORDER BY path
        """,
        (SOURCE_STATE,),
    ).fetchall()


def build_subtitle_job(media_id: str, file_path: str) -> dict:
    """Construct the SubtitleJob JSON payload for a single media record.

    The subtitle worker names the intermediate WAV file using job.media_id, so
    media_id must be populated from the DB record (not generated fresh).
    ``item_id`` is intentionally None — media_brain has no catalog item_id.
    """
    return {
        "job_id": str(uuid.uuid4()),
        "item_id": None,
        "media_id": media_id,
        "file_path": file_path,
        "job_type": _JOB_TYPE,
        "target_language": _TARGET_LANGUAGE,
        "source_language": None,
        "output_dir": None,
        # scratch_dir=None → worker uses its own default (SUBTITLE_SCRATCH_DIR
        # env var or /mnt/container/media-work/subtitle-scratch per storage-layout.yaml)
        "scratch_dir": None,
        "whisper_model": _WHISPER_MODEL,
        "dry_run": False,
    }


def dispatch_one(
    connection: sqlite3.Connection,
    media_id: str,
    file_path: str,
    worker_url: str,
) -> None:
    """POST one job to the worker and advance its state within *connection*.

    The caller commits the connection. If the HTTP call succeeds but the
    execute raises, the record stays in SOURCE_STATE and will be retried;
    the worker may receive the same job twice — acceptable, as the worker is
    idempotent (it overwrites any existing SRT output).

    Raises:
        urllib.error.URLError: propagated from _http_post on network failure.
        ValueError: propagated from _http_post on non-2xx response.
    """
    job = build_subtitle_job(media_id, file_path)
    jobs_url = worker_url.rstrip("/") + "/jobs"

    log.info(
        "dispatching media_id=%s file=%r → %s",
        media_id, file_path, jobs_url,
    )
    _http_post(jobs_url, job)

    connection.execute(
        "UPDATE media_records SET state = ? WHERE media_id = ?",
        (QUEUED_STATE, media_id),
    )
    log.info("state → %s  media_id=%s", QUEUED_STATE, media_id)


def dispatch_pending_jobs(
    db_path: Path | str = DEFAULT_DB_PATH,
    worker_url: str = "",
    dry_run: bool = False,
) -> DispatchSummary:
    """Read all needs_subtitle_generation records and dispatch each to the worker.

    Args:
        db_path:    Path to the media_brain.db SQLite file.
        worker_url: Base URL of the subtitle-worker HTTP service.  Falls back
                    to the SUBTITLE_WORKER_URL environment variable, then to
                    http://localhost:8100.
        dry_run:    Log what would be dispatched but make no HTTP calls and
                    write no state changes.

    Returns:
        DispatchSummary with per-outcome counts.
    """
    db_path = Path(db_path)
    effective_url = (
        worker_url
        or os.environ.get("SUBTITLE_WORKER_URL", _DEFAULT_WORKER_URL)
    )
    counts: dict[str, int] = {"dispatched": 0, "skipped": 0, "failed": 0}

    with sqlite3.connect(db_path) as connection:
        rows = fetch_pending_dispatch(connection)

        if not rows:
            log.info("no records in state=%s — nothing to dispatch", SOURCE_STATE)
            return DispatchSummary(db_path=db_path, **counts)

        for row in rows:
            media_id: str = row["media_id"]
            file_path: str = row["path"]

            if dry_run:
                log.info(
                    "dry_run=True — would dispatch media_id=%s file=%r",
                    media_id, file_path,
                )
                counts["skipped"] += 1
                continue

            try:
                dispatch_one(connection, media_id, file_path, effective_url)
                counts["dispatched"] += 1
            except (urllib.error.URLError, OSError, ValueError) as exc:
                log.warning(
                    "dispatch failed media_id=%s: %s — state unchanged, will retry on next run",
                    media_id, exc,
                )
                counts["failed"] += 1

        connection.commit()

    return DispatchSummary(db_path=db_path, **counts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dispatch subtitle generation jobs for media records in "
            f"state='{SOURCE_STATE}'."
        )
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to media_brain.db (default: %(default)s).",
    )
    parser.add_argument(
        "--worker-url",
        default="",
        help=(
            "Base URL of the subtitle-worker service.  "
            "Defaults to SUBTITLE_WORKER_URL env var or http://localhost:8100."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be dispatched without making any HTTP calls.",
    )
    return parser


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    )
    args = build_arg_parser().parse_args()
    summary = dispatch_pending_jobs(
        db_path=args.db_path,
        worker_url=args.worker_url,
        dry_run=args.dry_run,
    )
    import json as _json
    print(
        _json.dumps(
            {
                "dispatched": summary.dispatched,
                "skipped": summary.skipped,
                "failed": summary.failed,
                "db_path": str(summary.db_path),
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
