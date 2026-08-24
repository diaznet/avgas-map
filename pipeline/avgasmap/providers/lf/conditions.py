"""France-specific detection of fuel condition flags from an AVT block.

Produces the closed `conditions` shape (see CONTEXT.md "Condition flags"). The
full AVT text is retained verbatim as source_text elsewhere, so anything not
captured here is never lost. Deterministic regex/rules, no LLM.
"""

from __future__ import annotations

import re

_ON_REQUEST = re.compile(r"\bO\s*/?\s*R\b|\bon\s+request\b|\bsur\s+demande\b", re.IGNORECASE)
_PPR = re.compile(r"\bPPR\b", re.IGNORECASE)
_SELF_SERVICE = re.compile(r"\bautomate\b|\bself[-\s]?service\b|\bCB\s+24\b|\bH24\b.*\bautomate\b", re.IGNORECASE)
_RESERVED_BASED = re.compile(r"reserved?\s+(?:for|to)\s+based|r[eé]serv[eé].*bas[eé]s?", re.IGNORECASE)
_MIL_CIV = re.compile(r"\bMIL\b.*\bCIV\b|\bCIV\b.*\bMIL\b", re.IGNORECASE | re.DOTALL)
_HOURS = re.compile(
    r"\bHOR\b|\bH24\b|\bSR\b|\bSS\b|\d{3,4}\s*[-\u2013]\s*\d{3,4}",
    re.IGNORECASE,
)

# Phone: optional +CC, an optional "(0)" trunk marker, then grouped digits.
_PHONE = re.compile(r"(?:\+\d{1,3}\s*)?(?:\(0\)\s*)?\d(?:[\d .]{6,}\d)")

# Website URL (http/https, and bare domains like totalenergi.es/… used by SIA).
_WEBSITE = re.compile(
    r"\bhttps?://[^\s)]+"
    r"|\bwww\.[^\s)]+"
    r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/[^\s)]+",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Brand vocabulary (closed-ish; extend deliberately). Longest first for matching.
# In the French AIP the aviation fuel brand is "Air BP"; bare "BP" (incl. "carte
# BP") always means Air BP, so we canonicalize it there.
_BRANDS = ["TOTALENERGIES", "TOTAL", "AIR BP", "BP", "SHELL", "ESSO", "AVIA", "DYNEFF"]

# Card-implied brand: an accepted brand fuel card signals the provider even when
# the brand isn't named on its own. "Sterling" is Air BP's card. Ordered so the
# more specific / longer cues win.
_CARD_BRANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcarte\s+air\s*bp\b|\bair\s*bp\s+card\b|\bsterling\b|\bcarte\s+bp\b|\bbp\s+card\b", re.IGNORECASE), "AIR BP"),
    (re.compile(r"\bcarte\s+total(?:energies)?\b|\btotal(?:energies)?\s+card\b|\bcarte\s+air\s*total\b", re.IGNORECASE), "TOTAL"),
    (re.compile(r"\bcarte\s+shell\b|\bshell\s+card\b", re.IGNORECASE), "SHELL"),
    (re.compile(r"\bcarte\s+avia\b|\bavia\s+card\b", re.IGNORECASE), "AVIA"),
]

# Payment vocabulary.
_PAYMENTS = [
    (re.compile(r"\bcash\b|\besp[eè]ces\b|\bnum[eé]raire\b", re.IGNORECASE), "cash"),
    (re.compile(r"\bcarte\b|\bCB\b|\bcard\b|\bvisa\b|\bmastercard\b", re.IGNORECASE), "card"),
    (re.compile(r"\bch[eè]que\b|\bcheck\b", re.IGNORECASE), "cheque"),
    (re.compile(r"\bBP\s+card\b|\bsterling\b|\bcarte\s+(?:TOTAL|AIR\s+BP|SHELL|AVIA)\b", re.IGNORECASE), "fuel_card"),
]

# Canonicalize brand spellings to the display form.
_BRAND_CANON = {"TOTALENERGIES": "TOTAL", "BP": "AIR BP"}

# Word-boundaried brand patterns (longest first so "AIR BP" wins over "BP").
# Whole-word matching is essential: a plain substring test wrongly flags "AVIA"
# inside "aviation" (e.g. "qualité aviation") and "BP" inside other tokens.
_BRAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(b) + r"\b", re.IGNORECASE), b)
    for b in sorted(_BRANDS, key=len, reverse=True)
]


def _detect_brand(text: str) -> str | None:
    """Fuel provider: a directly-named brand wins; else a card-implied brand.

    Brands are matched as whole words (not substrings) so "aviation" does not
    read as the AVIA brand, etc.
    """
    for pat, brand in _BRAND_PATTERNS:
        if pat.search(text):
            return _BRAND_CANON.get(brand, brand)
    # No brand named directly — infer from an accepted brand fuel card.
    for pat, brand in _CARD_BRANDS:
        if pat.search(text):
            return brand
    return None


def _detect_website(text: str) -> str | None:
    m = _WEBSITE.search(text)
    if not m:
        return None
    url = m.group(0).rstrip(".,;)")
    # Don't mistake an email (already has @) for a website.
    if "@" in url:
        return None
    return url


def _detect_email(text: str) -> str | None:
    m = _EMAIL.search(text)
    return m.group(0).rstrip(".,;)") if m else None


def _detect_payment(text: str) -> list[str]:
    found: list[str] = []
    for pat, label in _PAYMENTS:
        if pat.search(text) and label not in found:
            found.append(label)
    return found


def _detect_phone(text: str) -> str | None:
    m = _PHONE.search(text)
    if not m:
        return None
    # Normalize whitespace, and keep the "(0)" trunk marker readable.
    return re.sub(r"\s+", " ", m.group(0)).strip()


def detect_conditions(avt: str) -> dict:
    """Return the closed conditions object for an AVT block."""
    text = avt or ""
    return {
        "on_request": bool(_ON_REQUEST.search(text)),
        "ppr": bool(_PPR.search(text)),
        "self_service": bool(_SELF_SERVICE.search(text)),
        "reserved_for_based": bool(_RESERVED_BASED.search(text)),
        "mil_civ_split": bool(_MIL_CIV.search(text)),
        "has_hours": bool(_HOURS.search(text)),
        "payment": _detect_payment(text),
        "brand": _detect_brand(text),
        "phone": _detect_phone(text),
        "website": _detect_website(text),
        "email": _detect_email(text),
    }
