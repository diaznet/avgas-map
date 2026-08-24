# AGENTS.md

Guidance for agents working in AVGAS-Map. The full feature spec lives in
[`.kiro/specs/avgas-map/requirements.md`](.kiro/specs/avgas-map/requirements.md);
read it for user stories and acceptance criteria. This file holds only the
durable rules that code won't tell you on its own.

## What this is

A free, statically-hosted map of aerodromes offering AVGAS, for pilots planning
fuel stops. France ships first, sourced from the official SIA eAIP. No backend,
no hosting cost.

## Workflow (spec-first — mandatory)

This project is built and maintained through its spec in
[`.kiro/specs/avgas-map/`](.kiro/specs/avgas-map/). **Any new feature, behaviour
change, or non-trivial modification MUST go through the spec before code**, in
this order:

1. **Requirements** (`requirements.md`) — capture the change as user stories +
   EARS acceptance criteria. Update the glossary in
   [`CONTEXT.md`](CONTEXT.md) and add a `docs/adr/` ADR if the decision is
   hard-to-reverse.
2. **Design** (`design.md`) — how it fits the architecture (the pluggable
   provider model, the normalized-dataset contract, static hosting). Do not let
   it contradict an invariant below without an explicit spec change.
3. **Tasks** (`tasks.md`) — break it into incremental, testable, ordered steps
   with requirement references.
4. **Implementation** — only then write code, task by task, test-backed, keeping
   the spec and code in lockstep (update the spec in the *same* change, never
   after the fact).

**Docs-before-code, every time.** Update the relevant docs (`requirements.md`,
`design.md`, `tasks.md`, `CONTEXT.md`, and — when hard-to-reverse — a `docs/adr/`
ADR) *before* touching code, in the same change. This is not optional and it is
not "after the fact": if a change alters observable behaviour, a contract, a
vocabulary, or a rule, the doc edit lands first. Never ship a behaviour change
whose only record is the code.

**Before every change, run a quick gap check:** does an existing requirement /
design section / task / glossary term already cover this? If yes, update it in
place. If no, add it. Do not leave a shipped behaviour undocumented, and do not
let a doc describe behaviour the code no longer has.

Only genuinely doc-invisible edits may skip the spec: typo/comment/formatting
fixes, and refactors that change no observable behaviour, no contract, and no
rule. Everything else — including bug fixes that correct user-visible behaviour
(e.g. a wrong fuel provider) or add a rule (e.g. "match brands as whole words") —
carries a doc trace, written first. When in doubt, start at requirements. Never
jump to code for a feature and backfill the spec later.

## Invariants

These are decided. Breaking one is a bug, not a style choice.

- **The normalized dataset is the contract.** Every country provider emits the
  same normalized GeoJSON; the front-end reads only that. Keep country-specific
  shapes (eAIP quirks, PDF fields) inside the provider, never leak them into the
  map or the combined dataset.
- **Providers are pluggable per country.** A new country is a new provider
  behind the common interface. Adding one must not require touching the map
  front-end or the pipeline wiring.
- **Static hosting only.** The site is static assets on GitHub Pages, and the
  front-end loads aerodrome data from static files. Never introduce a backend
  server or a paid service.
- **Never publish worse data than last time.** If a provider or the pipeline
  fails, keep the last known-good dataset. Do not overwrite it with an empty or
  partial result.
- **Flight-safety framing.** When the source doesn't specify a detail, render it
  as "unknown", never as "unavailable". An aerodrome counts as offering AVGAS
  only if the source indicates an AVGAS grade. The disclaimer (not an official
  source) and source attribution (e.g. SIA France) are mandatory on the site.
- **Never read secret files.** The agent must never read, open, print, search,
  or otherwise access the contents of `.env` files or any other secret/credential
  store (only `.env.example`, the secret-free template, is allowed). Reference
  credentials by variable name (`AUTOROUTER_USER` / `AUTOROUTER_PASS`), never by
  value. This is enforced by a `PreToolUse` hook (`.kiro/hooks/block-env-reads.json`
  → `block_env_reads.py`) that blocks any read/search tool targeting a `.env`
  file; the directive binds even where the hook doesn't reach.

## Out of scope (v1)

Fuel pricing, countries other than France, user accounts or submitted data,
routing between aerodromes, real-time NOTAM/outage status, native mobile apps.
Don't build these without a spec change.

## Environment

**Stack:** Python data pipeline (`pipeline/`) + a no-build static front-end
(`web/`, vanilla JS + Leaflet). No backend.

**Layout:**
- `pipeline/avgasmap/` — pipeline package (`schema.py`, `interface.py`,
  `retrieval.py`, `coordinates.py`, `assemble.py`, `airac.py`, `validate.py`,
  `publish.py`, `report.py`, `pipeline.py`, `logconfig.py`; providers under
  `providers/<code>/`, e.g. `providers/lf/`).
- `pipeline/run_pipeline.py` — CLI entry point.
- `pipeline/tests/` — pytest suite + `fixtures/lf/`.
- `web/` — `index.html`, `app.js`, `style.css`, `vendor/` (pinned Leaflet), and
  `data/` (local-only output, gitignored).

**Commands** (Windows / PowerShell; always use the venv interpreter, never the
system `python` — the system pymupdf DLL is broken here and produces an empty
dataset):
- Create venv + deps: `python -m venv pipeline/.venv; .\pipeline\.venv\Scripts\python.exe -m pip install -r pipeline/requirements.txt`
- Run tests (from `pipeline/`): `.\.venv\Scripts\python.exe -m pytest`
- Generate a dataset locally: `.\pipeline\.venv\Scripts\python.exe pipeline\run_pipeline.py --local --cycle <YYNN> --workspace .\pipeline\_run`
  - `--reparse-only` rebuilds from charts already in the workspace (skips the
    download; still ~minutes because PDF→markdown dominates).
  - `--keep-intermediates` dumps converted markdown to `<workspace>/md/<code>/`.
  - `--dry-run` uses fixtures (no network).
- Preview the site: serve `web/` with any static server
  (`python -m http.server` from `web/`).

There is no linter configured yet. Today (the dev date) is not an AIRAC effective
date, so live runs need an explicit `--cycle`.

## Agent skills

### Issue tracker

Issues live in the repo's GitHub Issues (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default triage vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`CONTEXT.md` + `docs/adr/` at the repo root). See `docs/agents/domain.md`.
