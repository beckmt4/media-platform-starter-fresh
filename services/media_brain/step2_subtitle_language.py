"""Step 2 subtitle language detection for media_brain.

Reads subtitle tracks discovered during Step 1, trusts valid existing language tags,
extracts text from suspicious or unknown tracks, runs local language detection,
and stores one per-track review row in SQLite.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("media_brain.db")
DEFAULT_TEMP_ROOT = Path("temp/media_brain_step2")
LANGUAGE_CONFIDENCE_THRESHOLD = 0.90
TARGET_MEDIA_STATE = "needs_subtitle_review"

IMAGE_BASED_SUBTITLE_CODECS = {
    "hdmv_pgs_subtitle",
    "dvd_subtitle",
    "dvb_subtitle",
    "xsub",
}

SUSPICIOUS_LANGUAGE_TAGS = {
    "",
    "und",
    "unk",
    "unknown",
    "mis",
    "mul",
    "zxx",
    "n/a",
    "na",
    "none",
    "null",
}

LANGUAGE_TAG_NORMALIZATION = {
    "eng": "en",
    "en": "en",
    "jpn": "ja",
    "ja": "ja",
    "spa": "es",
    "es": "es",
    "fra": "fr",
    "fre": "fr",
    "fr": "fr",
    "deu": "de",
    "ger": "de",
    "de": "de",
    "ita": "it",
    "it": "it",
    "por": "pt",
    "pt": "pt",
    "rus": "ru",
    "ru": "ru",
    "zho": "zh",
    "chi": "zh",
    "zh": "zh",
    "kor": "ko",
    "ko": "ko",
    "ara": "ar",
    "ar": "ar",
    "hin": "hi",
    "hi": "hi",
    "nld": "nl",
    "dut": "nl",
    "nl": "nl",
    "swe": "sv",
    "sv": "sv",
    "nor": "no",
    "no": "no",
    "dan": "da",
    "da": "da",
    "fin": "fi",
    "fi": "fi",
    "pol": "pl",
    "pl": "pl",
    "tur": "tr",
    "tr": "tr",
    "ukr": "uk",
    "uk": "uk",
    "ces": "cs",
    "cze": "cs",
    "cs": "cs",
    "ron": "ro",
    "rum": "ro",
    "ro": "ro",
    "ell": "el",
    "gre": "el",
    "el": "el",
    "heb": "he",
    "he": "he",
    "tha": "th",
    "th": "th",
    "vie": "vi",
    "vi": "vi",
    "ind": "id",
    "id": "id",
    "msa": "ms",
    "may": "ms",
    "ms": "ms",
}

SIDECAR_EXTENSION_TO_CODEC = {
    ".srt": "subrip",
    ".ass": "ass",
}


class SubtitleLanguageDetectionError(RuntimeError):
    """Raised when Step 2 cannot complete a required subtitle task."""


@dataclass(slots=True)
class Step2Summary:
    """Execution summary for Step 2."""

    processed_tracks: int
    trusted_existing: int
    detected: int
    uncertain: int
    needs_ocr: int
    failed_tracks: int
    db_path: Path


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_language_tag(tag: str | None) -> str | None:
    """Normalize common ISO language tag variants."""
    if tag is None:
        return None

    cleaned = tag.strip().lower()
    if cleaned in SUSPICIOUS_LANGUAGE_TAGS:
        return None

    return LANGUAGE_TAG_NORMALIZATION.get(cleaned, cleaned if re.fullmatch(r"[a-z]{2}", cleaned) else None)


def is_trusted_language_tag(tag: str | None) -> bool:
    """Return True when the tag is present and not suspicious."""
    return normalize_language_tag(tag) is not None


def is_image_based_subtitle(codec_name: str | None) -> bool:
    """Return True when the subtitle codec requires OCR instead of text detection."""
    return (codec_name or "").lower() in IMAGE_BASED_SUBTITLE_CODECS


def build_track_key(
    media_id: str,
    track_source: str,
    stream_index: int | None = None,
    sidecar_path: str | None = None,
) -> str:
    """Build a stable unique key for a subtitle track."""
    if track_source == "embedded":
        return f"{media_id}:embedded:{stream_index}"
    return f"{media_id}:sidecar:{sidecar_path}"


def infer_sidecar_language_tag(sidecar_path: Path, media_path: Path) -> str | None:
    """Infer a language token from a sidecar filename like movie.en.srt."""
    media_stem = media_path.stem.lower()
    sidecar_name = sidecar_path.name.lower()

    if not sidecar_name.startswith(f"{media_stem}."):
        return None

    remainder = sidecar_name[len(media_stem) + 1 :]
    parts = remainder.split(".")
    if not parts:
        return None

    candidate = parts[0]
    return candidate if is_trusted_language_tag(candidate) else None


def init_step2_db(connection: sqlite3.Connection) -> None:
    """Create the Step 2 results table if needed."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS subtitle_track_language_labels (
            track_key TEXT PRIMARY KEY,
            media_id TEXT NOT NULL,
            media_path TEXT NOT NULL,
            track_source TEXT NOT NULL,
            stream_index INTEGER,
            sidecar_path TEXT,
            codec_name TEXT,
            existing_language_tag TEXT,
            normalized_language_tag TEXT,
            sample_text TEXT,
            sample_char_count INTEGER NOT NULL,
            detected_language TEXT,
            detected_confidence REAL,
            detector_engine TEXT,
            review_status TEXT NOT NULL,
            ocr_state TEXT,
            scanned_at TEXT NOT NULL,
            FOREIGN KEY(media_id) REFERENCES media_records(media_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_subtitle_track_language_labels_media_id
        ON subtitle_track_language_labels(media_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_subtitle_track_language_labels_review_status
        ON subtitle_track_language_labels(review_status)
        """
    )


def fetch_candidate_media_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Fetch Step 1 media rows that are queued for subtitle review."""
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT media_id, path, file_name, subtitle_tracks_json, sidecar_subtitles_json, state
        FROM media_records
        WHERE state = ?
        ORDER BY path
        """,
        (TARGET_MEDIA_STATE,),
    ).fetchall()
    return rows


def decode_bytes_with_fallbacks(raw_bytes: bytes) -> str:
    """Decode subtitle bytes using a small set of common encodings."""
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def extract_embedded_subtitle_text(
    media_path: Path,
    stream_index: int,
    temp_root: Path,
) -> str:
    """Extract one embedded subtitle track to temporary text using ffmpeg."""
    temp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".srt",
        dir=temp_root,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(media_path),
        "-map",
        f"0:{stream_index}",
        str(temp_path),
    ]

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=False)
        _ = result
        raw_bytes = temp_path.read_bytes()
        return decode_bytes_with_fallbacks(raw_bytes)
    except FileNotFoundError as exc:
        raise SubtitleLanguageDetectionError("ffmpeg is not installed or is not on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = decode_bytes_with_fallbacks(exc.stderr or b"").strip()
        raise SubtitleLanguageDetectionError(
            f"ffmpeg subtitle extraction failed for {media_path}: {stderr or 'unknown error'}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def read_sidecar_subtitle_text(sidecar_path: Path) -> str:
    """Read a sidecar subtitle file with relaxed decoding."""
    return decode_bytes_with_fallbacks(sidecar_path.read_bytes())


def clean_subtitle_text(raw_text: str, codec_name: str | None = None) -> str:
    """Reduce subtitle markup to plain language-bearing text for detection."""
    codec = (codec_name or "").lower()
    lines: list[str] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if codec in {"ass", "ssa"}:
            if line.startswith("[") or line.startswith("Format:") or line.startswith("Style:"):
                continue
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                line = parts[-1] if len(parts) == 10 else line

        if re.fullmatch(r"\d+", line):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}", line):
            continue

        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"\{\\.*?\}", " ", line)
        line = re.sub(r"\[[^\]]+\]", " ", line) if codec in {"ass", "ssa"} else line
        line = re.sub(r"\\[Nn]", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)

    cleaned = " ".join(lines)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:2000]


def detect_language_from_text(sample_text: str) -> tuple[str | None, float, str]:
    """Detect language and confidence from subtitle text using local Python libraries."""
    if not sample_text.strip():
        return None, 0.0, "no_text"

    try:
        from langdetect import DetectorFactory, detect_langs
    except ImportError as exc:
        raise SubtitleLanguageDetectionError(
            "langdetect is not installed. Run 'pip install langdetect'."
        ) from exc

    DetectorFactory.seed = 0
    ranked = detect_langs(sample_text)
    if not ranked:
        return None, 0.0, "langdetect"

    best = ranked[0]
    normalized = normalize_language_tag(best.lang)
    confidence = float(best.prob)
    return normalized, confidence, "langdetect"


def upsert_track_label(
    connection: sqlite3.Connection,
    *,
    track_key: str,
    media_id: str,
    media_path: str,
    track_source: str,
    stream_index: int | None,
    sidecar_path: str | None,
    codec_name: str | None,
    existing_language_tag: str | None,
    normalized_language_tag: str | None,
    sample_text: str | None,
    detected_language: str | None,
    detected_confidence: float | None,
    detector_engine: str | None,
    review_status: str,
    ocr_state: str | None,
    scanned_at: str,
) -> None:
    """Insert or update one Step 2 track label record."""
    connection.execute(
        """
        INSERT INTO subtitle_track_language_labels (
            track_key,
            media_id,
            media_path,
            track_source,
            stream_index,
            sidecar_path,
            codec_name,
            existing_language_tag,
            normalized_language_tag,
            sample_text,
            sample_char_count,
            detected_language,
            detected_confidence,
            detector_engine,
            review_status,
            ocr_state,
            scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(track_key) DO UPDATE SET
            media_id=excluded.media_id,
            media_path=excluded.media_path,
            track_source=excluded.track_source,
            stream_index=excluded.stream_index,
            sidecar_path=excluded.sidecar_path,
            codec_name=excluded.codec_name,
            existing_language_tag=excluded.existing_language_tag,
            normalized_language_tag=excluded.normalized_language_tag,
            sample_text=excluded.sample_text,
            sample_char_count=excluded.sample_char_count,
            detected_language=excluded.detected_language,
            detected_confidence=excluded.detected_confidence,
            detector_engine=excluded.detector_engine,
            review_status=excluded.review_status,
            ocr_state=excluded.ocr_state,
            scanned_at=excluded.scanned_at
        """,
        (
            track_key,
            media_id,
            media_path,
            track_source,
            stream_index,
            sidecar_path,
            codec_name,
            existing_language_tag,
            normalized_language_tag,
            sample_text,
            len(sample_text or ""),
            detected_language,
            detected_confidence,
            detector_engine,
            review_status,
            ocr_state,
            scanned_at,
        ),
    )


def process_embedded_track(
    connection: sqlite3.Connection,
    *,
    media_id: str,
    media_path: Path,
    track: dict[str, Any],
    temp_root: Path,
    scanned_at: str,
) -> str:
    """Process one embedded subtitle track and persist the result."""
    stream_index = track.get("index")
    codec_name = track.get("codec_name")
    existing_tag = track.get("language")
    normalized_tag = normalize_language_tag(existing_tag)
    track_key = build_track_key(media_id, "embedded", stream_index=stream_index)

    if is_trusted_language_tag(existing_tag):
        upsert_track_label(
            connection,
            track_key=track_key,
            media_id=media_id,
            media_path=str(media_path),
            track_source="embedded",
            stream_index=stream_index,
            sidecar_path=None,
            codec_name=codec_name,
            existing_language_tag=existing_tag,
            normalized_language_tag=normalized_tag,
            sample_text=None,
            detected_language=normalized_tag,
            detected_confidence=1.0,
            detector_engine="existing_tag",
            review_status="trusted_existing",
            ocr_state=None,
            scanned_at=scanned_at,
        )
        return "trusted_existing"

    if is_image_based_subtitle(codec_name):
        upsert_track_label(
            connection,
            track_key=track_key,
            media_id=media_id,
            media_path=str(media_path),
            track_source="embedded",
            stream_index=stream_index,
            sidecar_path=None,
            codec_name=codec_name,
            existing_language_tag=existing_tag,
            normalized_language_tag=normalized_tag,
            sample_text=None,
            detected_language=None,
            detected_confidence=None,
            detector_engine=None,
            review_status="needs_ocr",
            ocr_state="future",
            scanned_at=scanned_at,
        )
        return "needs_ocr"

    raw_text = extract_embedded_subtitle_text(media_path, int(stream_index), temp_root)
    sample_text = clean_subtitle_text(raw_text, codec_name=codec_name)
    detected_language, confidence, engine = detect_language_from_text(sample_text)
    review_status = "detected" if confidence > LANGUAGE_CONFIDENCE_THRESHOLD and detected_language else "uncertain"

    upsert_track_label(
        connection,
        track_key=track_key,
        media_id=media_id,
        media_path=str(media_path),
        track_source="embedded",
        stream_index=int(stream_index),
        sidecar_path=None,
        codec_name=codec_name,
        existing_language_tag=existing_tag,
        normalized_language_tag=normalized_tag,
        sample_text=sample_text,
        detected_language=detected_language,
        detected_confidence=confidence,
        detector_engine=engine,
        review_status=review_status,
        ocr_state=None,
        scanned_at=scanned_at,
    )
    return review_status


def process_sidecar_track(
    connection: sqlite3.Connection,
    *,
    media_id: str,
    media_path: Path,
    sidecar: dict[str, Any],
    scanned_at: str,
) -> str:
    """Process one sidecar subtitle file and persist the result."""
    sidecar_path = Path(sidecar["path"])
    codec_name = SIDECAR_EXTENSION_TO_CODEC.get(sidecar_path.suffix.lower(), sidecar_path.suffix.lower())
    existing_tag = infer_sidecar_language_tag(sidecar_path, media_path)
    normalized_tag = normalize_language_tag(existing_tag)
    track_key = build_track_key(media_id, "sidecar", sidecar_path=str(sidecar_path))

    if is_trusted_language_tag(existing_tag):
        upsert_track_label(
            connection,
            track_key=track_key,
            media_id=media_id,
            media_path=str(media_path),
            track_source="sidecar",
            stream_index=None,
            sidecar_path=str(sidecar_path),
            codec_name=codec_name,
            existing_language_tag=existing_tag,
            normalized_language_tag=normalized_tag,
            sample_text=None,
            detected_language=normalized_tag,
            detected_confidence=1.0,
            detector_engine="existing_tag",
            review_status="trusted_existing",
            ocr_state=None,
            scanned_at=scanned_at,
        )
        return "trusted_existing"

    raw_text = read_sidecar_subtitle_text(sidecar_path)
    sample_text = clean_subtitle_text(raw_text, codec_name=codec_name)
    detected_language, confidence, engine = detect_language_from_text(sample_text)
    review_status = "detected" if confidence > LANGUAGE_CONFIDENCE_THRESHOLD and detected_language else "uncertain"

    upsert_track_label(
        connection,
        track_key=track_key,
        media_id=media_id,
        media_path=str(media_path),
        track_source="sidecar",
        stream_index=None,
        sidecar_path=str(sidecar_path),
        codec_name=codec_name,
        existing_language_tag=existing_tag,
        normalized_language_tag=normalized_tag,
        sample_text=sample_text,
        detected_language=detected_language,
        detected_confidence=confidence,
        detector_engine=engine,
        review_status=review_status,
        ocr_state=None,
        scanned_at=scanned_at,
    )
    return review_status


def run_step2_subtitle_language_detection(
    db_path: Path | str = DEFAULT_DB_PATH,
    temp_root: Path | str = DEFAULT_TEMP_ROOT,
) -> Step2Summary:
    """Execute Step 2 and persist per-track subtitle language labels."""
    db_path = Path(db_path)
    temp_root = Path(temp_root)
    scanned_at = utc_now_iso()

    counts = {
        "processed_tracks": 0,
        "trusted_existing": 0,
        "detected": 0,
        "uncertain": 0,
        "needs_ocr": 0,
        "failed_tracks": 0,
    }

    with sqlite3.connect(db_path) as connection:
        init_step2_db(connection)
        rows = fetch_candidate_media_rows(connection)

        for row in rows:
            media_id = row["media_id"]
            media_path = Path(row["path"])
            subtitle_tracks = json.loads(row["subtitle_tracks_json"] or "[]")
            sidecar_tracks = json.loads(row["sidecar_subtitles_json"] or "[]")

            for track in subtitle_tracks:
                counts["processed_tracks"] += 1
                try:
                    status = process_embedded_track(
                        connection,
                        media_id=media_id,
                        media_path=media_path,
                        track=track,
                        temp_root=temp_root,
                        scanned_at=scanned_at,
                    )
                    counts[status] += 1
                except (OSError, ValueError, SubtitleLanguageDetectionError):
                    counts["failed_tracks"] += 1

            for sidecar in sidecar_tracks:
                counts["processed_tracks"] += 1
                try:
                    status = process_sidecar_track(
                        connection,
                        media_id=media_id,
                        media_path=media_path,
                        sidecar=sidecar,
                        scanned_at=scanned_at,
                    )
                    counts[status] += 1
                except (OSError, ValueError, SubtitleLanguageDetectionError):
                    counts["failed_tracks"] += 1

        connection.commit()

    return Step2Summary(db_path=db_path, **counts)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the Step 2 CLI parser."""
    parser = argparse.ArgumentParser(
        description="Run Step 2 subtitle language detection for media_brain."
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database created by Step 1.",
    )
    parser.add_argument(
        "--temp-root",
        default=str(DEFAULT_TEMP_ROOT),
        help="Temporary working directory for extracted subtitle text.",
    )
    return parser


def main() -> int:
    """CLI entry point."""
    args = build_arg_parser().parse_args()
    summary = run_step2_subtitle_language_detection(
        db_path=args.db_path,
        temp_root=args.temp_root,
    )
    print(
        json.dumps(
            {
                "processed_tracks": summary.processed_tracks,
                "trusted_existing": summary.trusted_existing,
                "detected": summary.detected,
                "uncertain": summary.uncertain,
                "needs_ocr": summary.needs_ocr,
                "failed_tracks": summary.failed_tracks,
                "db_path": str(summary.db_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
