"""Tests for Release publishing + manifest generation (mock GitHub client)."""

from __future__ import annotations

import json

import pytest

from avgasmap import schema
from avgasmap.publish import (
    ASSET_NAME,
    PublishResult,
    Release,
    build_manifest,
    cycle_from_tag,
    publish_cycle,
    tag_for_cycle,
)
from tests.helpers import valid_dataset


class MockGitHub:
    """In-memory GitHub Releases: tag -> asset bytes."""

    def __init__(self, existing: dict[str, bytes] | None = None, fail_upload: bool = False):
        self._assets: dict[str, bytes] = dict(existing or {})
        self._fail_upload = fail_upload
        self.uploads: list[str] = []

    def list_releases(self) -> list[Release]:
        return [
            Release(tag=tag, asset_url=f"https://dl/{tag}/{ASSET_NAME}")
            for tag in self._assets
        ]

    def upsert_release_asset(self, tag: str, asset_name: str, data: bytes) -> Release:
        if self._fail_upload:
            raise RuntimeError("upload failed")
        self._assets[tag] = data
        self.uploads.append(tag)
        return Release(tag=tag, asset_url=f"https://dl/{tag}/{asset_name}")


def test_tag_roundtrip():
    assert tag_for_cycle("2609") == "airac-2609"
    assert cycle_from_tag("airac-2609") == "2609"
    assert cycle_from_tag("v1.0") is None


def test_build_manifest_marks_newest_effective_as_latest():
    releases = [
        Release("airac-2601", "https://dl/airac-2601/dataset.geojson"),
        Release("airac-2609", "https://dl/airac-2609/dataset.geojson"),
        Release("airac-2605", "https://dl/airac-2605/dataset.geojson"),
    ]
    manifest = build_manifest(releases)
    assert manifest["latest"] == "2609"
    # Newest-first ordering.
    assert [c["cycle"] for c in manifest["cycles"]] == ["2609", "2605", "2601"]
    # Each cycle echoes schema_version + effective_date.
    for c in manifest["cycles"]:
        assert c["schema_version"] == schema.SCHEMA_VERSION
        assert c["effective_date"]


def test_build_manifest_ignores_non_airac_or_assetless():
    releases = [
        Release("v1.0", "https://dl/v1.0/other"),          # not an airac tag
        Release("airac-2609", ""),                          # no asset url
        Release("airac-2605", "https://dl/airac-2605/dataset.geojson"),
    ]
    manifest = build_manifest(releases)
    assert [c["cycle"] for c in manifest["cycles"]] == ["2605"]
    assert manifest["latest"] == "2605"


def test_build_manifest_empty():
    assert build_manifest([]) == {"latest": None, "cycles": []}


def test_publish_uploads_asset_and_returns_manifest():
    gh = MockGitHub(existing={"airac-2605": b"old"})
    ds = valid_dataset()
    res = publish_cycle("2609", ds, gh)
    assert isinstance(res, PublishResult)
    assert res.published_tag == "airac-2609"
    assert "airac-2609" in gh.uploads
    # Uploaded bytes are the serialized dataset.
    assert json.loads(gh._assets["airac-2609"].decode())["type"] == "FeatureCollection"
    # Manifest now includes both cycles, latest = 2609.
    assert res.manifest["latest"] == "2609"
    assert {c["cycle"] for c in res.manifest["cycles"]} == {"2605", "2609"}


def test_publish_replaces_same_cycle_asset():
    gh = MockGitHub(existing={"airac-2609": b"old"})
    res = publish_cycle("2609", valid_dataset(), gh)
    assert res.manifest["latest"] == "2609"
    assert json.loads(gh._assets["airac-2609"].decode())["type"] == "FeatureCollection"


class LaggyGitHub(MockGitHub):
    """Simulates GitHub read-after-write lag: list_releases() returns the
    just-uploaded release WITHOUT its asset url yet (empty), while the upsert
    itself returns the real url. Reproduces the empty-manifest bug."""

    def list_releases(self) -> list[Release]:
        # Every release comes back asset-less (as if the asset isn't visible yet).
        return [Release(tag=tag, asset_url="") for tag in self._assets]


def test_publish_survives_read_after_write_lag():
    # The just-published cycle must appear in the manifest even when a
    # freshly-listed release still shows no asset (GitHub consistency lag).
    gh = LaggyGitHub()
    res = publish_cycle("2608", valid_dataset(), gh)
    assert res.manifest["latest"] == "2608"
    assert [c["cycle"] for c in res.manifest["cycles"]] == ["2608"]


def test_publish_failure_propagates_and_leaves_prior_state():
    gh = MockGitHub(existing={"airac-2605": b"good"}, fail_upload=True)
    with pytest.raises(RuntimeError):
        publish_cycle("2609", valid_dataset(), gh)
    # Prior state untouched: no 2609, 2605 still present.
    assert "airac-2609" not in gh._assets
    assert gh._assets["airac-2605"] == b"good"
