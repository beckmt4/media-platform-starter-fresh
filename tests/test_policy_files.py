"""Structural validation tests for config/policies/*.yaml.

These tests verify that the policy files are present, well-formed,
versioned, and internally consistent — without running any media processing.
They are safe to run in GitHub Actions.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

POLICIES_DIR = Path(__file__).resolve().parents[1] / "config" / "policies"

REQUIRED_POLICY_FILES = [
    "subtitles.yaml",
    "audio.yaml",
    "transcode.yaml",
    "arr-locks.yaml",
]

# All category keys that may appear under `domains:` in policy files.
KNOWN_DOMAIN_CATEGORIES = {
    "domestic_live_action",
    "international_live_action",
    "domestic_animation",
    "international_animation",
    "anime",
    "adult",
}


# ---------------------------------------------------------------------------
# File presence and parseability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", REQUIRED_POLICY_FILES)
def test_policy_file_exists(filename):
    assert (POLICIES_DIR / filename).exists(), f"missing policy file: {filename}"


@pytest.mark.parametrize("filename", REQUIRED_POLICY_FILES)
def test_policy_file_is_valid_yaml(filename):
    path = POLICIES_DIR / filename
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{filename} must be a YAML mapping"


@pytest.mark.parametrize("filename", REQUIRED_POLICY_FILES)
def test_policy_file_has_version(filename):
    path = POLICIES_DIR / filename
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert "version" in data, f"{filename} must have a top-level 'version' key"
    assert isinstance(data["version"], int), f"{filename}: 'version' must be an integer"


# ---------------------------------------------------------------------------
# Subtitles policy
# ---------------------------------------------------------------------------

def test_subtitles_has_universal_section(subtitles_policy):
    assert "universal" in subtitles_policy, "subtitles.yaml must have a 'universal' section"


def test_subtitles_universal_keys(subtitles_policy):
    u = subtitles_policy["universal"]
    required = {
        "keep_forced",
        "keep_english",
        "quarantine_unknown_language",
        "delete_exact_duplicates",
    }
    for key in required:
        assert key in u, f"subtitles.yaml universal section missing key: {key!r}"


def test_subtitles_universal_booleans(subtitles_policy):
    u = subtitles_policy["universal"]
    for key, value in u.items():
        assert isinstance(value, bool), (
            f"subtitles.yaml universal.{key} must be a bool, got {type(value).__name__}"
        )


def test_subtitles_domains_are_known(subtitles_policy):
    for category in subtitles_policy.get("domains", {}):
        assert category in KNOWN_DOMAIN_CATEGORIES, (
            f"subtitles.yaml unknown domain category: {category!r}"
        )


def test_subtitles_adult_has_confidence_threshold(subtitles_policy):
    adult = subtitles_policy.get("domains", {}).get("adult", {})
    assert "require_review_below_confidence" in adult, (
        "subtitles.yaml adult domain must define require_review_below_confidence"
    )
    threshold = adult["require_review_below_confidence"]
    assert 0.0 < threshold < 1.0, (
        f"subtitles.yaml adult require_review_below_confidence must be in (0, 1), got {threshold}"
    )


def test_subtitles_adult_has_generate_english(subtitles_policy):
    adult = subtitles_policy.get("domains", {}).get("adult", {})
    assert "generate_english_if_missing" in adult, (
        "subtitles.yaml adult domain must define generate_english_if_missing"
    )


def test_subtitles_anime_has_signs_songs(subtitles_policy):
    anime = subtitles_policy.get("domains", {}).get("anime", {})
    assert "keep_signs_songs_when_present" in anime, (
        "subtitles.yaml anime domain must define keep_signs_songs_when_present"
    )


# ---------------------------------------------------------------------------
# Audio policy
# ---------------------------------------------------------------------------

def test_audio_has_universal_section(audio_policy):
    assert "universal" in audio_policy, "audio.yaml must have a 'universal' section"


def test_audio_universal_keys(audio_policy):
    u = audio_policy["universal"]
    required = {
        "preserve_original_language",
        "preserve_english_if_available",
        "remove_commentary_by_default",
        "create_stereo_fallback_when_missing",
    }
    for key in required:
        assert key in u, f"audio.yaml universal section missing key: {key!r}"


def test_audio_universal_preserve_original_is_true(audio_policy):
    assert audio_policy["universal"]["preserve_original_language"] is True, (
        "audio.yaml universal.preserve_original_language must be true — non-negotiable"
    )


def test_audio_domains_are_known(audio_policy):
    for category in audio_policy.get("domains", {}):
        assert category in KNOWN_DOMAIN_CATEGORIES, (
            f"audio.yaml unknown domain category: {category!r}"
        )


# ---------------------------------------------------------------------------
# Transcode policy
# ---------------------------------------------------------------------------

def test_transcode_has_universal_section(transcode_policy):
    assert "universal" in transcode_policy, "transcode.yaml must have a 'universal' section"


def test_transcode_universal_keys(transcode_policy):
    u = transcode_policy["universal"]
    required = {
        "target_video_codec",
        "skip_if_already_hevc",
        "protect_remux",
    }
    for key in required:
        assert key in u, f"transcode.yaml universal section missing key: {key!r}"


def test_transcode_target_codec_is_hevc(transcode_policy):
    assert transcode_policy["universal"]["target_video_codec"] == "hevc", (
        "transcode.yaml universal.target_video_codec must be 'hevc'"
    )


def test_transcode_protect_remux_is_true(transcode_policy):
    assert transcode_policy["universal"]["protect_remux"] is True, (
        "transcode.yaml universal.protect_remux must be true — remux files must not be transcoded"
    )


def test_transcode_domains_are_known(transcode_policy):
    for category in transcode_policy.get("domains", {}):
        assert category in KNOWN_DOMAIN_CATEGORIES, (
            f"transcode.yaml unknown domain category: {category!r}"
        )


def test_transcode_anime_has_banding_review(transcode_policy):
    anime = transcode_policy.get("domains", {}).get("anime", {})
    assert "manual_review_for_banding_risk" in anime, (
        "transcode.yaml anime domain must define manual_review_for_banding_risk"
    )


# ---------------------------------------------------------------------------
# Arr-locks policy
# ---------------------------------------------------------------------------

def test_arr_locks_has_rules(arr_locks_policy):
    assert "rules" in arr_locks_policy, "arr-locks.yaml must have a 'rules' section"


def test_arr_locks_manually_sourced_rule(arr_locks_policy):
    rules = arr_locks_policy["rules"]
    assert "manually_sourced" in rules, "arr-locks.yaml must define the 'manually_sourced' rule"
    rule = rules["manually_sourced"]
    assert rule.get("block_upgrades") is True, (
        "arr-locks.yaml manually_sourced must set block_upgrades: true"
    )
    assert rule.get("monitored") is False, (
        "arr-locks.yaml manually_sourced must set monitored: false"
    )


def test_arr_locks_tags_are_strings(arr_locks_policy):
    for rule_name, rule in arr_locks_policy.get("rules", {}).items():
        for tag in rule.get("apply_tags", []):
            assert isinstance(tag, str), (
                f"arr-locks.yaml rules.{rule_name}.apply_tags must contain strings, got {type(tag)}"
            )


# ---------------------------------------------------------------------------
# Cross-policy consistency
# ---------------------------------------------------------------------------

def test_all_policies_same_domain_categories(subtitles_policy, audio_policy, transcode_policy):
    """All three policies should reference the same set of domain categories."""
    sub_domains = set(subtitles_policy.get("domains", {}).keys())
    audio_domains = set(audio_policy.get("domains", {}).keys())
    transcode_domains = set(transcode_policy.get("domains", {}).keys())

    # Every category in any policy must be a known category
    all_seen = sub_domains | audio_domains | transcode_domains
    unknown = all_seen - KNOWN_DOMAIN_CATEGORIES
    assert not unknown, f"unknown domain categories across policies: {unknown}"


def test_adult_subtitle_and_audio_both_define_english(subtitles_policy, audio_policy):
    sub_adult = subtitles_policy.get("domains", {}).get("adult", {})
    audio_adult = audio_policy.get("domains", {}).get("adult", {})
    assert sub_adult.get("keep_english") or subtitles_policy["universal"].get("keep_english"), (
        "adult subtitle policy must keep English subtitles (universal or domain)"
    )
    assert audio_adult.get("preserve_english_if_available") or \
           audio_policy["universal"].get("preserve_english_if_available"), (
        "adult audio policy must preserve English audio (universal or domain)"
    )
