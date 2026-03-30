from __future__ import annotations

from pathlib import Path

import pytest

from media_policy_engine.evaluator import PolicyEvaluator
from media_policy_engine.policy_loader import load_policies

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICIES_DIR = REPO_ROOT / "config" / "policies"


@pytest.fixture(scope="session")
def evaluator() -> PolicyEvaluator:
    policies = load_policies(POLICIES_DIR)
    return PolicyEvaluator(policies)
