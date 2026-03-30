from __future__ import annotations

import pytest

from jav_normalizer.models import NormalizeRequest, ParseStatus
from jav_normalizer.normalizer import JavNormalizer, _clean

norm = JavNormalizer()


def normalize(raw: str, **kwargs) -> object:
    return norm.normalize(NormalizeRequest(raw=raw, **kwargs))


# ---------------------------------------------------------------------------
# _clean helper
# ---------------------------------------------------------------------------

def test_clean_drops_extension():
    assert "MKV" not in _clean("SSIS-123.mkv")


def test_clean_strips_resolution_tag():
    result = _clean("SSIS-123.1080p.mkv")
    assert "1080P" not in result
    assert "SSIS" in result


def test_clean_uppercases():
    assert _clean("ssis-123.mkv") == "SSIS-123"


def test_clean_strips_bracket_noise():
    # Bracket with release group — not an ID
    cleaned = _clean("[SubsGroup] SSIS-123.mkv")
    assert "SUBSGROUP" not in cleaned
    assert "SSIS" in cleaned


# ---------------------------------------------------------------------------
# Standard hyphenated IDs
# ---------------------------------------------------------------------------

def test_standard_hyphenated_id():
    r = normalize("SSIS-123.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "SSIS-123"
    assert r.title.studio_code == "SSIS"
    assert r.title.title_number == "123"


def test_four_digit_number():
    r = normalize("IPX-4567.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "IPX-4567"


def test_five_digit_number():
    r = normalize("FC2-PPV-12345.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.title_number == "12345"


def test_short_studio_code():
    r = normalize("BF-123.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.studio_code == "BF"


def test_six_letter_studio_code():
    r = normalize("MAXVR-123.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.studio_code == "MAXVR"


# ---------------------------------------------------------------------------
# No hyphen / space separator
# ---------------------------------------------------------------------------

def test_no_hyphen_separator():
    r = normalize("SSIS123.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "SSIS-123"


def test_space_separator():
    r = normalize("SSIS 123.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "SSIS-123"


# ---------------------------------------------------------------------------
# Suffix flags
# ---------------------------------------------------------------------------

def test_censored_suffix_stripped():
    r = normalize("PRED-456-C.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "PRED-456"
    assert r.title.stripped_suffix == "C"


def test_uncensored_suffix_stripped():
    r = normalize("PRED-456-UC.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "PRED-456"
    assert r.title.stripped_suffix == "UC"


# ---------------------------------------------------------------------------
# Messy filenames
# ---------------------------------------------------------------------------

def test_bracketed_id():
    r = normalize("[SSIS-123] Some Title Here.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "SSIS-123"


def test_id_with_resolution_noise():
    r = normalize("ABW-001.1080p.BluRay.x265.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "ABW-001"


def test_id_with_underscore_separators():
    r = normalize("SSIS_123_some_title.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "SSIS-123"


def test_full_path_uses_basename():
    r = normalize("/mnt/itv/adult/SSIS-123/SSIS-123.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.canonical_id == "SSIS-123"


def test_lowercase_input_normalised():
    r = normalize("ssis-123.mkv")
    assert r.status == ParseStatus.ok
    assert r.title.studio_code == "SSIS"


# ---------------------------------------------------------------------------
# No match cases
# ---------------------------------------------------------------------------

def test_no_id_plain_title():
    r = normalize("Some Movie Without An ID.mkv")
    assert r.status == ParseStatus.no_id_found
    assert r.title is None


def test_no_id_empty_string():
    r = normalize("")
    assert r.status == ParseStatus.no_id_found


def test_no_id_numbers_only():
    r = normalize("123456.mkv")
    assert r.status == ParseStatus.no_id_found


def test_no_id_too_short_number():
    # Two-digit number — below threshold
    r = normalize("AB-12.mkv")
    assert r.status == ParseStatus.no_id_found


# ---------------------------------------------------------------------------
# Ambiguous / return_all_candidates
# ---------------------------------------------------------------------------

def test_return_all_candidates_single():
    r = normalize("SSIS-123.mkv", return_all_candidates=True)
    assert r.status == ParseStatus.ok
    assert len(r.candidates) == 1
    assert r.candidates[0].canonical_id == "SSIS-123"


def test_return_all_candidates_multiple():
    # Two distinct IDs in the string
    r = normalize("SSIS-123 and IPX-456.mkv", return_all_candidates=True)
    assert r.status == ParseStatus.ambiguous
    ids = {c.canonical_id for c in r.candidates}
    assert "SSIS-123" in ids
    assert "IPX-456" in ids


def test_ambiguous_returns_best_title():
    r = normalize("SSIS-123 and IPX-456.mkv")
    assert r.status == ParseStatus.ambiguous
    # Best match is the first candidate (leftmost)
    assert r.title is not None
    assert r.title.canonical_id == "SSIS-123"
