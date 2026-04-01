"""Step 1 inventory builder for media_brain.

Scans the target library for video files, probes each file with ffprobe,
inventories container and sidecar tracks, computes a stable media_id, and
writes records into a SQLite database with the initial review state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SCAN_ROOT = Path("/mnt/itv/adult")
DEFAULT_DB_PATH = Path("media_brain.db")
MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi"}
SIDECAR_EXTENSIONS = {".srt", ".ass"}
INITIAL_STATE = "needs_subtitle_review"


class FFProbeError(RuntimeError):
    """Raised when ffprobe fails."""


@dataclass(slots=True)
class InventorySummary:
    """Simple execution summary for Step 1."""

    scanned_files: int
    inserted_or_updated: int
    failed_files: int
    db_path: Path


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_media_id(path: Path, size_bytes: int) -> str:
    """Compute a stable media_id from normalized path and a size hash."""
    normalized_path = str(path.resolve()).replace("\\", "/").lower()
    size_hash = hashlib.sha256(str(size_bytes).encode("utf-8")).hexdigest()
    media_id_source = f"{normalized_path}|{size_hash}"
    return hashlib.sha256(media_id_source.encode("utf-8")).hexdigest()


def scan_media_files(root: Path) -> list[Path]:
    """Recursively scan for supported media container files."""
    if not root.exists():
        return []

    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
    ]
    return sorted(files)


def detect_sidecar_subtitles(media_path: Path) -> list[dict[str, Any]]:
    """Find sidecar subtitle files next to a media file.

    Matches both exact-stem files like ``movie.srt`` and language-tagged
    variants such as ``movie.en.srt`` or ``movie.forced.ass``.
    """
    results: list[dict[str, Any]] = []
    stem = media_path.stem

    for sibling in sorted(media_path.parent.iterdir()):
        if not sibling.is_file():
            continue
        if sibling.suffix.lower() not in SIDECAR_EXTENSIONS:
            continue

        sibling_stem = sibling.stem
        if sibling_stem != stem and not sibling.name.startswith(f"{stem}."):
            continue

        results.append(
            {
                "path": str(sibling.resolve()),
                "filename": sibling.name,
                "extension": sibling.suffix.lower(),
                "size_bytes": sibling.stat().st_size,
            }
        )

    return results


def probe_media_file(media_path: Path) -> dict[str, Any]:
    """Run ffprobe and return parsed JSON."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_path),
    ]

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=False,
        )
    except FileNotFoundError as exc:
        raise FFProbeError("ffprobe is not installed or is not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr_bytes = exc.stderr or b""
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        if not stderr:
            stderr = "ffprobe failed without stderr output"
        raise FFProbeError(f"ffprobe failed for {media_path}: {stderr}") from exc

    stdout_bytes = result.stdout or b""
    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()

    if not stdout_text:
        raise FFProbeError(f"ffprobe returned empty output for {media_path}")

    try:
        return json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise FFProbeError(f"ffprobe returned invalid JSON for {media_path}") from exc


def enumerate_tracks(ffprobe_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Split ffprobe streams into video/audio/subtitle buckets."""
    tracks: dict[str, list[dict[str, Any]]] = {
        "video": [],
        "audio": [],
        "subtitle": [],
    }

    for stream in ffprobe_data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type not in tracks:
            continue

        tags = stream.get("tags", {})
        disposition = stream.get("disposition", {})
        color_primaries = stream.get("color_primaries", "")
        color_transfer = stream.get("color_transfer", "")
        tracks[codec_type].append(
            {
                "index": stream.get("index"),
                "codec_type": codec_type,
                "codec_name": stream.get("codec_name"),
                "language": tags.get("language"),
                "title": tags.get("title"),
                "channels": stream.get("channels"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "default": bool(disposition.get("default", 0)),
                "forced": bool(disposition.get("forced", 0)),
                # HDR: bt2020 primaries with PQ (smpte2084) or HLG (arib-std-b67) transfer.
                "is_hdr": (
                    color_primaries == "bt2020"
                    or color_transfer in {"smpte2084", "arib-std-b67"}
                ),
            }
        )

    return tracks


def init_db(connection: sqlite3.Connection) -> None:
    """Create the media record table if it does not exist."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS media_records (
            media_id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            extension TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            ffprobe_json TEXT NOT NULL,
            video_tracks_json TEXT NOT NULL,
            audio_tracks_json TEXT NOT NULL,
            subtitle_tracks_json TEXT NOT NULL,
            sidecar_subtitles_json TEXT NOT NULL,
            state TEXT NOT NULL,
            scanned_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_records_state ON media_records(state)"
    )


def upsert_media_record(
    connection: sqlite3.Connection,
    media_path: Path,
    ffprobe_data: dict[str, Any],
    scanned_at: str,
) -> None:
    """Insert or update a single media record."""
    size_bytes = media_path.stat().st_size
    media_id = compute_media_id(media_path, size_bytes)
    tracks = enumerate_tracks(ffprobe_data)
    sidecars = detect_sidecar_subtitles(media_path)

    connection.execute(
        """
        INSERT INTO media_records (
            media_id,
            path,
            file_name,
            extension,
            size_bytes,
            ffprobe_json,
            video_tracks_json,
            audio_tracks_json,
            subtitle_tracks_json,
            sidecar_subtitles_json,
            state,
            scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(media_id) DO UPDATE SET
            path=excluded.path,
            file_name=excluded.file_name,
            extension=excluded.extension,
            size_bytes=excluded.size_bytes,
            ffprobe_json=excluded.ffprobe_json,
            video_tracks_json=excluded.video_tracks_json,
            audio_tracks_json=excluded.audio_tracks_json,
            subtitle_tracks_json=excluded.subtitle_tracks_json,
            sidecar_subtitles_json=excluded.sidecar_subtitles_json,
            scanned_at=excluded.scanned_at
        """,
        (
            media_id,
            str(media_path.resolve()),
            media_path.name,
            media_path.suffix.lower(),
            size_bytes,
            json.dumps(ffprobe_data, sort_keys=True),
            json.dumps(tracks["video"], sort_keys=True),
            json.dumps(tracks["audio"], sort_keys=True),
            json.dumps(tracks["subtitle"], sort_keys=True),
            json.dumps(sidecars, sort_keys=True),
            INITIAL_STATE,
            scanned_at,
        ),
    )


def run_step1_inventory(
    scan_root: Path | str = DEFAULT_SCAN_ROOT,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> InventorySummary:
    """Execute Step 1 and write records to the SQLite database."""
    scan_root = Path(scan_root)
    db_path = Path(db_path)
    media_files = scan_media_files(scan_root)
    scanned_at = utc_now_iso()
    failures = 0
    updated = 0

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        init_db(connection)

        for media_path in media_files:
            try:
                ffprobe_data = probe_media_file(media_path)
                upsert_media_record(connection, media_path, ffprobe_data, scanned_at)
                updated += 1
            except (OSError, FFProbeError):
                failures += 1

        connection.commit()

    return InventorySummary(
        scanned_files=len(media_files),
        inserted_or_updated=updated,
        failed_files=failures,
        db_path=db_path,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build a CLI parser for Step 1 execution."""
    parser = argparse.ArgumentParser(
        description="Build Step 1 of media_brain and write media records to SQLite."
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_SCAN_ROOT),
        help="Root path to scan recursively.",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path to create or update.",
    )
    return parser


def main() -> int:
    """CLI entry point."""
    args = build_arg_parser().parse_args()
    summary = run_step1_inventory(scan_root=args.root, db_path=args.db_path)
    print(
        json.dumps(
            {
                "scanned_files": summary.scanned_files,
                "inserted_or_updated": summary.inserted_or_updated,
                "failed_files": summary.failed_files,
                "db_path": str(summary.db_path),
                "state": INITIAL_STATE,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
