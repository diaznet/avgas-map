"""Shared dataset assembly: parsers -> AVGAS-only features -> validated dataset.

Takes the fuel records produced per country, keeps only those offering AVGAS
(fuel_state 'available' — the sole marker criterion), joins coordinates from
OpenAIP by ICAO, and builds a schema-valid GeoJSON FeatureCollection with
metadata. Records that are 'nil'/'unknown' are excluded from the map (they go to
the report). A provider whose output does not conform to the schema is rejected
in full (R5.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from avgasmap import coordinates, schema
from avgasmap.coordinates import Coordinate

# Fuel-source attribution keyed by provider code (lowercased ICAO prefix).
FUEL_ATTRIBUTION = {"lf": "SIA"}


@dataclass
class AssemblyResult:
    dataset: dict
    # Diagnostics for the processing report:
    rejected_countries: dict[str, str] = field(default_factory=dict)  # cc -> reason
    unmatched_coords: list[str] = field(default_factory=list)         # ICAOs dropped
    non_avgas: list[str] = field(default_factory=list)                # nil/unknown ICAOs


def _feature(record: dict, coord: Coordinate, code: str) -> dict:
    # `code` is the provider's lowercased ICAO prefix (e.g. "lf"); the published
    # `country` property uses it uppercased (e.g. "LF").
    props = {
        "icao": record["icao"],
        "name": record.get("name") or coord.name,
        "country": code.upper(),
        "fuel_state": record["fuel_state"],
        "avgas_grades": record["avgas_grades"],
        "jet_a1": record["jet_a1"],
        "conditions": record["conditions"],
        "source_text": record["source_text"],
        "amdt": record.get("amdt"),
        "source": FUEL_ATTRIBUTION.get(code, code),
    }
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [coord.lon, coord.lat]},
        "properties": props,
    }


def assemble(
    records_by_country: dict[str, dict[str, dict]],
    indexes_by_country: dict[str, dict[str, Coordinate]],
    *,
    airac_cycle: str,
    effective_date: str,
    generated_at: str | None = None,
) -> AssemblyResult:
    """Assemble a validated dataset from per-provider fuel records + coord indexes.

    records_by_country: provider code (lowercased ICAO prefix) -> {icao -> FuelRecord}
    indexes_by_country: provider code -> {icao -> Coordinate}
    """
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = AssemblyResult(dataset={})
    features: list[dict] = []
    codes_used: list[str] = []  # provider codes (lowercased ICAO prefix)

    for code in sorted(records_by_country):
        records = records_by_country[code]

        # Validate every record from this provider; reject the provider on any
        # non-conforming output (do not let partial/bad data downstream).
        try:
            for icao, rec in records.items():
                schema.validate_fuel_record(rec, where=f"{code}:{icao}")
        except schema.SchemaError as exc:
            result.rejected_countries[code] = str(exc)
            continue

        # Keep AVGAS-only; note the rest for the report.
        avgas_records = {}
        for icao, rec in records.items():
            if rec["fuel_state"] == "available":
                avgas_records[icao] = rec
            else:
                result.non_avgas.append(icao)

        # Join coordinates by exact ICAO; drop + report unmatched.
        index = indexes_by_country.get(code, {})
        join_res = coordinates.join(avgas_records, index)
        result.unmatched_coords.extend(join_res.unmatched)

        for icao in sorted(join_res.joined):
            rec, coord = join_res.joined[icao]
            features.append(_feature(rec, coord, code))

        if avgas_records:
            codes_used.append(code)

    result.non_avgas.sort()
    result.unmatched_coords.sort()

    dataset = {
        "type": "FeatureCollection",
        "metadata": {
            "schema_version": schema.SCHEMA_VERSION,
            "airac_cycle": airac_cycle,
            "effective_date": effective_date,
            "generated_at": generated_at,
            # `countries` and attribution keys are uppercased ICAO prefixes (LF).
            "countries": [c.upper() for c in codes_used],
            "attribution": {
                "fuel": {c.upper(): FUEL_ATTRIBUTION.get(c, c) for c in codes_used},
                "coordinates": coordinates.ATTRIBUTION,
            },
            "feature_count": len(features),
        },
        "features": features,
    }

    # The assembled dataset must itself be valid (defensive; catches bugs).
    schema.validate_dataset(dataset)
    result.dataset = dataset
    return result
