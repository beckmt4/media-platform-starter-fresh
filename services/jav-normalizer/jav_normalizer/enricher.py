from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from .models import EnrichRequest, EnrichResult, EnrichStatus, JavMetadata

log = logging.getLogger("jav_normalizer.enricher")

_DEFAULT_TIMEOUT = 10  # seconds


def _parse_metadata(canonical_id: str, data: dict, source_url: str) -> JavMetadata:
    """Map a generic metadata API response dict into JavMetadata.

    Accepts a flexible shape — unrecognised keys are silently ignored.
    Expected keys (all optional):
        title, studio, release_date, cast (list[str]), genres (list[str]), cover_url
    """
    return JavMetadata(
        canonical_id=canonical_id,
        title=data.get("title") or None,
        studio=data.get("studio") or None,
        release_date=data.get("release_date") or None,
        cast=[str(a) for a in data.get("cast", []) if a],
        genres=[str(g) for g in data.get("genres", []) if g],
        cover_url=data.get("cover_url") or None,
        source=source_url,
    )


class JavEnricher:
    """Fetches JAV metadata from a self-hosted local metadata service.

    Configure via the ``JAV_METADATA_URL`` environment variable.  The
    enricher calls::

        GET {JAV_METADATA_URL}/movie/{canonical_id}

    and expects a JSON response body.  The caller is responsible for running
    a compatible local metadata API (e.g. javinfo-api or a custom service).

    If ``JAV_METADATA_URL`` is not set the enricher returns
    ``EnrichStatus.unavailable`` without making any network call.

    Behaviour matrix:
    - URL not set              → unavailable
    - HTTP 404                 → not_found
    - HTTP 200, valid JSON     → ok
    - HTTP 200, invalid JSON   → error
    - HTTP 4xx/5xx (non-404)   → error
    - Network/timeout error    → error
    """

    def __init__(self, metadata_url: str | None = None) -> None:
        # Allow injection for tests; fall back to env var at call time
        self._metadata_url = metadata_url

    def _base_url(self) -> str | None:
        url = self._metadata_url or os.environ.get("JAV_METADATA_URL", "").strip()
        return url.rstrip("/") if url else None

    def enrich(self, request: EnrichRequest) -> EnrichResult:
        canonical_id = request.canonical_id.strip().upper()

        base = self._base_url()
        if not base:
            log.debug("JAV_METADATA_URL not set — enrichment unavailable")
            return EnrichResult(
                canonical_id=canonical_id,
                status=EnrichStatus.unavailable,
                notes=["JAV_METADATA_URL is not configured"],
            )

        encoded_id = urllib.parse.quote(canonical_id, safe="")
        url = f"{base}/movie/{encoded_id}"
        log.info("enrich fetch canonical_id=%s url=%s", canonical_id, url)

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                log.info("enrich not_found canonical_id=%s", canonical_id)
                return EnrichResult(
                    canonical_id=canonical_id,
                    status=EnrichStatus.not_found,
                    notes=[f"metadata service returned 404 for {canonical_id!r}"],
                )
            log.warning("enrich http_error canonical_id=%s code=%s", canonical_id, exc.code)
            return EnrichResult(
                canonical_id=canonical_id,
                status=EnrichStatus.error,
                notes=[f"metadata service returned HTTP {exc.code}"],
            )
        except OSError as exc:
            # Covers URLError (connection refused, DNS failure) and TimeoutError
            log.warning("enrich network_error canonical_id=%s error=%s", canonical_id, exc)
            return EnrichResult(
                canonical_id=canonical_id,
                status=EnrichStatus.error,
                notes=[f"network error contacting metadata service: {exc}"],
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("enrich invalid_json canonical_id=%s error=%s", canonical_id, exc)
            return EnrichResult(
                canonical_id=canonical_id,
                status=EnrichStatus.error,
                notes=["metadata service returned invalid JSON"],
            )

        metadata = _parse_metadata(canonical_id, data, url)
        log.info(
            "enrich ok canonical_id=%s title=%r studio=%r cast_count=%d",
            canonical_id, metadata.title, metadata.studio, len(metadata.cast),
        )
        return EnrichResult(
            canonical_id=canonical_id,
            status=EnrichStatus.ok,
            metadata=metadata,
        )
