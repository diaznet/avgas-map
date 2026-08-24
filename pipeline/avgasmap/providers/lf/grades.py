"""France-specific AVGAS grade + fuel-state classification (deterministic).

Rules grounded in the spike (see .kiro/specs/avgas-map/vac-avt-findings.md):
- Normalize grade wording to the closed vocabulary 100LL / UL91 / 100/130.
- Generic "AVGAS" with no specific grade -> treat as 100LL is NOT assumed;
  generic AVGAS alone counts as unknown grade unless a specific grade appears.
  (We only ever emit closed-vocabulary grades; a bare "AVGAS" token without a
  specific grade does not by itself add a grade.)
- Exclude non-AVGAS: JET A1, military F18/F34/F35, lubricants (O###/H###).
- Jet A-1 is captured as a secondary boolean; it never affects AVGAS.
- NIL is read positionally against the FUEL value, not the lubricants value.

No LLM, pure regex/rules (R4.9), so results are reproducible and auditable.
"""

from __future__ import annotations

import re

# Specific AVGAS grades, ordered; each maps wording variants to a canonical key.
_GRADE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("100/130", re.compile(r"100\s*/\s*130")),
    ("100LL", re.compile(r"100\s*LL", re.IGNORECASE)),
    # UL91 appears as "UL 91" and, in real VACs, also as "91 UL" (number first).
    ("UL91", re.compile(r"\bUL\s*91\b|\b91\s*UL\b", re.IGNORECASE)),
]

# Bare "AVGAS" token: indicates AVGAS availability without naming a grade.
# Used only as a fallback when no specific grade matched.
_GENERIC_AVGAS = re.compile(r"\bAVGAS\b", re.IGNORECASE)

# Non-AVGAS tokens we explicitly exclude from grades.
_JET_A1 = re.compile(r"\bJET\s*A1\b", re.IGNORECASE)
_MIL_F = re.compile(r"\bF\s?(?:18|34|35)\b", re.IGNORECASE)

# NIL as a standalone token (word-boundaried, case-insensitive).
_NIL = re.compile(r"\bNIL\b", re.IGNORECASE)

# The fuel value often precedes a lubricants/oil sub-field. French VACs use
# "Lubrifiants" (fuel first, then oil). We split on that so NIL can be read
# positionally against the fuel portion only.
_LUBRICANTS_SPLIT = re.compile(r"\bLubrifiants?\b|\bHuiles?\b", re.IGNORECASE)


def fuel_portion(avt: str) -> str:
    """Return the fuel part of an AVT block, excluding any lubricants sub-field."""
    m = _LUBRICANTS_SPLIT.search(avt)
    return avt[: m.start()] if m else avt


def find_avgas_grades(avt: str) -> list[str]:
    """Return normalized AVGAS grades found in the fuel portion, in canonical order.

    100/130 is checked before 100LL so the "/130" form isn't mis-split. If no
    specific grade matches but a bare "AVGAS" token is present, return the
    generic ["AVGAS"] (the aerodrome offers AVGAS, grade unspecified).
    """
    text = fuel_portion(avt)
    found: list[str] = []
    for key, pat in _GRADE_PATTERNS:
        if pat.search(text) and key not in found:
            found.append(key)
    if found:
        # Canonical order: 100LL, UL91, 100/130 (schema order); generic dropped
        # because a specific grade is present.
        order = {"100LL": 0, "UL91": 1, "100/130": 2}
        return sorted(found, key=lambda g: order[g])
    # No specific grade: fall back to generic AVGAS if the token is present.
    if _GENERIC_AVGAS.search(text):
        return ["AVGAS"]
    return []


def has_jet_a1(avt: str) -> bool:
    """True if Jet A-1 is mentioned anywhere (secondary detail, whole block)."""
    return bool(_JET_A1.search(avt))


def is_nil_fuel(avt: str) -> bool:
    """True if the FUEL value is explicitly NIL (read positionally, not oil)."""
    return bool(_NIL.search(fuel_portion(avt)))


def classify(avt: str | None) -> tuple[str, list[str]]:
    """Classify an AVT block into (fuel_state, avgas_grades).

    - "" or None (AVT not found/parsed) -> ("unknown", [])
    - AVGAS grade present -> ("available", grades)
    - explicit NIL fuel and no grades -> ("nil", [])
    - fuel present but no AVGAS grade (e.g. only JET A1) -> ("nil"? no):
      this is "no AVGAS" but fuel exists; per the flight-safety framing an
      aerodrome only counts as available with an AVGAS grade, and it is not
      "nil" (fuel is not absent). We map "fuel-but-no-AVGAS" to "unknown" for
      AVGAS purposes is wrong too. We use: grades present -> available; explicit
      NIL -> nil; otherwise -> unknown (we cannot assert AVGAS availability).
    """
    if not avt or not avt.strip():
        return ("unknown", [])
    grades = find_avgas_grades(avt)
    if grades:
        return ("available", grades)
    if is_nil_fuel(avt):
        return ("nil", [])
    return ("unknown", [])
