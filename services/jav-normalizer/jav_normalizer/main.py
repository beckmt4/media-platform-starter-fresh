from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from pydantic import BaseModel

from .models import NormalizeRequest, NormalizeResult
from .normalizer import JavNormalizer

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("jav_normalizer")

app = FastAPI(title="jav-normalizer", version="0.1.0")
_normalizer = JavNormalizer()


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/normalize", response_model=NormalizeResult, tags=["normalize"])
def normalize(request: NormalizeRequest) -> NormalizeResult:
    result = _normalizer.normalize(request)
    log.info(
        "normalize status=%s canonical_id=%r raw=%r",
        result.status,
        result.title.canonical_id if result.title else None,
        result.raw_input,
    )
    return result
