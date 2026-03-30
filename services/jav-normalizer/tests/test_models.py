from __future__ import annotations

from jav_normalizer.models import JavTitleInfo, NormalizeRequest, ParseStatus


def test_jav_title_info_fields():
    info = JavTitleInfo(
        raw_input="SSIS-123.mkv",
        canonical_id="SSIS-123",
        studio_code="SSIS",
        title_number="123",
    )
    assert info.canonical_id == "SSIS-123"
    assert info.stripped_suffix is None


def test_jav_title_info_with_suffix():
    info = JavTitleInfo(
        raw_input="SSIS-123-C.mkv",
        canonical_id="SSIS-123",
        studio_code="SSIS",
        title_number="123",
        stripped_suffix="C",
    )
    assert info.stripped_suffix == "C"


def test_normalize_request_defaults():
    req = NormalizeRequest(raw="SSIS-123.mkv")
    assert req.return_all_candidates is False


def test_parse_status_values():
    assert ParseStatus.ok.value == "ok"
    assert ParseStatus.no_id_found.value == "no_id_found"
    assert ParseStatus.ambiguous.value == "ambiguous"
