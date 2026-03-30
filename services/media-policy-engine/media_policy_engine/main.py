from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .evaluator import PolicyEvaluator
from .models import MediaFacts, PolicyEvaluationResult
from .policy_loader import load_policies

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("media_policy_engine")

app = FastAPI(title="media-policy-engine", version="0.1.0")


def _policies_dir() -> Path:
    """Resolve the policy directory from env or repo-relative default."""
    env = os.environ.get("POLICY_DIR")
    if env:
        return Path(env)
    # Default: repo root / config / policies
    return Path(__file__).resolve().parents[3] / "config" / "policies"


@lru_cache(maxsize=1)
def _evaluator() -> PolicyEvaluator:
    policies_dir = _policies_dir()
    log.info("loading policies from %s", policies_dir)
    policies = load_policies(policies_dir)
    return PolicyEvaluator(policies)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

@app.post("/evaluate", response_model=PolicyEvaluationResult, tags=["policy"])
def evaluate(facts: MediaFacts) -> PolicyEvaluationResult:
    try:
        evaluator = _evaluator()
    except Exception as exc:
        log.error("failed to load policies: %s", exc)
        raise HTTPException(status_code=500, detail=f"policy load error: {exc}") from exc

    result = evaluator.evaluate(facts)
    log.info(
        "evaluated domain=%s actions=%d requires_review=%s path=%r",
        result.domain,
        len(result.actions),
        result.requires_review,
        result.file_path,
    )
    return result
