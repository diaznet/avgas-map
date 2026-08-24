"""France-specific extraction of the VAC fuel field (item "10 - AVT").

FRANCE-ONLY. The `10 - AVT` .. `11 - RFFS` anchor, the bilingual French wording,
and the `AMDT NN/YY` date format are specific to the SIA VAC layout and must not
be treated as universal — other countries implement their own extraction behind
the same CountryParser interface.

Logic grounded in the spike (vac-avt-findings.md):
- Anchor on the "10 - AVT" item label; cut at the next numbered item (11..19).
- Markdown conversion wraps labels in ** and the colon may land inside/outside.
- Table-layout fallback: when the anchor yields nothing (e.g. LFOH renders AD 2
  as a table, detaching label from value), scan for a line starting with a fuel
  keyword (AVGAS / Carburant) + ':'.
- Capture the full item-10 block (value can continue after a Lubrifiants break).
"""

from __future__ import annotations

import re

# "10 - AVT" (hyphen or en dash, optional bold/space noise around the label).
# Markdown noise between tokens: asterisks (bold markers), spaces, hyphens.
# Real VACs render the label as e.g. "**10 -** **AVT :**" — the hyphen sits
# inside the bold and there's a "** **" gap before AVT, so we must tolerate
# arbitrary runs of `*`, whitespace, and the hyphen between "10" and "AVT".
_N = r"[*\s]*"  # asterisks / whitespace filler

# Anchor: item 10 labelled AVT, tolerant of bold/space noise and the hyphen.
_AVT_ANCHOR = re.compile(rf"\b10{_N}[-\u2013]{_N}AVT\b", re.IGNORECASE)
# Next numbered item "11 - RFFS" .. "19 - ...": bounds the AVT block.
_NEXT_ITEM = re.compile(rf"{_N}\b1[1-9]{_N}[-\u2013]{_N}[A-Z]")

# Fallback: a detached fuel statement whose line starts with a fuel keyword + ':'
_AVT_FALLBACK = re.compile(
    r"^\s*\**\s*(?:AVGAS|Carburants?)\b[^\n]*?[:\uFF1A][^\n]*",
    re.IGNORECASE | re.MULTILINE,
)

# AMDT marker, e.g. "AMDT 01/25".
_AMDT = re.compile(r"\bAMDT\s*(\d{2}\s*/\s*\d{2})\b", re.IGNORECASE)

# Leading markdown/colon noise left after the label is stripped.
_LEADING_NOISE = re.compile(r"^[\s*:\uFF1A]+")

# Real content = at least one letter or digit (table cells like "| |" have none).
_HAS_CONTENT = re.compile(r"[A-Za-z0-9]")


def extract_avt(markdown: str) -> str:
    """Return the text of item '10 - AVT' up to the next numbered item.

    Returns "" if neither the anchor nor the fallback finds a fuel value.
    """
    m = _AVT_ANCHOR.search(markdown)
    if m:
        tail = markdown[m.end():]
        nxt = _NEXT_ITEM.search(tail)
        block = tail[: nxt.start()] if nxt else tail[:600]
        block = _LEADING_NOISE.sub("", block).strip()
        # A block with no letters/digits (e.g. an empty table cell "| |") means
        # the value was detached by a table layout -> fall through to fallback.
        if block and _HAS_CONTENT.search(block):
            return block
    # Anchor missing or empty (table layout) -> fallback.
    return _extract_fallback(markdown)


def _extract_fallback(markdown: str) -> str:
    m = _AVT_FALLBACK.search(markdown)
    return m.group(0).strip() if m else ""


def extract_amdt(markdown: str) -> str | None:
    """Return the AMDT marker as 'NN/YY', or None if absent."""
    m = _AMDT.search(markdown)
    if not m:
        return None
    return re.sub(r"\s*", "", m.group(1))
