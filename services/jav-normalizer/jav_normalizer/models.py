from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ParseStatus(StrEnum):
    ok = "ok"
    no_id_found = "no_id_found"
    ambiguous = "ambiguous"  # multiple candidate IDs found in the same string


class JavTitleInfo(BaseModel):
    """Structured representation of a parsed JAV title ID."""

    raw_input: str
    canonical_id: str  # e.g. "SSIS-123" — uppercase studio code, hyphenated
    studio_code: str   # e.g. "SSIS"
    title_number: str  # e.g. "123" — preserved as string to retain leading zeros
    # Suffix flags stripped during parsing (e.g. "C" for censored, "UC" uncensored)
    stripped_suffix: str | None = None


class NormalizeRequest(BaseModel):
    # Raw filename, title string, or path. Only the basename is used.
    raw: str
    # When True, return all candidate matches instead of just the best one.
    return_all_candidates: bool = False


class NormalizeResult(BaseModel):
    raw_input: str
    status: ParseStatus
    title: JavTitleInfo | None = None
    # Populated when status=ambiguous or return_all_candidates=True
    candidates: list[JavTitleInfo] = Field(default_factory=list)
    parse_notes: list[str] = Field(default_factory=list)
