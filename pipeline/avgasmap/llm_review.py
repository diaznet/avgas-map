"""Advisory LLM extraction-QA pass (report-only). See ADR-0003 and R4.10.

This module NEVER writes the published dataset, gates publishing, touches the
never-worse guard, or edits code. It reads already-parsed fuel records against
their verbatim source text and emits *suggestions* about likely extraction gaps,
for a human to turn into deterministic parser rules + fixtures.

Determinism is not guaranteed (it's a local LLM); that's acceptable because the
output is advisory only. The model is pinned and run at temperature 0 for as
much reproducibility as local inference allows.

The LLM client is injected (a tiny protocol), so the review logic is unit-tested
with a fake client and no real model / network.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable, Protocol

log = logging.getLogger("avgasmap.llm_review")

# Pinned default: chosen by benchmark (see design.md). qwen3:8b gave the best
# balance of low false-alarm rate (23%) and high bug-catch recall (83%),
# dominating the prior qwen2.5:7b default (40% / 67%). It's a reasoning model,
# hence slower — acceptable because the pass is separate and non-blocking. A
# smaller model can be substituted via --llm-model where speed matters more.
DEFAULT_MODEL = "qwen3:8b"

# Closed set of suggestion kinds, so findings aggregate into patterns rather than
# 273 one-offs. "other" is the catch-all. Scope is deliberately narrow: grades
# and fuel state only. missed_brand/missed_contact were removed after two runs
# produced ~only false positives there (a manual audit confirmed the
# deterministic brand/contact detection was already correct). ADR-0003, R4.10.
SUGGESTION_KINDS = (
    "missing_grade",     # text states an AVGAS grade that avgas_grades omits
    "wrong_state",       # fuel_state looks wrong vs. the text (e.g. NIL mis-read)
    "other",
)
_CONFIDENCE = ("low", "medium", "high")


@dataclass(frozen=True)
class Suggestion:
    """One advisory finding about a single aerodrome. Report-only."""

    icao: str
    kind: str
    detail: str
    confidence: str = "medium"

    def __post_init__(self) -> None:
        if self.kind not in SUGGESTION_KINDS:
            raise ValueError(f"unknown suggestion kind: {self.kind!r}")
        if self.confidence not in _CONFIDENCE:
            raise ValueError(f"unknown confidence: {self.confidence!r}")

    def as_dict(self) -> dict:
        return {"icao": self.icao, "kind": self.kind,
                "detail": self.detail, "confidence": self.confidence}


class LlmClient(Protocol):
    """Minimal LLM surface: one deterministic-ish text completion."""

    def generate(self, prompt: str) -> str:
        """Return the model's raw text response to `prompt`."""
        ...


# --- Prompt -----------------------------------------------------------------

_PROMPT_HEADER = """\
You audit an automated parser that extracts aviation fuel facts from a French
aerodrome chart's fuel text (item "10 - AVT"). You are given the verbatim SOURCE
TEXT and the parser's PARSED fields. Check ONLY two things: the AVGAS grades and
the fuel state. Ignore brand, phone, website, email, hours, and payment entirely.

A discrepancy exists ONLY when the SOURCE TEXT literally contains something that
PARSED got wrong or omitted. If in doubt, report nothing.

RULES (violating these produces useless noise):
- Consider ONLY AVGAS grades and fuel_state. Do NOT comment on brand or contacts.
- AVGAS grades vocabulary: 100LL, UL91, 100/130, and the generic AVGAS.
  * Jet A-1 is NOT an AVGAS grade and is tracked separately — NEVER report Jet A-1
    as a missing grade.
  * When the text names a SPECIFIC grade (e.g. 100 LL), the parser correctly drops
    the generic "AVGAS"; do NOT report generic AVGAS as missing in that case.
  * Military fuels (F18, F34, F35) and lubricants are NOT AVGAS grades.
- NEVER invent a grade absent from the SOURCE TEXT; only flag a grade the text
  actually contains that PARSED omitted.
- fuel_state is available|nil|unknown. "nil" means the FUEL value is NIL — a
  "Lubrifiant/Lubricant : NIL" is about lubricants, NOT fuel, and is not a
  discrepancy. Operating hours/PPR/conditions do NOT change fuel_state.
- NEVER report a value PARSED already contains.
- If grades and state are consistent with the text, return an empty JSON array.

Reply with ONLY a JSON array (no prose), each item:
  {"kind": <missing_grade|wrong_state|other>,
   "detail": <short explanation citing the source-text words>,
   "confidence": <low|medium|high>}
"""


