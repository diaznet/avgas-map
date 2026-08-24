"""Tests for the normalized schema and validator (the contract)."""

from __future__ import annotations

import pytest

from avgasmap import schema
from avgasmap.schema import SchemaError
from tests.helpers import mutate, valid_dataset, valid_feature, valid_record


# --- Valid cases pass -------------------------------------------------------

def test_valid_record_passes():
    schema.validate_fuel_record(valid_record())


def test_valid_feature_passes():
    schema.validate_feature(valid_feature())


def test_valid_dataset_passes():
    schema.validate_dataset(valid_dataset())


def test_nil_and_unknown_records_pass_without_grades():
    schema.validate_fuel_record(
        valid_record(fuel_state="nil", avgas_grades=[])
    )
    schema.validate_fuel_record(
        valid_record(fuel_state="unknown", avgas_grades=[])
    )


# --- Record-level rejections ------------------------------------------------

@pytest.mark.parametrize(
    "path,value",
    [
        ("icao", "lfav"),          # lowercase
        ("icao", "LFA"),           # too short
        ("icao", "LFAV1"),         # too long
        ("fuel_state", "maybe"),   # not in vocab
        ("jet_a1", "yes"),         # not a bool
        ("source_text", None),     # must be str
        ("amdt", 5),               # must be str or None
        ("avgas_grades", ["JET A1"]),  # not an AVGAS grade
        ("avgas_grades", ["100LL", "100LL"]),  # duplicate
    ],
)
def test_record_field_rejections(path, value):
    with pytest.raises(SchemaError):
        schema.validate_fuel_record(mutate(valid_record(), path, value))


def test_available_requires_a_grade():
    with pytest.raises(SchemaError):
        schema.validate_fuel_record(
            valid_record(fuel_state="available", avgas_grades=[])
        )


def test_generic_avgas_is_a_valid_grade():
    # The generic "AVGAS" grade is part of the closed vocabulary and makes an
    # aerodrome available (grade unspecified).
    schema.validate_fuel_record(
        valid_record(fuel_state="available", avgas_grades=["AVGAS"])
    )


def test_conditions_accepts_website_and_email():
    # Schema v2 adds website/email to the closed conditions shape.
    schema.validate_conditions({
        "on_request": False, "ppr": False, "self_service": False,
        "reserved_for_based": False, "mil_civ_split": False, "has_hours": False,
        "payment": [], "brand": "TOTAL",
        "phone": "+33 1 23 45 67 89",
        "website": "https://example.fr/book", "email": "ops@example.fr",
    })


def test_conditions_still_valid_without_new_fields():
    # Back-compat: records lacking website/email still validate.
    schema.validate_conditions({
        "on_request": False, "ppr": False, "self_service": False,
        "reserved_for_based": False, "mil_civ_split": False, "has_hours": False,
        "payment": [], "brand": None, "phone": None,
    })


def test_non_available_must_not_have_grades():
    with pytest.raises(SchemaError):
        schema.validate_fuel_record(
            valid_record(fuel_state="nil", avgas_grades=["100LL"])
        )


# --- Conditions rejections --------------------------------------------------

def test_conditions_missing_bool_rejected():
    rec = valid_record()
    del rec["conditions"]["ppr"]
    with pytest.raises(SchemaError):
        schema.validate_fuel_record(rec)


def test_conditions_unexpected_key_rejected():
    rec = valid_record()
    rec["conditions"]["fizz"] = True
    with pytest.raises(SchemaError):
        schema.validate_fuel_record(rec)


def test_conditions_payment_must_be_string_list():
    with pytest.raises(SchemaError):
        schema.validate_fuel_record(
            mutate(valid_record(), "conditions.payment", [1, 2])
        )


# --- Feature-level rejections -----------------------------------------------

def test_feature_requires_available_state():
    with pytest.raises(SchemaError):
        schema.validate_feature(
            valid_feature(fuel_state="nil", avgas_grades=[])
        )


@pytest.mark.parametrize(
    "coords",
    [[200, 0], [0, 100], [0], "nope"],
)
def test_feature_bad_coordinates_rejected(coords):
    feat = valid_feature()
    feat["geometry"]["coordinates"] = coords
    with pytest.raises(SchemaError):
        schema.validate_feature(feat)


def test_feature_missing_country_rejected():
    feat = valid_feature()
    del feat["properties"]["country"]
    with pytest.raises(SchemaError):
        schema.validate_feature(feat)


# --- Dataset-level rejections -----------------------------------------------

def test_dataset_feature_count_mismatch_rejected():
    ds = valid_dataset()
    ds["metadata"]["feature_count"] = 99
    with pytest.raises(SchemaError):
        schema.validate_dataset(ds)


def test_dataset_missing_attribution_rejected():
    ds = valid_dataset()
    del ds["metadata"]["attribution"]["coordinates"]
    with pytest.raises(SchemaError):
        schema.validate_dataset(ds)


def test_dataset_propagates_bad_feature():
    ds = valid_dataset([valid_feature(fuel_state="nil", avgas_grades=[])])
    with pytest.raises(SchemaError):
        schema.validate_dataset(ds)
