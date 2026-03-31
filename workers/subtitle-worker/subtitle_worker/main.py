from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from pydantic import BaseModel

from .models import SubtitleJob, SubtitleJobResult
from .worker import SubtitleWorker, status

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("subtitle_worker")

app = FastAPI(title="subtitle-worker", version="0.1.0")
_worker = SubtitleWorker()


class HealthResponse(BaseModel):
    status: str
    tools: dict[str, bool]


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    info = status()
    return HealthResponse(status=info["status"], tools=info["tools"])


@app.post("/jobs", response_model=SubtitleJobResult, tags=["jobs"])
def run_job(job: SubtitleJob) -> SubtitleJobResult:
    log.info(
        "job received job_id=%s type=%s item_id=%s dry_run=%s",
        job.job_id, job.job_type, job.item_id, job.dry_run,
    )
    result = _worker.run(job)
    log.info(
        "job done job_id=%s status=%s duration=%.3fs",
        result.job_id, result.status, result.duration_seconds,
    )
    return result
