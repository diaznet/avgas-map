"""`lf` provider (France) — the reference CountryParser implementation.

Provider identity is the lowercased ICAO prefix `lf` (see CONTEXT.md). France's
aerodromes are OpenAIP ISO `fr`, declared in `openaip_iso` for the coordinate
fetch only.

Turns a French VAC PDF into a normalized FuelRecord by:
  1. converting the PDF to markdown (pymupdf4llm),
  2. extracting the "10 - AVT" fuel block (+ table fallback) and AMDT,
  3. classifying AVGAS grades and fuel state,
  4. detecting condition flags, and
  5. retaining the verbatim AVT text as source_text.

Retrieval and coordinates are NOT this parser's concern. Everything France-
specific (the AVT anchor, French wording, AMDT format) lives under this package.
"""

from __future__ import annotations

import logging
import os
import re

from avgasmap.interface import FuelRecord

log = logging.getLogger("avgasmap.lf")
from avgasmap.providers.lf import avt as avt_mod
from avgasmap.providers.lf import conditions as cond_mod
from avgasmap.providers.lf import grades as grades_mod

# Metropolitan/overseas French ICAOs use "LF" + two letters (e.g. LFAV). We
# deliberately skip "LF##" ULM strips and non-French ICAOs sharing the folder.
_ICAO_RE = re.compile(r"^LF[A-Z]{2}$")


# pymupdf4llm marks the AIP's English translation as italic, i.e. wraps it in
# `_..._`. We keep those balanced markers (the front-end uses them to split
# FR/EN) but strip the artifacts: stray/unbalanced underscores, and underscores
# glued to word boundaries (`/_ _H24`), which are conversion noise, not italics.
# It also leaves `**` bold markers and occasional control chars (e.g. \u0007) —
# both pure noise to strip.
_MULTISPACE = re.compile(r"[ \t]{2,}")
# Control characters except tab/newline (kept for line structure).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_source_text(text: str) -> str:
    """Remove PDF->markdown conversion artifacts from an AVT block.

    Preserves balanced `_italic_` spans (the English translation marker) but
    drops dangling/unbalanced underscores, `**` bold markers, and stray control
    characters, without changing the substantive wording. Idempotent.
    """
    if not text:
        return text
    out_lines: list[str] = []
    for line in text.split("\n"):
        s = _CONTROL.sub("", line)       # drop stray control chars (e.g. \u0007)
        s = s.replace("**", "")          # drop leftover bold markers
        s = re.sub(r"_{2,}", "_", s)     # collapse underscore runs
        # Keep balanced `_...text..._` italic pairs (the English-translation
        # marker the front-end splits on); everything else is conversion noise.
        # Pair up underscores left-to-right: even-indexed markers open a span,
        # odd-indexed close it. Any leftover (unpaired) underscore is dropped.
        if s.count("_") % 2 == 1:
            # Odd count: an italic span is broken across lines (an artifact).
            # Drop every underscore on the line rather than guess the pairing.
            s = s.replace("_", " ")
        s = _MULTISPACE.sub(" ", s).rstrip()
        out_lines.append(s)
    # Drop leading/trailing blank lines produced by the cleanup.
    while out_lines and not out_lines[0].strip():
        out_lines.pop(0)
    while out_lines and not out_lines[-1].strip():
        out_lines.pop()
    return "\n".join(out_lines)


def _pdf_to_markdown(pdf_path: str) -> str:
    """Convert a VAC PDF to markdown. Isolated for easy monkeypatching in tests."""
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(pdf_path)
    try:
        return pymupdf4llm.to_markdown(doc)
    finally:
        doc.close()


class DependencyError(RuntimeError):
    """A required chart-conversion dependency is missing or unimportable."""


