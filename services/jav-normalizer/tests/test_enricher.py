from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from jav_normalizer.enricher import JavEnricher
from jav_normalizer.models import EnrichRequest, EnrichStatus


def _enrich(canonical_id: str, url: str | None = None) -> object:
    enricher = JavEnricher(metadata_url=url)
    return enricher.enrich(EnrichRequest(canonical_id=canonical_id))


def _mock_response(body: dict, status: int = 200):
    raw = json.dumps(body).encode()
    resp = MagicMock()
    resp.read.return_value = raw
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# URL not configured
# ---------------------------------------------------------------------------

def test_unavailable_when_url_not_set(monkeypatch):
    monkeypatch.delenv("JAV_METADATA_URL", raising=False)
    result = _enrich("SSIS-123")
    assert result.status == EnrichStatus.unavailable
    assert result.metadata is None
    assert result.notes


def test_unavailable_when_url_empty_string(monkeypatch):
    monkeypatch.setenv("JAV_METADATA_URL", "   ")
    result = _enrich("SSIS-123")
    assert result.status == EnrichStatus.unavailable


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_ok_returns_metadata():
    payload = {
        "title": "Super Title",
        "studio": "SOD",
        "release_date": "2023-06-15",
        "cast": ["Actress A", "Actress B"],
        "genres": ["Drama", "Romance"],
        "cover_url": "http://local/covers/ssis-123.jpg",
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = _enrich("SSIS-123", url="http://local-meta:8080")

    assert result.status == EnrichStatus.ok
    assert result.metadata is not None
    assert result.metadata.title == "Super Title"
    assert result.metadata.studio == "SOD"
    assert result.metadata.release_date == "2023-06-15"
    assert result.metadata.cast == ["Actress A", "Actress B"]
    assert result.metadata.genres == ["Drama", "Romance"]
    assert result.metadata.cover_url == "http://local/covers/ssis-123.jpg"


def test_ok_canonical_id_uppercased():
    payload = {"title": "Some Title"}
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        result = _enrich("ssis-123", url="http://local-meta:8080")
    assert result.canonical_id == "SSIS-123"


def test_ok_partial_metadata_fields_none():
    # Service returns only title; all other fields should default gracefully
    with patch("urllib.request.urlopen", return_value=_mock_response({"title": "Only Title"})):
        result = _enrich("IPX-456", url="http://local-meta:8080")
    assert result.status == EnrichStatus.ok
    assert result.metadata.title == "Only Title"
    assert result.metadata.studio is None
    assert result.metadata.cast == []
    assert result.metadata.genres == []


def test_ok_empty_metadata_response():
    with patch("urllib.request.urlopen", return_value=_mock_response({})):
        result = _enrich("BF-123", url="http://local-meta:8080")
    assert result.status == EnrichStatus.ok
    assert result.metadata.title is None


def test_ok_source_url_populated():
    with patch("urllib.request.urlopen", return_value=_mock_response({"title": "T"})):
        result = _enrich("SSIS-123", url="http://local-meta:8080")
    assert result.metadata.source is not None
    assert "SSIS-123" in result.metadata.source


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

def test_not_found_on_404():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(url="", code=404, msg="Not Found", hdrs=None, fp=None),
    ):
        result = _enrich("SSIS-999", url="http://local-meta:8080")
    assert result.status == EnrichStatus.not_found
    assert result.metadata is None
    assert result.notes


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_error_on_500():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(url="", code=500, msg="Server Error", hdrs=None, fp=None),
    ):
        result = _enrich("SSIS-123", url="http://local-meta:8080")
    assert result.status == EnrichStatus.error
    assert "500" in result.notes[0]


def test_error_on_connection_refused():
    with patch(
        "urllib.request.urlopen",
        side_effect=OSError("Connection refused"),
    ):
        result = _enrich("SSIS-123", url="http://local-meta:8080")
    assert result.status == EnrichStatus.error
    assert result.notes


def test_error_on_timeout():
    with patch(
        "urllib.request.urlopen",
        side_effect=TimeoutError("timed out"),
    ):
        result = _enrich("SSIS-123", url="http://local-meta:8080")
    assert result.status == EnrichStatus.error


def test_error_on_invalid_json():
    resp = MagicMock()
    resp.read.return_value = b"not json {"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp):
        result = _enrich("SSIS-123", url="http://local-meta:8080")
    assert result.status == EnrichStatus.error
    assert "invalid JSON" in result.notes[0]


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def test_request_url_includes_canonical_id():
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req.full_url)
        return _mock_response({"title": "T"})

    with patch("urllib.request.urlopen", fake_urlopen):
        _enrich("PRED-456", url="http://local-meta:8080")

    assert captured
    assert "PRED-456" in captured[0]
    assert captured[0].startswith("http://local-meta:8080/movie/")


def test_trailing_slash_stripped_from_base_url():
    captured = []

    def fake_urlopen(req, timeout=None):
        captured.append(req.full_url)
        return _mock_response({})

    with patch("urllib.request.urlopen", fake_urlopen):
        _enrich("SSIS-123", url="http://local-meta:8080/")

    assert "//" not in captured[0].replace("http://", "")
