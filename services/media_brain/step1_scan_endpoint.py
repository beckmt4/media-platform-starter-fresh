"""Spec-complete Step 1 scanner and HTTP endpoint for media_brain.

This module closes the remaining Step 1 gaps by:
- enriching video track inventory with HDR status
- exposing a real HTTP scan endpoint

It keeps the same SQLite schema used by the original Step 1 implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
    )


def detect_sidecar_subtitles(media_path: Path) -> list[dict[str, Any]]:
    """Find sidecar subtitle files next to a media file."""
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


def detect_video_hdr(stream: dict[str, Any]) -> tuple[bool, str | None]:
    """Infer HDR status from ffprobe video metadata."""
    transfer = str(stream.get("color_transfer") or "").lower()
    primaries = str(stream.get("color_primaries") or "").lower()
    side_data_types = {
        str(item.get("side_data_type") or "").lower()
        for item in stream.get("side_data_list", [])
    }

    if "dolby vision configuration record" in side_data_types:
        return True, "dolby_vision"
    if transfer == "arib-std-b67":
        return True, "hlg"
    if transfer == "smpte2084":
        return True, "hdr10"
    if (
        {"mastering display metadata", "content light level metadata"} & side_data_types
        or ("bt2020" in primaries and transfer in {"smpte2084", "arib-std-b67"})
    ):
        return True, "hdr"
    return False, None


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
        track = {
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
        }

        if codec_type == "video":
            hdr, hdr_format = detect_video_hdr(stream)
            track["hdr"] = hdr
            track["hdr_format"] = hdr_format
            track["pix_fmt"] = stream.get("pix_fmt")
            track["color_transfer"] = stream.get("color_transfer")
            track["color_primaries"] = stream.get("color_primaries")
            track["color_space"] = stream.get("color_space")

        tracks[codec_type].append(track)

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
            state=excluded.state,
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


def run_step1_inventory_complete(
    scan_root: Path | str = DEFAULT_SCAN_ROOT,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> InventorySummary:
    """Execute the spec-complete Step 1 scan."""
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


def handle_scan_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle a scan request payload and return a JSON-safe response."""
    scan_root = payload.get("scan_root", str(DEFAULT_SCAN_ROOT))
    db_path = payload.get("db_path", str(DEFAULT_DB_PATH))
    summary = run_step1_inventory_complete(scan_root=scan_root, db_path=db_path)
    return {
        "scanned_files": summary.scanned_files,
        "inserted_or_updated": summary.inserted_or_updated,
        "failed_files": summary.failed_files,
        "db_path": str(summary.db_path),
        "state": INITIAL_STATE,
    }


class ScanEndpointHandler(BaseHTTPRequestHandler):
    """Minimal standard-library HTTP handler for the media-brain scan endpoint."""

    server_version = "MediaBrainScanEndpoint/1.0"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/media-brain/scan":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return

        raw_body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return

        try:
            response = handle_scan_request(payload)
        except Exception as exc:  # pragma: no cover - defensive endpoint guard
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        self._send_json(HTTPStatus.OK, response)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        """Silence default request logging for cleaner local runs."""
        return


def run_scan_endpoint_server(host: str, port: int) -> None:
    """Run the Step 1 HTTP endpoint server."""
    server = ThreadingHTTPServer((host, port), ScanEndpointHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for one-shot scan or HTTP serving mode."""
    parser = argparse.ArgumentParser(
        description="Run the spec-complete media-brain Step 1 scanner or serve it as an endpoint."
    )
    parser.add_argument("--root", default=str(DEFAULT_SCAN_ROOT), help="Root path to scan recursively.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument("--serve", action="store_true", help="Serve the /media-brain/scan endpoint.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP serving mode.")
    parser.add_argument("--port", type=int, default=8787, help="Port for HTTP serving mode.")
    return parser


def main() -> int:
    """CLI entry point."""
    args = build_arg_parser().parse_args()
    if args.serve:
        run_scan_endpoint_server(args.host, args.port)
        return 0

    response = handle_scan_request({"scan_root": args.root, "db_path": args.db_path})
    print(json.dumps(response, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