class LfParser:
    """France provider, keyed by the lowercased ICAO prefix `lf`."""

    code = "lf"                       # lowercased ICAO prefix (provider identity)
    icao_pattern = r"^LF[A-Z]{2}$"
    openaip_iso = ["fr"]              # ISO cc(s) for the OpenAIP coordinate fetch

    # --- CountryParser interface -------------------------------------------

    @staticmethod
    def check_dependencies() -> None:
        """Verify PDF-conversion deps import before a live run does any work.

        Raises DependencyError with an actionable message (failing import +
        interpreter) so a broken interpreter — e.g. running system Python instead
        of the venv, where pymupdf's native `_extra` DLL fails to load on
        Windows — aborts loudly instead of silently converting every chart to
        empty text and tripping the never-worse guard.
        """
        import sys

        try:
            import pymupdf  # noqa: F401
            import pymupdf4llm  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - re-raised as an actionable error
            raise DependencyError(
                f"lf provider: cannot import PDF-conversion dependencies "
                f"({type(exc).__name__}: {exc}). Interpreter: {sys.executable}. "
                f"Install pipeline/requirements.txt into THIS interpreter, or run "
                f"the pipeline with the project venv "
                f"(e.g. .\\pipeline\\.venv\\Scripts\\python.exe)."
            ) from exc

    def chart_paths(self, country_dir: str) -> dict[str, str]:
        """Map ICAO -> local VAC PDF path under a retrieved country directory.

        Expects the shared retrieval to have laid out one PDF per aerodrome as
        `<country_dir>/<ICAO>.pdf`. Filters to ^LF[A-Z]{2}$; skips anything else
        and any ICAO without a PDF.
        """
        out: dict[str, str] = {}
        if not os.path.isdir(country_dir):
            return out
        for entry in sorted(os.listdir(country_dir)):
            if not entry.lower().endswith(".pdf"):
                continue
            icao = entry[:-4].upper()
            if not _ICAO_RE.match(icao):
                continue
            out[icao] = os.path.join(country_dir, entry)
        return out

    def parse(self, icao: str, chart_path: str, md_dump_dir: str = "") -> FuelRecord:
        """Parse one VAC PDF into a FuelRecord. Never raises on parse failure:
        an unextractable chart yields fuel_state 'unknown'.

        When `md_dump_dir` is non-empty, the converted markdown is written to
        `<md_dump_dir>/<ICAO>.md` for debugging (--keep-intermediates). Dumping
        never affects parsing and never raises."""
        try:
            markdown = _pdf_to_markdown(chart_path)
        except Exception as exc:  # noqa: BLE001 - never fail a run on one chart
            # Don't swallow silently: a systematic conversion failure would
            # otherwise turn every chart into 'unknown' with no trace (and trip
            # the never-worse guard) — exactly the kind of failure that must be
            # visible. One line per chart at WARNING; full traceback at DEBUG.
            log.warning("%s: PDF->markdown failed: %s: %s",
                        icao, type(exc).__name__, exc)
            log.debug("%s: conversion traceback", icao, exc_info=True)
            markdown = ""
        if md_dump_dir:
            self._dump_markdown(md_dump_dir, icao, markdown)
        return self.parse_markdown(icao, markdown)

    @staticmethod
    def _dump_markdown(md_dump_dir: str, icao: str, markdown: str) -> None:
        """Write converted markdown for one chart; best-effort, never fatal."""
        try:
            path = os.path.join(md_dump_dir, f"{icao.upper()}.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(markdown)
        except OSError:
            pass

    # --- Testable core (no PDF/network) ------------------------------------

    def parse_markdown(self, icao: str, markdown: str) -> FuelRecord:
        """Build a FuelRecord from already-converted VAC markdown."""
        avt = avt_mod.extract_avt(markdown)
        avt = clean_source_text(avt)
        amdt = avt_mod.extract_amdt(markdown)
        fuel_state, avgas_grades = grades_mod.classify(avt)
        jet_a1 = grades_mod.has_jet_a1(avt) if avt else False
        conditions = cond_mod.detect_conditions(avt)

        return {
            "icao": icao.upper(),
            "name": None,  # OpenAIP is the authoritative name source
            "fuel_state": fuel_state,  # available | nil | unknown
            "avgas_grades": avgas_grades,
            "jet_a1": jet_a1,
            "conditions": conditions,
            "source_text": avt,
            "amdt": amdt,
        }
