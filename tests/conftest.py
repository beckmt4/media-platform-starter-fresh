from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = REPO_ROOT / "config" / "policies"
CONFIG_DIR = REPO_ROOT / "config"


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def policies_dir() -> Path:
    return POLICIES_DIR


@pytest.fixture(scope="session")
def subtitles_policy() -> dict:
    return load_yaml(POLICIES_DIR / "subtitles.yaml")


@pytest.fixture(scope="session")
def audio_policy() -> dict:
    return load_yaml(POLICIES_DIR / "audio.yaml")


@pytest.fixture(scope="session")
def transcode_policy() -> dict:
    return load_yaml(POLICIES_DIR / "transcode.yaml")


@pytest.fixture(scope="session")
def arr_locks_policy() -> dict:
    return load_yaml(POLICIES_DIR / "arr-locks.yaml")


@pytest.fixture(scope="session")
def media_domains() -> dict:
    return load_yaml(CONFIG_DIR / "media-domains.yaml")


@pytest.fixture(scope="session")
def storage_layout() -> dict:
    return load_yaml(CONFIG_DIR / "storage-layout.yaml")
