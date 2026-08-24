"""Shared test helpers: builders for valid records / features / datasets."""

from __future__ import annotations

import copy
from typing import Any


def valid_conditions(**overrides: Any) -> dict:
    base = {
        "on_request": False,
        "ppr": False,
        "self_service": True,
        "reserved_for_based": False,
        "mil_civ_split": False,
        "has_hours": True,
        "payment": ["card", "cash"],
        "brand": "AIR BP",
        "phone": "+33123456789",
    }
    base.update(overrides)
    return base


def valid_record(**overrides: Any) -> dict:
    base = {
        "icao": "LFAV",
        "name": "Valenciennes Denain",
        "fuel_state": "available",
        "avgas_grades": ["100LL", "UL91"],
        "jet_a1": True,
        "conditions": valid_conditions(),
        "source_text": "Carburants / Fuel : (AIR BP) 100 LL-JET A1.",
        "amdt": "01/25",
    }
    base.update(overrides)
    return base


def valid_feature(**prop_overrides: Any) -> dict:
    props = valid_record()
    props.update({"country": "FR", "source": "SIA"})
    props.update(prop_overrides)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [3.46, 50.33]},
        "properties": props,
    }


def valid_dataset(features: list[dict] | None = None) -> dict:
    feats = [valid_feature()] if features is None else features
    return {
        "type": "FeatureCollection",
        "metadata": {
            "schema_version": 1,
            "airac_cycle": "2609",
            "effective_date": "2026-09-03",
            "generated_at": "2026-09-03T04:12:00Z",
            "countries": ["FR"],
            "attribution": {"fuel": {"FR": "SIA"}, "coordinates": "OpenAIP"},
            "feature_count": len(feats),
        },
        "features": feats,
    }


def mutate(obj: dict, path: str, value: Any) -> dict:
    """Return a deep copy of obj with a dotted path set to value.

    Supports dict keys and list indices, e.g. "properties.avgas_grades".
    """
    out = copy.deepcopy(obj)
    cur: Any = out
    parts = path.split(".")
    for p in parts[:-1]:
        cur = cur[int(p)] if p.isdigit() else cur[p]
    last = parts[-1]
    if last.isdigit():
        cur[int(last)] = value
    else:
        cur[last] = value
    return out
