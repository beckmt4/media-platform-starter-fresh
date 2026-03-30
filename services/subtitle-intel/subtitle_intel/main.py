from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from pydantic import BaseModel

from .models import ScanRequest, ScanResult
from .scanner import SubtitleScanner

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("subtitle_intel")

app = FastAPI(title="subtitle-intel", version="0.1.0")
_scanner = SubtitleScanner()


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/scan", response_model=ScanResult, tags=["scan"])
def scan(request: ScanRequest) -> ScanResult:
    result = _scanner.scan(
        file_path=request.file_path,
        mediainfo_json=request.mediainfo_json,
    )
    log.info(
        "scan status=%s tracks=%d path=%r requires_review=%s",
        result.status,
        len(result.subtitle_tracks),
        result.file_path,
        result.requires_review,
    )
    return result
