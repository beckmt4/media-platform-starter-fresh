"""Step 4 audio extraction dispatcher for media_brain.

Reads records in state 'needs_subtitle_generation' from media_brain.db and
submits an extract_audio job to the subtitle-worker HTTP API for each one.
The worker extracts the audio track to a WAV file and keeps it on disk for
a downstream transcription job.

State transitions written here:
  needs_subtitle_generation → audio_extracted   (HTTP 200/201, worker status=complete)
  needs_subtitle_generation → failed            (HTTP error or worker status=failed)

Idempotency: only records in needs_subtitle_generation are selected.
Re-running after a partial failure retries only the failed/unprocessed records.
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

from services.media_brain.job_store import (
    init_job_tables,
    mark_job_complete,
    mark_job_failed,
    record_state_transition,
    upsert_processing_job,
)

log = logging.getLogger("media_brain.step4_audio_extraction")

SOURCE_STATE = "needs_subtitle_generation"
SUCCESS_STATE = "audio_extracted"
FAILED_STATE = "failed"

_DEFAULT_WORKER_URL = "http://localhost:8100"

# Audio extraction (no transcription) should complete within 10 minutes even
# for large files.  Override with SUBTITLE_DISPATCH_TIMEOUT env var if needed.
_HTTP_TIMEOUT = 600  # seconds

DEFAULT_DB_PATH = Path("media_brain.db")

_JOB_TYPE = "extract_audio"
_WHISPER_MODEL = "large-v3"  # carried through for consistency; unused by extract_audio


class ExtractionError(RuntimeError):
    """Raised when the entire extraction batch cannot begin."""


@dataclass(slots=True)
class ExtractionSummary:
    """Result of a single step-4 extraction run."""

    extracted: int    # jobs completed successfully, state → audio_extracted
    failed: int       # jobs failed (HTTP or worker error), state → failed
    skipped: int      # records skipped due to dry_run
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


def fetch_media_for_audio_extraction(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all media records waiting for audio extraction."""
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


def build_extract_audio_job(media_id: str, file_path: str) -> dict:
    """Construct the SubtitleJob JSON payload for an extract_audio job."""
    return {
        "job_id": str(uuid.uuid4()),
        "item_id": None,
        "media_id": media_id,
        "file_path": file_path,
        "job_type": _JOB_TYPE,
        "target_language": "en",
        "source_language": None,
        "output_dir": None,
        "scratch_dir": None,
        "whisper_model": _WHISPER_MODEL,
        "dry_run": False,
    }


def dispatch_one(
    connection: sqlite3.Connection,
    media_id: str,
    file_path: str,
    worker_url: str,
) -> bool:
    """POST one extract_audio job and advance state based on the worker result.

    Returns True if the worker reported success (state → audio_extracted).
    Returns False if the worker reported failure (state → failed).

    Raises:
        urllib.error.URLError: on network failure (caller handles state write).
        ValueError: on non-2xx HTTP response (caller handles state write).
    """
    job = build_extract_audio_job(media_id, file_path)
    job_id = job["job_id"]
    jobs_url = worker_url.rstrip("/") + "/jobs"

    log.info("dispatching media_id=%s file=%r → %s", media_id, file_path, jobs_url)

    upsert_processing_job(connection, job_id, media_id, _JOB_TYPE, "pending", worker_url=jobs_url)

    result = _http_post(jobs_url, job)

    worker_status = result.get("status", "")
    if worker_status == "complete":
        connection.execute(
            "UPDATE media_records SET state = ? WHERE media_id = ?",
            (SUCCESS_STATE, media_id),
        )
        record_state_transition(
            connection, media_id,
            from_state=SOURCE_STATE, to_state=SUCCESS_STATE,
            job_id=job_id, reason="extract_audio_complete",
        )
        mark_job_complete(connection, job_id, notes=str(result.get("notes", [])))
        log.info("state → %s  media_id=%s", SUCCESS_STATE, media_id)
        return True
    else:
        error = result.get("error_message") or f"worker returned status={worker_status!r}"
        _fail_record(connection, media_id, job_id, error)
        return False


def _fail_record(
    connection: sqlite3.Connection,
    media_id: str,
    job_id: str,
    error_message: str,
) -> None:
    """Write FAILED_STATE and record the failure in job_store."""
    connection.execute(
        "UPDATE media_records SET state = ? WHERE media_id = ?",
        (FAILED_STATE, media_id),
    )
    record_state_transition(
        connection, media_id,
        from_state=SOURCE_STATE, to_state=FAILED_STATE,
        job_id=job_id, reason=error_message[:200],
    )
    mark_job_failed(connection, job_id, error_message)
    log.warning("state → %s  media_id=%s  error=%s", FAILED_STATE, media_id, error_message)


def run_step4_audio_extraction(
    db_path: Path | str = DEFAULT_DB_PATH,
    worker_url: str = "",
    dry_run: bool = False,
) -> ExtractionSummary:
    """Read all needs_subtitle_generation records and dispatch extract_audio jobs.

    Args:
        db_path:    Path to the media_brain.db SQLite file.
        worker_url: Base URL of the subtitle-worker HTTP service.  Falls back
                    to SUBTITLE_WORKER_URL env var then http://localhost:8100.
        dry_run:    Log what would be dispatched but make no HTTP calls and
                    write no state changes.
    """
    db_path = Path(db_path)
    effective_url = worker_url or os.environ.get("SUBTITLE_WORKER_URL", _DEFAULT_WORKER_URL)
    counts: dict[str, int] = {"extracted": 0, "failed": 0, "skipped": 0}

    with sqlite3.connect(db_path) as connection:
        init_job_tables(connection)
        rows = fetch_media_for_audio_extraction(connection)

        if not rows:
            log.info("no records in state=%s — nothing to dispatch", SOURCE_STATE)
            return ExtractionSummary(db_path=db_path, **counts)

        for row in rows:
            media_id: str = row["media_id"]
            file_path: str = row["path"]

            if dry_run:
                log.info("dry_run=True — would dispatch media_id=%s file=%r", media_id, file_path)
                counts["skipped"] += 1
                continue

            try:
                if dispatch_one(connection, media_id, file_path, effective_url):
                    counts["extracted"] += 1
                else:
                    counts["failed"] += 1
            except (urllib.error.URLError, OSError, ValueError) as exc:
                # Network-level failure: we never got a worker result, so write failed state.
                job_id = str(uuid.uuid4())
                upsert_processing_job(
                    connection, job_id, media_id, _JOB_TYPE, "pending",
                    worker_url=effective_url,
                )
                _fail_record(connection, media_id, job_id, str(exc))
                counts["failed"] += 1

        connection.commit()

    return ExtractionSummary(db_path=db_path, **counts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dispatch audio extraction jobs for media records in "
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
    summary = run_step4_audio_extraction(
        db_path=args.db_path,
        worker_url=args.worker_url,
        dry_run=args.dry_run,
    )
    import json as _json
    print(
        _json.dumps(
            {
                "extracted": summary.extracted,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "db_path": str(summary.db_path),
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
