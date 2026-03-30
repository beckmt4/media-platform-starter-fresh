from __future__ import annotations

from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"
    skipped = "skipped"       # dry_run, already target codec, or policy skip
    tool_unavailable = "tool_unavailable"


class TranscodeJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    item_id: str                          # catalog-api MediaItem.id
    file_path: str                        # source media file
    output_path: str                      # destination file (must be different from source)
    target_codec: str = "hevc"            # from transcode policy
    container: str = "mkv"
    allow_nvenc: bool = False             # use NVIDIA hardware encoder if available
    # Copy all streams except video; do not re-encode audio/subtitles
    copy_streams: bool = True
    dry_run: bool = False                 # validate inputs, skip actual execution


class TranscodeJobResult(BaseModel):
    job_id: str
    item_id: str
    status: JobStatus
    output_path: str | None = None
    codec_used: str | None = None         # actual encoder used (e.g. "hevc_nvenc")
    size_bytes_before: int | None = None
    size_bytes_after: int | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    notes: list[str] = Field(default_factory=list)
