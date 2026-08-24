"""Tests for the CountryParser interface and the provider registry."""

from __future__ import annotations

import pytest

from avgasmap import providers, schema
from avgasmap.interface import CountryParser, FuelRecord


class FakeParser:
    """An in-memory parser standing in for a real country module."""

    code = "zz"                       # lowercased ICAO prefix (provider identity)
    icao_pattern = r"^ZZ[A-Z]{2}$"
    openaip_iso = ["zz"]              # ISO cc(s) for the OpenAIP fetch

    def __init__(self, records: dict[str, FuelRecord]):
        self._records = records

    def chart_paths(self, country_dir: str) -> dict[str, str]:
        return {icao: f"{country_dir}/{icao}.pdf" for icao in self._records}

    def parse(self, icao: str, chart_path: str, md_dump_dir: str = "") -> FuelRecord:
        return self._records[icao]


def _record(icao="ZZAA") -> FuelRecord:
    return {
        "icao": icao,
        "name": "Fake Field",
        "fuel_state": "available",
        "avgas_grades": ["100LL"],
        "jet_a1": False,
        "conditions": {
            "on_request": False, "ppr": False, "self_service": False,
            "reserved_for_based": False, "mil_civ_split": False,
            "has_hours": False, "payment": [], "brand": None, "phone": None,
        },
        "source_text": "AVGAS 100LL",
        "amdt": None,
    }


def test_fake_parser_satisfies_protocol():
    parser = FakeParser({"ZZAA": _record()})
    assert isinstance(parser, CountryParser)


def test_registry_register_and_lookup():
    parser = FakeParser({"ZZAA": _record()})
    providers.register(parser)
    try:
        assert providers.get_parser("zz") is parser
        assert "zz" in providers.enabled_parsers()
    finally:
        # keep the registry clean for other tests
        providers._REGISTRY.pop("zz", None)


def test_parser_output_conforms_to_schema():
    parser = FakeParser({"ZZAA": _record()})
    paths = parser.chart_paths("/tmp/zz")
    assert paths == {"ZZAA": "/tmp/zz/ZZAA.pdf"}
    rec = parser.parse("ZZAA", paths["ZZAA"])
    schema.validate_fuel_record(rec)  # must not raise
