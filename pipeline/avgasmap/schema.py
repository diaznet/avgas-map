"""The normalized dataset schema and its validator — the contract.

Every country parser's output and the published GeoJSON must conform to the
shapes defined here. See CONTEXT.md for the domain terms (Map feature, Fuel
state, AVGAS grade, Condition flags, Schema version) and design.md for the
dataset layout.

Validation is deliberately strict and dependency-free (pure Python) so it can
run anywhere and give auditable, specific rejection reasons (R5.4).
"""

from __future__ import annotations

from typing import Any

# Current schema version stamped on every dataset. Bump on any additive change
# to the published feature shape (see CONTEXT.md "Schema version").
SCHEMA_VERSION = 2

# Closed vocabularies.
# Closed AVGAS-grade vocabulary. "AVGAS" is the generic value meaning "AVGAS
# available, grade unspecified"; specific grades are preferred when present.
AVGAS_GRADES: tuple[str, ...] = ("100LL", "UL91", "100/130", "AVGAS")
FUEL_STATES: tuple[str, ...] = ("available", "nil", "unknown")

# Closed `conditions` shape (CONTEXT.md "Condition flags").
CONDITION_BOOL_KEYS: tuple[str, ...] = (
    "on_request",
    "ppr",
    "self_service",
    "reserved_for_based",
    "mil_civ_split",
    "has_hours",
)
CONDITION_VALUE_KEYS: tuple[str, ...] = ("payment", "brand", "phone", "website", "email")

ICAO_LEN = 4


class SchemaError(ValueError):
    """Raised when a record or dataset does not conform to the schema."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaError(message)


def validate_conditions(conditions: Any, *, where: str = "conditions") -> None:
    _require(isinstance(conditions, dict), f"{where} must be an object")
    for key in CONDITION_BOOL_KEYS:
        _require(key in conditions, f"{where}.{key} is required")
        _require(
            isinstance(conditions[key], bool),
            f"{where}.{key} must be a boolean",
        )
    # payment: list[str]
    payment = conditions.get("payment", [])
    _require(isinstance(payment, list), f"{where}.payment must be a list")
    _require(
        all(isinstance(p, str) for p in payment),
        f"{where}.payment must be a list of strings",
    )
    # brand / phone / website / email: str | None
    for key in ("brand", "phone", "website", "email"):
        val = conditions.get(key, None)
        _require(
            val is None or isinstance(val, str),
            f"{where}.{key} must be a string or null",
        )
    # No unexpected keys (closed shape within a schema version).
    allowed = set(CONDITION_BOOL_KEYS) | set(CONDITION_VALUE_KEYS)
    extra = set(conditions) - allowed
    _require(not extra, f"{where} has unexpected keys: {sorted(extra)}")


def validate_avgas_grades(grades: Any, *, where: str = "avgas_grades") -> None:
    _require(isinstance(grades, list), f"{where} must be a list")
    for g in grades:
        _require(
            g in AVGAS_GRADES,
            f"{where} contains invalid grade {g!r}; allowed: {AVGAS_GRADES}",
        )
    _require(len(set(grades)) == len(grades), f"{where} must not contain duplicates")


def validate_fuel_record(record: Any, *, where: str = "record") -> None:
    """Validate a parser's FuelRecord (pre-join, no coordinates)."""
    _require(isinstance(record, dict), f"{where} must be an object")

    icao = record.get("icao")
    _require(isinstance(icao, str), f"{where}.icao must be a string")
    _require(
        len(icao) == ICAO_LEN and icao.isalnum() and icao.isupper(),
        f"{where}.icao must be a {ICAO_LEN}-char uppercase code, got {icao!r}",
    )

    name = record.get("name", None)
    _require(name is None or isinstance(name, str), f"{where}.name must be string or null")

    state = record.get("fuel_state")
    _require(state in FUEL_STATES, f"{where}.fuel_state must be one of {FUEL_STATES}")

    validate_avgas_grades(record.get("avgas_grades"), where=f"{where}.avgas_grades")

    # available <=> at least one AVGAS grade (the sole marker criterion).
    has_grade = bool(record.get("avgas_grades"))
    if state == "available":
        _require(has_grade, f"{where}: fuel_state 'available' requires >=1 AVGAS grade")
    else:
        _require(
            not has_grade,
            f"{where}: fuel_state {state!r} must have no AVGAS grades",
        )

    _require(isinstance(record.get("jet_a1"), bool), f"{where}.jet_a1 must be a boolean")

    validate_conditions(record.get("conditions"), where=f"{where}.conditions")

    _require(isinstance(record.get("source_text"), str), f"{where}.source_text must be a string")

    amdt = record.get("amdt", None)
    _require(amdt is None or isinstance(amdt, str), f"{where}.amdt must be a string or null")


