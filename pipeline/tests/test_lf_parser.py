"""Tests for the lf (France) parser: AVT extraction, grades, conditions, e2e.

Fixture-driven and network-free. Covers the documented spike edge cases.
"""

from __future__ import annotations

import os

import pytest

from avgasmap import schema
import avgasmap.providers.lf as lf_pkg
from avgasmap.providers.lf import LfParser
from avgasmap.providers.lf import avt as avt_mod
from avgasmap.providers.lf import conditions as cond_mod
from avgasmap.providers.lf import grades as grades_mod
from tests.fixtures.lf.cases import CASES


# --- extraction (avt.py) ----------------------------------------------------

def test_amdt_extraction():
    assert avt_mod.extract_amdt("... AMDT 01/25 ...") == "01/25"
    assert avt_mod.extract_amdt("no amdt here") is None


def test_avt_anchor_extracts_inline_value():
    md = CASES["LFAV"]["markdown"]
    block = avt_mod.extract_avt(md)
    assert "100 LL" in block
    assert "RFFS" not in block  # cut at the next item


def test_avt_table_fallback_recovers_detached_value():
    md = CASES["LFOH"]["markdown"]
    block = avt_mod.extract_avt(md)
    assert "AVGAS 100LL" in block


def test_avt_missing_returns_empty():
    assert avt_mod.extract_avt("nothing useful here") == ""


# --- grades + fuel state (grades.py) ----------------------------------------

@pytest.mark.parametrize("icao", list(CASES))
def test_classification_matches_fixture(icao):
    md = CASES[icao]["markdown"]
    avt = avt_mod.extract_avt(md)
    state, gr = grades_mod.classify(avt)
    assert state == CASES[icao]["expect_state"], icao
    assert gr == CASES[icao]["expect_grades"], icao


def test_generic_avgas_alone_yields_generic_grade():
    # "AVGAS" with no specific grade -> generic AVGAS grade, aerodrome available.
    state, gr = grades_mod.classify("Carburant : AVGAS available")
    assert gr == ["AVGAS"]
    assert state == "available"


def test_specific_grade_drops_generic_avgas():
    # A specific grade present alongside the word AVGAS -> generic dropped.
    state, gr = grades_mod.classify("Carburant AVGAS : 100 LL")
    assert gr == ["100LL"]
    assert state == "available"


def test_positional_nil_ignores_lubricants_grades():
    avt = "Fuel : NIL. Lubrifiants : 100 LL type oil ref"
    assert grades_mod.is_nil_fuel(avt) is True
    assert grades_mod.find_avgas_grades(avt) == []


def test_jet_a1_never_becomes_a_grade():
    state, gr = grades_mod.classify("Fuel : JET A1")
    assert "100LL" not in gr and gr == []
    assert grades_mod.has_jet_a1("Fuel : JET A1") is True


# --- conditions (conditions.py) ---------------------------------------------

def test_conditions_detects_flags_and_values():
    c = cond_mod.detect_conditions(
        "(AIR BP) 100 LL. PPR. O/R. Automate H24. CIV-MIL. Cash, CB. Tel 01 23 45 67 89"
    )
    assert c["ppr"] is True
    assert c["on_request"] is True
    assert c["self_service"] is True
    assert c["mil_civ_split"] is True
    assert c["has_hours"] is True
    assert c["brand"] == "AIR BP"
    assert "cash" in c["payment"] and "card" in c["payment"]
    assert c["phone"] is not None


def test_conditions_shape_is_schema_valid():
    c = cond_mod.detect_conditions("100 LL")
    schema.validate_conditions(c)


def test_brand_inferred_from_fuel_card():
    # A named brand is not always present; an accepted brand card implies it.
    assert cond_mod.detect_conditions("100LL par carte TOTAL uniquement.")["brand"] == "TOTAL"
    assert cond_mod.detect_conditions("Automate carte Sterling (Air BP).")["brand"] == "AIR BP"
    # Bare "carte BP" is Air BP in the French AIP.
    assert cond_mod.detect_conditions("Paiement carte BP.")["brand"] == "AIR BP"
    # A directly-named brand wins over a different card.
    assert cond_mod.detect_conditions("TOTAL station, carte BP acceptee.")["brand"] == "TOTAL"


def test_brand_not_matched_as_substring():
    # "aviation" must not read as the AVIA brand (LFGB regression); brands are
    # matched as whole words only.
    assert cond_mod.detect_conditions(
        "Fuel : 100 LL, Lubrifiant : qualité aviation / aviation quality (CIV)."
    )["brand"] is None
    # A genuine AVIA station is still detected.
    assert cond_mod.detect_conditions("Carburant 100LL. Station AVIA.")["brand"] == "AVIA"


