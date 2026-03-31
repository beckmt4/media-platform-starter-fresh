from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from pydantic import BaseModel

from .enricher import JavEnricher
from .models import (
    EnrichRequest,
    EnrichResult,
    NormalizeAndEnrichRequest,
    NormalizeAndEnrichResult,
    NormalizeRequest,
    NormalizeResult,
)
from .normalizer import JavNormalizer

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("jav_normalizer")

app = FastAPI(title="jav-normalizer", version="0.1.0")
_normalizer = JavNormalizer()
_enricher = JavEnricher()


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


@app.post("/enrich", response_model=EnrichResult, tags=["enrich"])
def enrich(request: EnrichRequest) -> EnrichResult:
    result = _enricher.enrich(request)
    log.info(
        "enrich status=%s canonical_id=%r",
        result.status,
        result.canonical_id,
    )
    return result


@app.post("/normalize-and-enrich", response_model=NormalizeAndEnrichResult, tags=["normalize"])
def normalize_and_enrich(request: NormalizeAndEnrichRequest) -> NormalizeAndEnrichResult:
    norm_result = _normalizer.normalize(
        NormalizeRequest(raw=request.raw, return_all_candidates=request.return_all_candidates)
    )
    log.info(
        "normalize status=%s canonical_id=%r raw=%r",
        norm_result.status,
        norm_result.title.canonical_id if norm_result.title else None,
        norm_result.raw_input,
    )

    enrich_result = None
    if norm_result.title is not None:
        enrich_result = _enricher.enrich(EnrichRequest(canonical_id=norm_result.title.canonical_id))
        log.info(
            "enrich status=%s canonical_id=%r",
            enrich_result.status,
            enrich_result.canonical_id,
        )

    return NormalizeAndEnrichResult(normalize=norm_result, enrich=enrich_result)