def validate_feature(feature: Any, *, where: str = "feature") -> None:
    """Validate a published GeoJSON Point feature (post-join, AVGAS-only)."""
    _require(isinstance(feature, dict), f"{where} must be an object")
    _require(feature.get("type") == "Feature", f"{where}.type must be 'Feature'")

    geom = feature.get("geometry")
    _require(isinstance(geom, dict), f"{where}.geometry must be an object")
    _require(geom.get("type") == "Point", f"{where}.geometry.type must be 'Point'")
    coords = geom.get("coordinates")
    _require(
        isinstance(coords, list) and len(coords) == 2,
        f"{where}.geometry.coordinates must be [lon, lat]",
    )
    lon, lat = coords
    _require(
        isinstance(lon, (int, float)) and isinstance(lat, (int, float)),
        f"{where}.geometry.coordinates must be numbers",
    )
    _require(-180 <= lon <= 180, f"{where}: lon out of range: {lon}")
    _require(-90 <= lat <= 90, f"{where}: lat out of range: {lat}")

    props = feature.get("properties")
    _require(isinstance(props, dict), f"{where}.properties must be an object")

    # Published features are AVGAS-only.
    _require(
        props.get("fuel_state") == "available",
        f"{where}: published features must have fuel_state 'available'",
    )
    # Reuse the record validator for the shared property shape.
    validate_fuel_record(props, where=f"{where}.properties")

    country = props.get("country")
    _require(isinstance(country, str) and len(country) == 2, f"{where}.properties.country must be a 2-letter code")
    _require(isinstance(props.get("source"), str), f"{where}.properties.source must be a string")


def validate_dataset(dataset: Any, *, where: str = "dataset") -> None:
    """Validate a full FeatureCollection with metadata."""
    _require(isinstance(dataset, dict), f"{where} must be an object")
    _require(
        dataset.get("type") == "FeatureCollection",
        f"{where}.type must be 'FeatureCollection'",
    )

    meta = dataset.get("metadata")
    _require(isinstance(meta, dict), f"{where}.metadata must be an object")
    _require(
        isinstance(meta.get("schema_version"), int),
        f"{where}.metadata.schema_version must be an int",
    )
    _require(isinstance(meta.get("airac_cycle"), str), f"{where}.metadata.airac_cycle must be a string")
    _require(isinstance(meta.get("effective_date"), str), f"{where}.metadata.effective_date must be a string")
    _require(isinstance(meta.get("generated_at"), str), f"{where}.metadata.generated_at must be a string")
    _require(isinstance(meta.get("countries"), list), f"{where}.metadata.countries must be a list")

    attribution = meta.get("attribution")
    _require(isinstance(attribution, dict), f"{where}.metadata.attribution must be an object")
    _require("fuel" in attribution, f"{where}.metadata.attribution.fuel is required")
    _require("coordinates" in attribution, f"{where}.metadata.attribution.coordinates is required")

    features = dataset.get("features")
    _require(isinstance(features, list), f"{where}.features must be a list")
    for i, feat in enumerate(features):
        validate_feature(feat, where=f"{where}.features[{i}]")

    _require(
        meta.get("feature_count") == len(features),
        f"{where}.metadata.feature_count ({meta.get('feature_count')}) "
        f"must equal number of features ({len(features)})",
    )
