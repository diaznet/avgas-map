# ADR-0003: LLM-assisted extraction QA is advisory-only, never a data source

## Status
Accepted

## Context
Fuel extraction from the French VAC charts is deterministic, code-only (regex /
rule) with no runtime LLM — see Requirement 4.9 and the "NO LLM at runtime"
contract in [`vac-avt-findings.md`](../../.kiro/specs/avgas-map/vac-avt-findings.md).
That choice was made for cost, determinism/auditability, and flight-safety (a
model can hallucinate or drop a fuel grade — unacceptable for safety data).

The deterministic parser inevitably misses things a reader would catch: a grade
stated in prose it didn't pattern-match, a mis-read NIL, a phone/website it
skipped. Finding those today means eyeballing 273+ blocks by hand.

The findings doc already anticipated this: "An LLM, if ever used, would be an
offline QA/fallback pass on the residue, never a runtime dependency." A local
LLM (Ollama on the GitHub Actions runner, open-weight model, no external API)
makes such a pass free and keeps all chart data on the runner.

## Decision
An LLM may be used **only as an advisory quality-assurance pass** over the
already-parsed data. It:

- reads `(source_text, parsed fields)` and emits **structured suggestions**
  (missing grade, wrong state, missed contact, etc.) into the **processing
  report only**;
- **never writes the published dataset** and **never edits code**;
- runs **outside the publish path** — a separate, non-blocking workflow / opt-in
  local mode — so the publish job stays deterministic and fast;
- runs with the model pinned and temperature 0 (as reproducible as a local LLM
  allows), and the never-worse guard and all published fields remain independent
  of its output.

The path from a suggestion to an improvement is human-mediated: a recurring
suggestion pattern (e.g. "N aerodromes state a grade the parser missed") is a
parser-rule bug, which a human or agent fixes as a deterministic rule + a
regression fixture. The LLM finds discrepancies; people turn them into rules.
The published data and the code both stay under deterministic, reviewed control.

## Consequences
- Requirement 4.9 (deterministic, code-only published extraction) is preserved
  intact — the LLM sits beside the pipeline, not inside the data path.
- Extraction coverage improves over time because the QA pass surfaces exactly
  which deterministic rules to add, with the discrepancy doubling as a test case.
- The QA pass is non-deterministic run-to-run; this is acceptable because it is
  advisory and never gates publishing. It must never be wired into the guard.
- Added CI wall-clock (CPU-only inference) is confined to a separate job, so it
  never slows or blocks the publish path.
- No chart data or secrets leave the runner (local inference only).

## Alternatives considered
- **LLM auto-corrects the published dataset** (fumes straight into GeoJSON):
  rejected. Makes safety data non-deterministic and non-reproducible and admits
  hallucinated/dropped grades — a direct violation of R4.9 and the flight-safety
  framing. A wrong grade a pilot trusts is worse than a missing one.
- **LLM as the primary extractor** (replace the rules): rejected for the same
  determinism/auditability/cost reasons the original code-only decision rested
  on.
- **Cloud LLM API**: rejected. Adds cost, an external dependency, and sends
  chart data off-box, against the static/no-cost and data-locality posture.