def build_prompt(record: dict) -> str:
    """Construct the per-record audit prompt from a normalized fuel record."""
    c = record.get("conditions") or {}
    parsed = {
        "fuel_state": record.get("fuel_state"),
        "avgas_grades": record.get("avgas_grades"),
        "jet_a1": record.get("jet_a1"),
        "brand": c.get("brand"),
        "phone": c.get("phone"),
        "website": c.get("website"),
        "email": c.get("email"),
    }
    return (
        _PROMPT_HEADER
        + f"\nAERODROME: {record.get('icao', '????')}\n"
        + "\nSOURCE TEXT:\n"
        + (record.get("source_text") or "(empty)")
        + "\n\nPARSED:\n"
        + json.dumps(parsed, ensure_ascii=False)
        + "\n\nJSON array of discrepancies:"
    )


# --- Response parsing -------------------------------------------------------

_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def _parse_response(icao: str, raw: str) -> list[Suggestion]:
    """Parse a model response into Suggestions; drop malformed output (advisory)."""
    m = _JSON_ARRAY.search(raw or "")
    if not m:
        log.debug("%s: no JSON array in model response", icao)
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        log.warning("%s: could not parse model JSON; dropping", icao)
        return []
    if not isinstance(items, list):
        return []
    out: list[Suggestion] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind", "other"))
        if kind not in SUGGESTION_KINDS:
            kind = "other"
        conf = str(it.get("confidence", "medium"))
        if conf not in _CONFIDENCE:
            conf = "medium"
        detail = str(it.get("detail", "")).strip()
        if not detail:
            continue
        out.append(Suggestion(icao=icao, kind=kind, detail=detail, confidence=conf))
    return out


# --- Public API -------------------------------------------------------------

def review_records(
    records: Iterable[dict], *, client: LlmClient, model: str = DEFAULT_MODEL,
) -> list[Suggestion]:
    """Advisory QA over parsed records. Returns suggestions; mutates nothing.

    `records` are normalized fuel records (dicts). `client` is injected so tests
    can supply a fake. Never raises on a single bad record: a failing/garbled
    call is logged and skipped (the pass is best-effort and non-load-bearing).
    """
    suggestions: list[Suggestion] = []
    for record in records:
        icao = record.get("icao", "????")
        try:
            raw = client.generate(build_prompt(record))
        except Exception as exc:  # noqa: BLE001 - advisory pass never fails a run
            log.warning("%s: LLM call failed (%s); skipping", icao, exc)
            continue
        suggestions.extend(_parse_response(icao, raw))
    log.info("LLM review (%s): %d suggestion(s) across reviewed records",
             model, len(suggestions))
    return suggestions


def group_by_kind(suggestions: list[Suggestion]) -> dict[str, list[Suggestion]]:
    """Group suggestions by `kind` so the report shows patterns, not one-offs."""
    grouped: dict[str, list[Suggestion]] = {}
    for s in suggestions:
        grouped.setdefault(s.kind, []).append(s)
    return grouped


def render_suggestions_markdown(suggestions: list[Suggestion], *, model: str) -> str:
    """Render suggestions grouped by kind (patterns first), for the report."""
    grouped = group_by_kind(suggestions)
    lines = [
        "## LLM extraction-QA suggestions (advisory — never published)",
        "",
        f"- Model: `{model}` · suggestions: **{len(suggestions)}**",
        "- Advisory only: these do NOT change the dataset or code. A recurring "
        "kind is a parser-rule bug to fix (rule + fixture).",
        "",
    ]
    if not suggestions:
        lines += ["_No discrepancies suggested._", ""]
        return "\n".join(lines)
    for kind in SUGGESTION_KINDS:
        items = grouped.get(kind, [])
        if not items:
            continue
        lines.append(f"### {kind} ({len(items)})")
        lines.append("")
        for s in sorted(items, key=lambda x: x.icao):
            lines.append(f"- **{s.icao}** _{s.confidence}_: {s.detail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_suggestions(suggestions: list[Suggestion], json_path: str) -> None:
    """Write suggestions.json (a build artifact; never committed, never shipped)."""
    import os

    os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump([s.as_dict() for s in suggestions], fh, ensure_ascii=False, indent=2)


class OllamaClient:
    """Thin client for a local Ollama server (no external API). Temperature 0.

    `requests` is imported lazily so unit tests (which inject a fake client)
    don't require it or a running server.
    """

    def __init__(self, model: str = DEFAULT_MODEL,
                 host: str = "http://localhost:11434", timeout: float = 120.0):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        import requests

        resp = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "seed": 0},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
