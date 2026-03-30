from __future__ import annotations

import logging
import re
from pathlib import Path

from .models import JavTitleInfo, NormalizeRequest, NormalizeResult, ParseStatus

log = logging.getLogger("jav_normalizer.normalizer")

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Studio code: 1-6 uppercase letters, optionally starting with a digit
# (e.g. "3DSVR", "T28", "E-BODY handled separately)
# Title number: 3-5 digits
# Optional separator between code and number: hyphen, space, or nothing
# Optional suffix after the number: single letter flags like "C", "UC", "R"
#   that are NOT part of resolution/quality tags

_CORE = re.compile(
    r"""
    (?<![A-Z0-9])               # not preceded by alphanum (word boundary)
    ([A-Z]{1,6})                # studio code: 1-6 letters
    [-\s_]?                     # optional separator: hyphen, space, or underscore
    (\d{3,5})                   # title number: 3-5 digits
    (-?(?:UC|C|R))?             # optional suffix flag (UC=uncensored, C=censored, R=remaster)
    (?![A-Z0-9])                # not followed by alphanum
    """,
    re.VERBOSE,
)

# Known resolution/quality noise tokens to strip before matching
_NOISE_TOKENS = re.compile(
    r"\b(?:1080p|720p|480p|4k|2160p|bluray|blu-ray|web-?dl|webrip|x264|x265|"
    r"hevc|avc|aac|flac|hdr|sdr|remux|proper|repack|extended|theatrical)\b",
    re.IGNORECASE,
)

# Known junk bracket contents to strip (release group tags, etc.)
_BRACKET_NOISE = re.compile(r"\[(?!\s*[A-Z]{1,6}[-\s]?\d{3,5})[^\]]*\]", re.IGNORECASE)


def _clean(raw: str) -> str:
    """Strip noise tokens and bracket junk, return uppercase string."""
    s = Path(raw).stem  # drop extension and directory
    s = _BRACKET_NOISE.sub(" ", s)
    s = _NOISE_TOKENS.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.upper()


def _build_title_info(raw_input: str, code: str, number: str, suffix: str | None) -> JavTitleInfo:
    stripped = suffix.lstrip("-").upper() if suffix else None
    canonical = f"{code}-{number}"
    return JavTitleInfo(
        raw_input=raw_input,
        canonical_id=canonical,
        studio_code=code,
        title_number=number,
        stripped_suffix=stripped if stripped else None,
    )


class JavNormalizer:
    """Parses and normalises JAV title IDs from filenames or title strings.

    Stub — pure string processing, no network calls, no file system access.
    Enrichment (metadata lookup from external databases) is out of scope
    for this stub and will be added as a separate enricher component.
    """

    def normalize(self, request: NormalizeRequest) -> NormalizeResult:
        raw = request.raw
        cleaned = _clean(raw)
        notes: list[str] = []

        matches = list(_CORE.finditer(cleaned))

        if not matches:
            log.debug("no JAV ID found in %r (cleaned: %r)", raw, cleaned)
            return NormalizeResult(
                raw_input=raw,
                status=ParseStatus.no_id_found,
                parse_notes=[f"no JAV ID pattern found in {cleaned!r}"],
            )

        candidates = [
            _build_title_info(raw, m.group(1), m.group(2), m.group(3))
            for m in matches
        ]

        if request.return_all_candidates:
            notes.append(f"{len(candidates)} candidate(s) found")
            return NormalizeResult(
                raw_input=raw,
                status=ParseStatus.ok if len(candidates) == 1 else ParseStatus.ambiguous,
                title=candidates[0],
                candidates=candidates,
                parse_notes=notes,
            )

        if len(candidates) == 1:
            return NormalizeResult(
                raw_input=raw,
                status=ParseStatus.ok,
                title=candidates[0],
                parse_notes=notes,
            )

        # Multiple matches — pick the best candidate using a simple heuristic:
        # prefer the match closest to the start of the cleaned string, and
        # prefer matches with a hyphen separator (more likely to be the real ID).
        notes.append(f"{len(candidates)} candidates found — using best match heuristic")
        log.debug("ambiguous: %d candidates for %r: %s", len(candidates), raw, candidates)

        hyphenated = [c for c in candidates if "-" in c.canonical_id]
        best = (hyphenated or candidates)[0]

        return NormalizeResult(
            raw_input=raw,
            status=ParseStatus.ambiguous,
            title=best,
            candidates=candidates,
            parse_notes=notes,
        )