def test_conditions_extracts_website_and_email():
    c = cond_mod.detect_conditions(
        "Fuel online booking : https://totalenergi.es/resatoussus - E-mail : ops@ad.fr"
    )
    assert c["website"] == "https://totalenergi.es/resatoussus"
    assert c["email"] == "ops@ad.fr"


def test_phone_keeps_trunk_marker():
    c = cond_mod.detect_conditions("TEL : +33 (0)1 39 56 31 26.")
    assert c["phone"] == "+33 (0)1 39 56 31 26"


# --- source_text cleanup (clean_source_text) --------------------------------

def test_clean_source_text_keeps_balanced_italics():
    # Balanced `_..._` italic pairs (the EN-translation marker) are preserved.
    out = lf_pkg.clean_source_text("Carburant / _Fuel : 100 LL._")
    assert out == "Carburant / _Fuel : 100 LL._"


def test_clean_source_text_strips_broken_underscore_artifacts():
    # An odd/broken underscore line has its stray markers dropped.
    out = lf_pkg.clean_source_text("Carburants / _Fuel : 100 LL /_ _H24 dispenser:_ __ paiement")
    assert "_" not in out
    assert "Fuel : 100 LL" in out and "paiement" in out


def test_clean_source_text_strips_bold_and_control_chars():
    # pymupdf4llm leaves ** bold markers and stray control chars (e.g. \x07);
    # both are noise to strip, wording preserved (audit finding: LFBY/LFMY/...).
    out = lf_pkg.clean_source_text("\x07Carburants / Fuel : 100 LL - UL 91**")
    assert "**" not in out and "\x07" not in out
    assert "100 LL" in out and "UL 91" in out


# --- end-to-end LfParser ----------------------------------------------------

@pytest.mark.parametrize("icao", list(CASES))
def test_parse_markdown_produces_valid_record(icao):
    parser = LfParser()
    rec = parser.parse_markdown(icao, CASES[icao]["markdown"])
    schema.validate_fuel_record(rec)
    assert rec["icao"] == icao
    assert rec["fuel_state"] == CASES[icao]["expect_state"]
    assert rec["avgas_grades"] == CASES[icao]["expect_grades"]
    assert rec["jet_a1"] == CASES[icao]["expect_jet_a1"]
    assert rec["name"] is None  # coordinates/name come from OpenAIP


def test_military_chart_is_unknown_not_fatal():
    parser = LfParser()
    rec = parser.parse_markdown("LFRJ", CASES["LFRJ"]["markdown"])
    assert rec["fuel_state"] == "unknown"
    assert rec["source_text"] == ""


def test_chart_paths_filters_and_maps(tmp_path):
    # Create a mix of valid LF**, an LF## strip, a non-French ICAO, a non-pdf.
    for name in ["LFAV.pdf", "LFOH.pdf", "LF12.pdf", "HLLT.pdf", "notes.txt"]:
        (tmp_path / name).write_text("x")
    parser = LfParser()
    paths = parser.chart_paths(str(tmp_path))
    assert set(paths) == {"LFAV", "LFOH"}
    assert paths["LFAV"].endswith(os.path.join("", "LFAV.pdf"))


# --- --keep-intermediates markdown dump -------------------------------------

def test_parse_dumps_markdown_when_dir_given(tmp_path, monkeypatch):
    import avgasmap.providers.lf as lf_pkg

    md = CASES["LFAV"]["markdown"]
    monkeypatch.setattr(lf_pkg, "_pdf_to_markdown", lambda path: md)
    md_dir = tmp_path / "md" / "lf"
    md_dir.mkdir(parents=True)

    parser = LfParser()
    rec = parser.parse("LFAV", "ignored.pdf", md_dump_dir=str(md_dir))

    dumped = md_dir / "LFAV.md"
    assert dumped.is_file()
    assert dumped.read_text(encoding="utf-8") == md
    # Dumping does not change parsing.
    assert rec["fuel_state"] == "available"
    assert rec["avgas_grades"] == ["100LL"]


def test_parse_writes_no_markdown_without_dir(tmp_path, monkeypatch):
    import avgasmap.providers.lf as lf_pkg

    monkeypatch.setattr(lf_pkg, "_pdf_to_markdown", lambda path: CASES["LFAV"]["markdown"])
    parser = LfParser()
    parser.parse("LFAV", "ignored.pdf")  # default md_dump_dir="" -> no file

    assert list(tmp_path.iterdir()) == []
