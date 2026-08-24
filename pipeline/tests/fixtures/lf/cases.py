"""France VAC test fixtures.

Each case is a small piece of VAC-converted markdown around the "10 - AVT" item,
modelled on the real examples documented in the spike
(.kiro/specs/avgas-map/vac-avt-findings.md), plus the expected classification.

These stand in for the spike's cached out/avt/*.md (deleted). They exercise the
documented edge cases: specific grades, generic, UL91, 100/130, positional NIL,
fuel-but-no-AVGAS, MIL/CIV, table-layout fallback, value-after-lubricants, and
unparseable military charts.
"""

from __future__ import annotations

# icao -> dict(markdown, expect_state, expect_grades, expect_jet_a1)
CASES: dict[str, dict] = {
    # LFAV: AIR BP 100LL + JET A1, civ+mil, cash/BP card.
    "LFAV": {
        "markdown": (
            "**9 - RENS** : Valenciennes\n\n"
            "**10 - AVT** : Carburants / _Fuel_ : (AIR BP) 100 LL-JET A1. "
            "(CIV-MIL) Cash, BP card.\n\n"
            "**11 - RFFS** : NIL\n\n"
            "AMDT 01/25"
        ),
        "expect_state": "available",
        "expect_grades": ["100LL"],
        "expect_jet_a1": True,
    },
    # LFBY: MIL F34, CIV 100LL + UL91 with phone numbers.
    "LFBY": {
        "markdown": (
            "**10 - AVT** : MIL : F34 - CIV : 100 LL - UL 91. "
            "Tel 01 23 45 67 89.\n\n"
            "**11 - RFFS** : niveau 1"
        ),
        "expect_state": "available",
        "expect_grades": ["100LL", "UL91"],
        "expect_jet_a1": False,
    },
    # LFAE: AVGAS UL91 reserved for based ACFT.
    "LFAE": {
        "markdown": (
            "**10 - AVT** : AVGAS UL91 : reserved for based ACFT.\n\n"
            "**11 - RFFS** : NIL"
        ),
        "expect_state": "available",
        "expect_grades": ["UL91"],
        "expect_jet_a1": False,
    },
    # 100/130 present.
    "LFXX": {
        "markdown": (
            "**10 - AVT** : Carburants / _Fuel_ : 100/130, JET A1.\n\n"
            "**11 - RFFS** : NIL"
        ),
        "expect_state": "available",
        "expect_grades": ["100/130"],
        "expect_jet_a1": True,
    },
    # Positional NIL: fuel NIL, but lubricants line mentions grades/oil — must
    # still classify nil (grades only counted in the fuel portion).
    "LFNL": {
        "markdown": (
            "**10 - AVT** : Carburants / _Fuel_ : NIL. "
            "Lubrifiants / _Oil_ : NIL.\n\n"
            "**11 - RFFS** : NIL"
        ),
        "expect_state": "nil",
        "expect_grades": [],
        "expect_jet_a1": False,
    },
    # Fuel but no AVGAS: only JET A1 -> not 'available' (no AVGAS), not explicit
    # NIL fuel -> 'unknown' for AVGAS purposes.
    "LFJT": {
        "markdown": (
            "**10 - AVT** : Carburants / _Fuel_ : JET A1 only.\n\n"
            "**11 - RFFS** : NIL"
        ),
        "expect_state": "unknown",
        "expect_grades": [],
        "expect_jet_a1": True,
    },
    # LFBG-style: grades continue after a Lubrifiants break (must not be clipped)
    # and full item captured up to item 11. Military F-grades are not AVGAS.
    "LFBG": {
        "markdown": (
            "**10 - AVT** : Carburants / _Fuel_ : 100 LL. "
            "Lubrifiants / _Oil_ : F18 - F34 - F35.\n\n"
            "**11 - RFFS** : niveau 2"
        ),
        "expect_state": "available",
        "expect_grades": ["100LL"],
        "expect_jet_a1": False,
    },
    # LFOH table layout: the "10 - AVT" label is detached; the fuel value lands
    # on its own line starting with a fuel keyword + ':'. Fallback must recover.
    "LFOH": {
        "markdown": (
            "| Item | Value |\n"
            "| --- | --- |\n"
            "| 10 - AVT | |\n"
            "| 11 - RFFS | niveau 1 |\n\n"
            "AVGAS 100LL : Automate H24 CB.\n"
        ),
        "expect_state": "available",
        "expect_grades": ["100LL"],
        "expect_jet_a1": False,
    },
    # LFRJ / LFRL military "TRANSIT VFR": text not extractable -> no AVT found.
    "LFRJ": {
        "markdown": "TRANSIT VFR \ufffd\ufffd\ufffd\ufffd naval air station (no extractable text)",
        "expect_state": "unknown",
        "expect_grades": [],
        "expect_jet_a1": False,
    },
}
