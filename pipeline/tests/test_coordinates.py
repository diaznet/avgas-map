"""Tests for the OpenAIP coordinate join (no network; injected getter)."""

from __future__ import annotations

from avgasmap import coordinates
from avgasmap.coordinates import Coordinate, build_index, export_url, fetch_country_index, join


def _openaip_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"icaoCode": "LFAV", "name": "Valenciennes Denain", "country": "FR"},
                "geometry": {"type": "Point", "coordinates": [3.46, 50.33]},
            },
            {
                "type": "Feature",
                "properties": {"icaoCode": "LFOH", "name": "Le Havre", "country": "FR"},
                "geometry": {"type": "Point", "coordinates": [0.088, 49.53]},
            },
            {   # malformed: no coordinates -> skipped
                "type": "Feature",
                "properties": {"icaoCode": "LFXX", "name": "Broken"},
                "geometry": {"type": "Point", "coordinates": None},
            },
            {   # no icao -> skipped
                "type": "Feature",
                "properties": {"name": "Anonymous"},
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
            },
        ],
    }


def test_export_url_lowercases_country():
    assert export_url("FR") == "https://storage.openaip.net/openaip-system-exports/fr_apt.geojson"


def test_export_url_respects_config_override():
    url = export_url("FR", base="https://example/", key_template="{country}.json")
    assert url == "https://example/fr.json"


def test_build_index_extracts_valid_features_only():
    idx = build_index(_openaip_geojson())
    assert set(idx) == {"LFAV", "LFOH"}
    assert idx["LFAV"] == Coordinate(lon=3.46, lat=50.33, name="Valenciennes Denain")


def test_fetch_uses_injected_getter():
    captured = {}

    def getter(url):
        captured["url"] = url
        return _openaip_geojson()

    idx = fetch_country_index("fr", getter)
    assert captured["url"].endswith("fr_apt.geojson")
    assert "LFAV" in idx


def test_join_matches_by_exact_icao():
    idx = build_index(_openaip_geojson())
    records = {"LFAV": {"icao": "LFAV"}, "LFOH": {"icao": "LFOH"}}
    res = join(records, idx)
    assert set(res.joined) == {"LFAV", "LFOH"}
    assert res.unmatched == []
    _, coord = res.joined["LFAV"]
    assert coord.lat == 50.33


def test_join_drops_and_reports_unmatched():
    idx = build_index(_openaip_geojson())
    records = {"LFAV": {"icao": "LFAV"}, "LFZZ": {"icao": "LFZZ"}}  # LFZZ absent
    res = join(records, idx)
    assert "LFAV" in res.joined
    assert "LFZZ" not in res.joined
    assert res.unmatched == ["LFZZ"]


def test_join_is_case_insensitive_on_icao():
    idx = build_index(_openaip_geojson())
    res = join({"lfav": {"icao": "lfav"}}, idx)
    assert "lfav" in res.joined
