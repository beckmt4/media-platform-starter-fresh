from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def mediainfo_anime() -> dict:
    return _load("mediainfo_anime.json")


@pytest.fixture(scope="session")
def mediainfo_domestic() -> dict:
    return _load("mediainfo_domestic.json")


@pytest.fixture(scope="session")
def mediainfo_no_lang_tag() -> dict:
    return _load("mediainfo_no_lang_tag.json")


@pytest.fixture(scope="session")
def mediainfo_no_subtitles() -> dict:
    return _load("mediainfo_no_subtitles.json")
