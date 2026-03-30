"""Structural validation tests for config/media-domains.yaml and config/storage-layout.yaml."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

KNOWN_DOMAIN_TYPES = {"movie", "series", "scene_or_movie"}
KNOWN_DOMAIN_CATEGORIES = {
    "domestic_live_action",
    "international_live_action",
    "domestic_animation",
    "international_animation",
    "anime",
    "adult",
}

# The 11 domain keys defined in media-domains.yaml
EXPECTED_DOMAINS = {
    "domestic_live_action_movie",
    "domestic_live_action_tv",
    "international_live_action_movie",
    "international_live_action_tv",
    "domestic_animated_movie",
    "domestic_animated_tv",
    "international_animated_movie",
    "international_animated_tv",
    "anime_movie",
    "anime_series",
    "jav_adult",
}

REQUIRED_RUNTIME_PATHS = {
    "intake_root",
    "review_root",
    "quarantine_root",
    "reports_root",
    "manifests_root",
    "subtitle_scratch_root",
    "workflow_state_root",
}


# ---------------------------------------------------------------------------
# media-domains.yaml
# ---------------------------------------------------------------------------

def test_media_domains_file_exists(repo_root):
    assert (repo_root / "config" / "media-domains.yaml").exists()


def test_media_domains_has_version(media_domains):
    assert "version" in media_domains
    assert isinstance(media_domains["version"], int)


def test_media_domains_has_domains_section(media_domains):
    assert "domains" in media_domains
    assert isinstance(media_domains["domains"], dict)


def test_media_domains_expected_keys(media_domains):
    actual = set(media_domains["domains"].keys())
    assert actual == EXPECTED_DOMAINS, (
        f"media-domains.yaml domain keys mismatch.\n"
        f"  missing: {EXPECTED_DOMAINS - actual}\n"
        f"  extra:   {actual - EXPECTED_DOMAINS}"
    )


def test_media_domains_each_has_type_and_category(media_domains):
    for name, domain in media_domains["domains"].items():
        assert "type" in domain, f"domain {name!r} missing 'type'"
        assert "category" in domain, f"domain {name!r} missing 'category'"
        assert domain["type"] in KNOWN_DOMAIN_TYPES, (
            f"domain {name!r} has unknown type {domain['type']!r}"
        )
        assert domain["category"] in KNOWN_DOMAIN_CATEGORIES, (
            f"domain {name!r} has unknown category {domain['category']!r}"
        )


def test_media_domains_jav_adult_category(media_domains):
    assert media_domains["domains"]["jav_adult"]["category"] == "adult"


# ---------------------------------------------------------------------------
# storage-layout.yaml
# ---------------------------------------------------------------------------

def test_storage_layout_file_exists(repo_root):
    assert (repo_root / "config" / "storage-layout.yaml").exists()


def test_storage_layout_has_version(storage_layout):
    assert "version" in storage_layout
    assert isinstance(storage_layout["version"], int)


def test_storage_layout_has_authoritative_paths(storage_layout):
    assert "authoritative_paths" in storage_layout


def test_storage_layout_has_runtime_section(storage_layout):
    assert "runtime" in storage_layout["authoritative_paths"], (
        "storage-layout.yaml must have an authoritative_paths.runtime section"
    )


def test_storage_layout_runtime_required_keys(storage_layout):
    runtime = storage_layout["authoritative_paths"]["runtime"]
    for key in REQUIRED_RUNTIME_PATHS:
        assert key in runtime, (
            f"storage-layout.yaml authoritative_paths.runtime missing key: {key!r}"
        )


def test_storage_layout_runtime_paths_are_strings(storage_layout):
    runtime = storage_layout["authoritative_paths"]["runtime"]
    for key, value in runtime.items():
        assert isinstance(value, str), (
            f"storage-layout.yaml runtime.{key} must be a string path"
        )


def test_storage_layout_runtime_paths_are_absolute(storage_layout):
    runtime = storage_layout["authoritative_paths"]["runtime"]
    for key, value in runtime.items():
        assert value.startswith("/"), (
            f"storage-layout.yaml runtime.{key}={value!r} must be an absolute path"
        )


def test_storage_layout_has_bulk_media_section(storage_layout):
    assert "bulk_media" in storage_layout["authoritative_paths"], (
        "storage-layout.yaml must have an authoritative_paths.bulk_media section"
    )


def test_storage_layout_bulk_media_paths_are_absolute(storage_layout):
    bulk = storage_layout["authoritative_paths"]["bulk_media"]
    for key, value in bulk.items():
        assert isinstance(value, str) and value.startswith("/"), (
            f"storage-layout.yaml bulk_media.{key}={value!r} must be an absolute path"
        )


def test_storage_layout_no_path_duplicates(storage_layout):
    paths = storage_layout["authoritative_paths"]
    all_paths = []
    for section in paths.values():
        if isinstance(section, dict):
            all_paths.extend(section.values())
    duplicates = {p for p in all_paths if all_paths.count(p) > 1}
    assert not duplicates, f"storage-layout.yaml has duplicate paths: {duplicates}"
