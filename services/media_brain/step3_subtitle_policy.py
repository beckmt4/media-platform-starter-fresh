"""Step 3 subtitle policy decision for media_brain.

Reads the track inventory from Step 1 and the language labels from Step 2,
applies the subtitle policy decision tree, writes a per-file policy decision
to SQLite, and advances the media record state.

Decision tree
─────────────
  IF a trusted or detected English subtitle exists (detected_language="en",
  review_status in ("trusted_existing", "detected")):
      → policy_decision = "has_english_subtitle"
      → media_records.state = "needs_audio_review"

  IF no qualifying English subtitle exists:
      → policy_decision = "needs_subtitle_generation"
      → media_records.state = "needs_subtitle_generation"
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("media_brain.db")
SOURCE_STATE = "needs_subtitle_review"
ENGLISH_REVIEW_STATUSES = {"trusted_existing", "detected"}


class Step3PolicyError(RuntimeError):
    """Raised when Step 3 cannot complete a required operation."""


@dataclass(slots=True)
class Step3Summary:
    """Execution summary for Step 3."""

    processed_files: int
    has_english_subtitle: int
    needs_subtitle_generation: int
    failed_files: int
    db_path: Path


@dataclass(slots=True)
class PolicyDecision:
    """Result of evaluating subtitle policy for one media file."""

    media_id: str
    policy_decision: str          # "has_english_subtitle" | "needs_subtitle_generation"
    next_state: str               # value written to media_records.state
    english_track_key: str | None # set when decision is "has_english_subtitle"
    has_any_subtitle: bool        # True if any embedded or sidecar subtitle exists
    subtitle_track_count: int     # embedded subtitle tracks from Step 1
    sidecar_count: int            # sidecar files from Step 1
    notes: str


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# DB initialisation
# ---------------------------------------------------------------------------

def init_step3_db(connection: sqlite3.Connection) -> None:
    """Create the Step 3 results table and indexes if they do not exist."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS step3_policy_decisions (
            media_id           TEXT PRIMARY KEY,
            policy_decision    TEXT NOT NULL,
            next_state         TEXT NOT NULL,
            english_track_key  TEXT,
            has_any_subtitle   INTEGER NOT NULL,
            subtitle_track_count INTEGER NOT NULL,
            sidecar_count      INTEGER NOT NULL,
            decided_at         TEXT NOT NULL,
            notes              TEXT,
            FOREIGN KEY(media_id) REFERENCES media_records(media_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_step3_policy_decisions_decision
        ON step3_policy_decisions(policy_decision)
        """
    )


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_media_for_policy(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all media records whose state is still needs_subtitle_review."""
    connection.row_factory = sqlite3.Row
    return connection.execute(
        """
        SELECT media_id, path, subtitle_tracks_json, sidecar_subtitles_json
        FROM media_records
        WHERE state = ?
        ORDER BY path
        """,
        (SOURCE_STATE,),
    ).fetchall()


def fetch_track_labels(connection: sqlite3.Connection, media_id: str) -> list[sqlite3.Row]:
    """Return all Step 2 language labels for a single media file."""
    connection.row_factory = sqlite3.Row
    return connection.execute(
        """
        SELECT track_key, track_source, detected_language, review_status
        FROM subtitle_track_language_labels
        WHERE media_id = ?
        ORDER BY track_key
        """,
        (media_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Decision logic (pure — no DB access)
# ---------------------------------------------------------------------------

def evaluate_subtitle_policy(
    media_id: str,
    track_labels: list[Any],
    subtitle_tracks: list[dict[str, Any]],
    sidecar_subtitles: list[dict[str, Any]],
) -> PolicyDecision:
    """Apply the subtitle policy decision tree and return a PolicyDecision.

    Parameters
    ----------
    media_id:
        The SHA-256 media identifier.
    track_labels:
        Rows from ``subtitle_track_language_labels`` (sqlite3.Row or dict).
    subtitle_tracks:
        Embedded subtitle tracks from ``media_records.subtitle_tracks_json``.
    sidecar_subtitles:
        Sidecar entries from ``media_records.sidecar_subtitles_json``.
    """
    subtitle_track_count = len(subtitle_tracks)
    sidecar_count = len(sidecar_subtitles)
    has_any_subtitle = subtitle_track_count > 0 or sidecar_count > 0

    for label in track_labels:
        lang = label["detected_language"]
        status = label["review_status"]
        if lang == "en" and status in ENGLISH_REVIEW_STATUSES:
            return PolicyDecision(
                media_id=media_id,
                policy_decision="has_english_subtitle",
                next_state="needs_audio_review",
                english_track_key=label["track_key"],
                has_any_subtitle=True,
                subtitle_track_count=subtitle_track_count,
                sidecar_count=sidecar_count,
                notes=f"English subtitle found via {label['track_key']} (status={status})",
            )

    # No English subtitle found — build context note for downstream use.
    if has_any_subtitle:
        notes = (
            f"No English subtitle; {subtitle_track_count} embedded track(s), "
            f"{sidecar_count} sidecar(s) present. Queued for Whisper generation."
        )
    else:
        notes = "No subtitles of any kind. Queued for Whisper generation from scratch."

    return PolicyDecision(
        media_id=media_id,
        policy_decision="needs_subtitle_generation",
        next_state="needs_subtitle_generation",
        english_track_key=None,
        has_any_subtitle=has_any_subtitle,
        subtitle_track_count=subtitle_track_count,
        sidecar_count=sidecar_count,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def upsert_policy_decision(
    connection: sqlite3.Connection,
    decision: PolicyDecision,
    decided_at: str,
) -> None:
    """Persist the policy decision and advance the media record state."""
    connection.execute(
        """
        INSERT INTO step3_policy_decisions (
            media_id,
            policy_decision,
            next_state,
            english_track_key,
            has_any_subtitle,
            subtitle_track_count,
            sidecar_count,
            decided_at,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(media_id) DO UPDATE SET
            policy_decision      = excluded.policy_decision,
            next_state           = excluded.next_state,
            english_track_key    = excluded.english_track_key,
            has_any_subtitle     = excluded.has_any_subtitle,
            subtitle_track_count = excluded.subtitle_track_count,
            sidecar_count        = excluded.sidecar_count,
            decided_at           = excluded.decided_at,
            notes                = excluded.notes
        """,
        (
            decision.media_id,
            decision.policy_decision,
            decision.next_state,
            decision.english_track_key,
            int(decision.has_any_subtitle),
            decision.subtitle_track_count,
            decision.sidecar_count,
            decided_at,
            decision.notes,
        ),
    )
    connection.execute(
        "UPDATE media_records SET state = ? WHERE media_id = ?",
        (decision.next_state, decision.media_id),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_step3_subtitle_policy(
    db_path: Path | str = DEFAULT_DB_PATH,
    dispatch_after: bool = False,
    worker_url: str = "",
) -> Step3Summary:
    """Execute Step 3 and write policy decisions to the database.

    Args:
        db_path:        Path to media_brain.db.
        dispatch_after: When True, immediately dispatch all records that land
                        in needs_subtitle_generation to the subtitle worker.
                        Requires step4_dispatch.py to be present.
        worker_url:     Worker base URL used when dispatch_after=True.  Falls
                        back to SUBTITLE_WORKER_URL env var then localhost:8100.
    """
    db_path = Path(db_path)
    decided_at = utc_now_iso()

    counts: dict[str, int] = {
        "processed_files": 0,
        "has_english_subtitle": 0,
        "needs_subtitle_generation": 0,
        "failed_files": 0,
    }

    with sqlite3.connect(db_path) as connection:
        init_step3_db(connection)
        media_rows = fetch_media_for_policy(connection)

        for row in media_rows:
            media_id = row["media_id"]
            counts["processed_files"] += 1
            try:
                track_labels = fetch_track_labels(connection, media_id)
                subtitle_tracks = json.loads(row["subtitle_tracks_json"] or "[]")
                sidecar_subtitles = json.loads(row["sidecar_subtitles_json"] or "[]")

                decision = evaluate_subtitle_policy(
                    media_id=media_id,
                    track_labels=track_labels,
                    subtitle_tracks=subtitle_tracks,
                    sidecar_subtitles=sidecar_subtitles,
                )
                upsert_policy_decision(connection, decision, decided_at)
                counts[decision.policy_decision] += 1
            except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
                counts["failed_files"] += 1

        connection.commit()

    if dispatch_after:
        # Local import: step4_dispatch is an optional next step.  Importing at
        # call time keeps step3 usable in environments where step4 is not yet
        # deployed, and avoids a circular import at module load.
        try:
            from services.media_brain import step4_dispatch as _step4
        except ImportError as exc:
            raise Step3PolicyError(
                "dispatch_after=True requires step4_dispatch.py in "
                "services/media_brain/ but import failed: %s" % exc
            ) from exc
        _effective_url = worker_url or os.environ.get(
            "SUBTITLE_WORKER_URL", "http://localhost:8100"
        )
        _step4.dispatch_pending_jobs(db_path=db_path, worker_url=_effective_url)

    return Step3Summary(db_path=db_path, **counts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Step 3 subtitle policy decisions for media_brain."
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database created by Steps 1 and 2.",
    )
    parser.add_argument(
        "--dispatch-after",
        action="store_true",
        help=(
            "Immediately dispatch needs_subtitle_generation records to the "
            "subtitle worker after Step 3 completes."
        ),
    )
    parser.add_argument(
        "--worker-url",
        default="",
        help=(
            "Subtitle worker base URL (used with --dispatch-after).  "
            "Defaults to SUBTITLE_WORKER_URL env var or http://localhost:8100."
        ),
    )
    return parser


def main() -> int:
    """CLI entry point."""
    args = build_arg_parser().parse_args()
    summary = run_step3_subtitle_policy(
        db_path=args.db_path,
        dispatch_after=args.dispatch_after,
        worker_url=args.worker_url,
    )
    import json as _json
    print(
        _json.dumps(
            {
                "processed_files": summary.processed_files,
                "has_english_subtitle": summary.has_english_subtitle,
                "needs_subtitle_generation": summary.needs_subtitle_generation,
                "failed_files": summary.failed_files,
                "db_path": str(summary.db_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
