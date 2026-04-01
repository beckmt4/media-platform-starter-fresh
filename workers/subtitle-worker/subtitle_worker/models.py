from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"
    skipped = "skipped"       # dry_run or policy skip
    tool_unavailable = "tool_unavailable"


class SubtitleJobType(StrEnum):
    generate = "generate"     # run faster-whisper on audio track
    repair = "repair"         # fix malformed/mis-timed existing subtitle
    translate = "translate"   # translate existing subtitle to target language


class SubtitleJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    # catalog-api MediaItem.id — optional so media_brain can dispatch without
    # a catalog entry.  When absent, catalog notification is skipped.
    item_id: str | None = None
    media_id: str | None = None           # media-brain media_id; used to name WAV on scratch
    file_path: str                        # source media file
    job_type: SubtitleJobType
    target_language: str = "en"           # ISO 639-1
    source_language: str | None = None    # None = auto-detect
    output_dir: str | None = None         # defaults alongside source file
    # Scratch directory for intermediate WAV files.
    # Defaults to the path in config/storage-layout.yaml (subtitle_scratch_root).
    scratch_dir: str | None = None
    # faster-whisper model size: tiny / base / small / medium / large-v3
    whisper_model: str = "large-v3"
    dry_run: bool = False                 # validate inputs, skip actual execution


class SubtitleJobResult(BaseModel):
    job_id: str
    item_id: str | None = None            # mirrors SubtitleJob.item_id
    status: JobStatus
    job_type: SubtitleJobType
    output_path: str | None = None        # generated/repaired subtitle file
    detected_language: str | None = None
    confidence: float | None = None       # 0.0–1.0
    duration_seconds: float | None = None
    error_message: str | None = None
    notes: list[str] = Field(default_factory=list)
