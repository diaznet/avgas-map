"""Tests for dataset assembly."""

from __future__ import annotations

from avgasmap import schema
from avgasmap.assemble import assemble
from avgasmap.coordinates import Coordinate


def _rec(icao, state="available", grades=None, name=None):
    grades = grades if grades is not None else (["100LL"] if state == "available" else [])
    return {
        "icao": icao,
        "name": name,
        "fuel_state": state,
        "avgas_grades": grades,
        "jet_a1": False,
        "conditions": {
            "on_request": False, "ppr": False, "self_service": False,
            "reserved_for_based": False, "mil_civ_split": False,
            "has_hours": False, "payment": [], "brand": None, "phone": None,
        },
        "source_text": "AVGAS 100LL" if state == "available" else "",
        "amdt": "01/25",
    }


def _idx(*icaos):
    return {i: Coordinate(lon=3.0, lat=50.0, name=f"{i} Field") for i in icaos}


def test_assembles_avgas_only_features():
    records = {"lf": {"LFAV": _rec("LFAV"), "LFNL": _rec("LFNL", "nil"), "LFUN": _rec("LFUN", "unknown")}}
    idx = {"lf": _idx("LFAV", "LFNL", "LFUN")}
    res = assemble(records, idx, airac_cycle="2609", effective_date="2026-09-03")
    schema.validate_dataset(res.dataset)
    icaos = [f["properties"]["icao"] for f in res.dataset["features"]]
    assert icaos == ["LFAV"]                    # AVGAS-only
    # Published `country` is the uppercased ICAO prefix (provider code "lf" -> "LF").
    assert res.dataset["features"][0]["properties"]["country"] == "LF"
    assert set(res.non_avgas) == {"LFNL", "LFUN"}
    assert res.dataset["metadata"]["feature_count"] == 1


def test_metadata_has_schema_version_and_attribution():
    records = {"lf": {"LFAV": _rec("LFAV")}}
    res = assemble(records, {"lf": _idx("LFAV")}, airac_cycle="2609", effective_date="2026-09-03")
    meta = res.dataset["metadata"]
    assert meta["schema_version"] == schema.SCHEMA_VERSION
    assert meta["airac_cycle"] == "2609"
    assert meta["attribution"]["coordinates"] == "OpenAIP"
    assert meta["attribution"]["fuel"] == {"LF": "SIA"}
    assert meta["countries"] == ["LF"]


def test_name_falls_back_to_openaip():
    records = {"lf": {"LFAV": _rec("LFAV", name=None)}}
    res = assemble(records, {"lf": _idx("LFAV")}, airac_cycle="2609", effective_date="2026-09-03")
    assert res.dataset["features"][0]["properties"]["name"] == "LFAV Field"


def test_parser_provided_name_wins():
    records = {"lf": {"LFAV": _rec("LFAV", name="Parser Name")}}
    res = assemble(records, {"lf": _idx("LFAV")}, airac_cycle="2609", effective_date="2026-09-03")
    assert res.dataset["features"][0]["properties"]["name"] == "Parser Name"


def test_unmatched_coordinates_dropped_and_reported():
    records = {"lf": {"LFAV": _rec("LFAV"), "LFZZ": _rec("LFZZ")}}
    idx = {"lf": _idx("LFAV")}  # LFZZ absent from coords
    res = assemble(records, idx, airac_cycle="2609", effective_date="2026-09-03")
    icaos = [f["properties"]["icao"] for f in res.dataset["features"]]
    assert icaos == ["LFAV"]
    assert res.unmatched_coords == ["LFZZ"]


def test_nonconforming_provider_rejected_wholesale():
    bad = _rec("LFAV")
    bad["fuel_state"] = "banana"  # invalid
    records = {"lf": {"LFAV": bad, "LFOH": _rec("LFOH")}}
    res = assemble(records, {"lf": _idx("LFAV", "LFOH")}, airac_cycle="2609", effective_date="2026-09-03")
    assert "lf" in res.rejected_countries
    assert res.dataset["features"] == []       # nothing from FR published
    assert res.dataset["metadata"]["feature_count"] == 0


def test_features_sorted_by_icao():
    records = {"lf": {"LFOH": _rec("LFOH"), "LFAV": _rec("LFAV")}}
    res = assemble(records, {"lf": _idx("LFAV", "LFOH")}, airac_cycle="2609", effective_date="2026-09-03")
    icaos = [f["properties"]["icao"] for f in res.dataset["features"]]
    assert icaos == ["LFAV", "LFOH"]
