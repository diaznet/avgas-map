# Design Document

## Overview

AVGAS-Map is a static web map of aerodromes offering AVGAS, for pilots planning
fuel stops. Scope is the EASA area (charts available through the autorouter
WebDAV); France is the first country implemented.

The system has two cleanly separated halves that share only one thing — the
**normalized GeoJSON dataset** (the contract):

- A **Python data pipeline** that runs on AIRAC dates in GitHub Actions. It
  retrieves charts, parses fuel data per country, joins coordinates from
  OpenAIP, validates, and publishes each cycle's dataset as a GitHub Release
  asset. It commits nothing to the repository.
- A **static front-end** (plain HTML/JS + Leaflet) deployed to GitHub Pages via
  build-and-deploy. It loads a cycle manifest, lets the user pick an AIRAC cycle
  (default latest), fetches that cycle's dataset from its Release asset, and
  renders markers with fuel detail.

This design realizes the invariants in `AGENTS.md`: the normalized dataset is
the contract, providers are pluggable per country, hosting is static-only, a
failed run never publishes worse data than the last good one, and flight-safety
framing (unknown vs. unavailable, AVGAS-only markers, mandatory disclaimer and
attribution) is preserved.

### Key decisions (from the design interview)

| Area | Decision |
|------|----------|
| Pipeline language | Python 3.12 (reuses proven `pymupdf4llm` PDF handling) |
| Front-end | Plain HTML/JS, no build step |
| Map library | Leaflet + OSM tiles + marker-cluster plugin (keyless, free) |
| Parser boundary | Parser receives a local PDF path, returns ICAO-keyed fuel records |
| Dataset shape | One combined GeoJSON per cycle, AVGAS-only features |
| Coordinates | OpenAIP per-country airport export (public S3, configurable endpoint), joined by ICAO |
| Repo commits | None from CI; datasets → Release assets, site → Pages artifact |
| History | One GitHub Release per AIRAC cycle, tag `airac-<YYNN>`; retain all |
| Cycle discovery | `index.json` manifest shipped with the site; marks `latest` |
| Trigger | Daily cron gated on a committed AIRAC calendar + `workflow_dispatch` |
| Never-worse guard | Absolute floor AND relative-drop check before publishing |
| Report | CI job summary + uploaded artifact; not committed |
| Credentials | Pipeline reads env vars only (portable); CI = GitHub secrets, local = shell or optional gitignored `.env` |

## Architecture

```
                       GitHub Actions (AIRAC-gated)
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                    │
  │  autorouter WebDAV ──fetch──▶ [retrieval]  (shared, all countries) │
  │        (VAC/AIP PDFs)              │                               │
  │                                    ▼                               │
  │                          [country parser]   FR: VAC AVT parser     │
  │                          (pluggable, per-country)                  │
  │                                    │  ICAO-keyed fuel records       │
  │  OpenAIP bucket ──fetch──▶ [coordinate join by ICAO]  (shared)     │
  │    (<cc>_apt.geojson)              │                               │
  │                                    ▼                               │
  │                          [assemble normalized GeoJSON]  (shared)   │
  │                                    │                               │
  │                          [validate: floor + relative drop]         │
  │                            pass │        │ fail → abort, keep last  │
  │                                 ▼                                  │
  │            [publish Release asset airac-<YYNN>] + [regen manifest]  │
  │                                 │                                  │
  │            [build-and-deploy web/ + manifest → GitHub Pages]        │
  │                                                                    │
  │            [report → job summary + artifact]  (never committed)    │
  └──────────────────────────────────────────────────────────────────┘

  Browser (GitHub Pages):
     load index.json ──▶ cycle dropdown (default latest)
                          │ fetch dataset for selected cycle (Release asset)
                          ▼
                       Leaflet map: clustered AVGAS markers + popups
                       top bar: cycle | grade filter | search
                       footer: freshness | disclaimer | SIA + OpenAIP attribution
```

The dashed boundary is the contract: everything left of "assemble" may be
country-specific; everything from "assemble" rightward is shared and never needs
to change to add a country.

## Repository layout

```
avgas-map/
├─ pipeline/                     # Python data pipeline
│  ├─ avgasmap/
│  │  ├─ __init__.py
│  │  ├─ retrieval.py            # shared: autorouter WebDAV fetch (bounded, ret/backoff)
│  │  ├─ coordinates.py          # shared: OpenAIP fetch + ICAO join
│  │  ├─ assemble.py             # shared: build normalized GeoJSON FeatureCollection
│  │  ├─ validate.py             # shared: never-worse guard (floor + relative drop)
│  │  ├─ publish.py              # shared: GitHub Release asset + manifest regen
│  │  ├─ report.py               # shared: processing report (job summary + artifact)
│  │  ├─ logconfig.py            # shared: stage progress logging (stderr, INFO/DEBUG)
│  │  ├─ airac.py                # shared: read AIRAC calendar, is-today-an-AIRAC-date
│  │  ├─ schema.py               # shared: normalized feature schema + validation
│  │  ├─ interface.py            # shared: CountryParser protocol
│  │  ├─ llm_review.py           # shared: advisory LLM extraction-QA pass (ADR-0003)
│  │  └─ providers/
│  │     ├─ __init__.py          # provider registry (enabled countries)
│  │     └─ lf/                  # provider keyed by lowercased ICAO prefix (France)
│  │        ├─ __init__.py       # LfParser(CountryParser); code="lf", openaip_iso=["fr"]
│  │        ├─ avt.py            # FR-only: 10-AVT..11-RFFS anchor + table fallback
│  │        ├─ grades.py         # FR-only: grade normalization + NIL + Jet A-1
│  │        └─ conditions.py     # FR-only: condition-flag detection
│  ├─ tests/
│  │  ├─ fixtures/lf/            # real AVT blocks (regenerated from spike) as fixtures
│  │  └─ test_*.py
│  ├─ run_pipeline.py            # entry point (CLI)
│  ├─ requirements.txt           # pinned: pymupdf4llm, pymupdf, webdavclient3, python-dotenv, ...
│  ├─ .env.example               # template for AUTOROUTER_USER / AUTOROUTER_PASS (real .env gitignored)
│  └─ README.md                  # dev setup incl. credential env-var options
├─ web/                          # static front-end (deployed as-is)
│  ├─ index.html
│  ├─ app.js                     # map, manifest load, cycle/grade/search wiring
│  ├─ style.css
│  ├─ vendor/                    # leaflet + markercluster (pinned)
│  └─ data/                      # LOCAL ONLY: --local output (index.json + geojson), gitignored
├─ .github/workflows/
│  ├─ pipeline.yml               # AIRAC-gated build + publish + deploy
│  └─ llm-review.yml             # advisory LLM extraction-QA (Ollama; report-only, no publish)
├─ .kiro/
│  ├─ specs/avgas-map/           # this spec
│  └─ hooks/                     # block-env-reads.json + block_env_reads.py (secrets guard)
├─ docs/
├─ README.md                     # project overview + quickstart (canonical for run-locally)
├─ AGENTS.md
└─ .gitignore                    # ignores web/data/, pipeline/.env, out/
```

Generated data (`dataset.geojson`, `report.md`, `index.json`, downloaded PDFs,
and any `--keep-intermediates` markdown dumps) is never committed — it is
produced in the runner workspace and shipped to
Releases / Pages.

## Components and Interfaces

### The contract: normalized dataset schema

A cycle's dataset is a single GeoJSON `FeatureCollection`. Only aerodromes whose
`fuel_state == available` (≥1 AVGAS grade) are emitted as features (R1.2, R6.3).
`nil` / `unknown` aerodromes are not in the map data — they appear only in the
processing report.

Top-level FeatureCollection carries dataset metadata:

```json
{
  "type": "FeatureCollection",
  "metadata": {
    "airac_cycle": "2609",
    "schema_version": 1,
    "effective_date": "2026-09-03",
    "generated_at": "2026-09-03T04:12:00Z",
    "countries": ["LF"],
    "attribution": { "fuel": { "LF": "SIA" }, "coordinates": "OpenAIP" },
    "feature_count": 296
  },
  "features": [ /* Feature per AVGAS aerodrome */ ]
}
```

Each `Feature` is a `Point` with these `properties`:

```json
{
  "icao": "LFAV",
  "name": "Valenciennes Denain",
  "country": "LF",
  "fuel_state": "available",
  "avgas_grades": ["100LL", "UL91"],
  "jet_a1": true,
  "conditions": {
    "on_request": false, "ppr": false, "self_service": true,
    "reserved_for_based": false, "mil_civ_split": false,
    "has_hours": true, "payment": ["card", "cash"],
    "brand": "AIR BP", "phone": "+33..."
  },
  "source_text": "Carburants / Fuel : (AIR BP) 100 LL-JET A1. ...",
  "amdt": "01/25",
  "source": "SIA"
}
```

`source_text` is the verbatim fuel text from the country's source (country-
agnostic name; for France this is the raw AVT block). `geometry.coordinates` is
`[lon, lat]` from the OpenAIP join. `schema.py` validates every feature against
the shape for the dataset's `schema_version`; a parser that yields non-
conforming records is rejected (R5.4). Schema changes are additive-only within
a major line so older cycles stay renderable; the front-end renders what is
present and treats missing fields as unknown (never assumes a field exists).

### Shared: `CountryParser` interface (`interface.py`)

```python
class FuelRecord(TypedDict):
    icao: str
    name: str | None          # parser may provide; OpenAIP is authoritative fallback
    fuel_state: Literal["available", "nil", "unknown"]
    avgas_grades: list[str]   # subset of {"100LL","UL91","100/130","AVGAS"} (generic last)
    jet_a1: bool
    conditions: dict          # closed shape (incl. brand/phone/website/email), see CONTEXT.md
    source_text: str          # verbatim source fuel text (FR: raw AVT block), artifact-cleaned
    amdt: str | None

class CountryParser(Protocol):
    code: str                              # lowercased ICAO prefix, e.g. "lf"
    icao_pattern: str                      # r"^LF[A-Z]{2}$"
    openaip_iso: list[str]                 # ISO cc(s) for OpenAIP fetch, e.g. ["fr"]
    def chart_paths(self, country_dir: str) -> dict[str, str]: ...
        # ICAO -> local path of the chart PDF to parse (after shared retrieval)
    def parse(self, icao: str, pdf_path: str) -> FuelRecord: ...
        # parse ONE aerodrome's chart into a fuel record
```

Provider identity is the lowercased ICAO prefix (`code`, e.g. `lf`); it names the
package, keys the registry, and becomes the dataset's `country`/attribution
(uppercased, `LF`). `openaip_iso` is declared separately and used only for the
OpenAIP fetch (ISO-keyed files). See CONTEXT.md "Country parser" + "OpenAIP ISO code".

The shared retrieval downloads what `chart_paths` names; the shared assembler
calls `parse` per aerodrome, validates, and joins coordinates. A parser touches
neither the network nor the schema assembly — it only turns a local chart into a
`FuelRecord`.

### The `lf` parser (`providers/lf/`, France) — one implementation, France-only

Everything here is specific to the French SIA VAC layout and must not be treated
as a universal rule (the AVT anchor works for France only; other countries will
need entirely different extraction behind this same interface):

- **`chart_paths`**: enumerate `France/<ICAO> - <name>/VFR/AD 2 <ICAO> VAC.pdf`
  under the WebDAV France dir, filter to `^LF[A-Z]{2}` with a `VFR/` folder,
  skip non-French ICAOs and entries with no VAC PDF (R4.1).
- **`parse`**: convert PDF→markdown with `pymupdf4llm`; anchor on
  `10 - AVT` .. `11 - RFFS`; on empty/table layout, apply the fallback (scan for
  a line starting `AVGAS`/`Carburant` + `:`) (R4.6); capture the full item-10
  block; extract `AMDT NN/YY`.
- **`grades.py`**: normalize to `{100LL, UL91 (incl. "91 UL"), 100/130}`; keep a
  bare `AVGAS` token as the generic grade `AVGAS` (so the aerodrome is
  `available`), but drop it when a specific grade is present; exclude `JET A1`,
  military `F18/F34/F35`, lubricants; detect Jet A-1 as a secondary boolean;
  read `NIL` positionally against the fuel value, not the lubricants value
  (R4.3, R4.3a, R4.4).
- **`conditions.py`**: presence flags + values (on-request, PPR, self-service,
  reserved-for-based, MIL/CIV, hours, payment, brand, phone, website, email);
  the remainder stays in `source_text` verbatim (R4.5). Brand detection reads
  both directly-named brands and brand fuel cards (`carte TOTAL` ⇒ `TOTAL`,
  `Sterling`/`carte BP` ⇒ `AIR BP`, …), preferring a named brand (R4.5a).
  Website (`http(s)://…`) and email are extracted for clickable links (R4.5b).
- **`parse` / source_text cleanup**: strip conversion artifacts left by
  `pymupdf4llm` without changing wording — stray/unbalanced `_` italic markers,
  leftover `**` bold markers, and stray control characters (e.g. `\u0007`). The
  FR and EN renderings are preserved so the front-end can toggle between them
  (French AIP emits the FR line then an italic EN translation) (R4.5c).
- All deterministic regex/rule code — no runtime LLM (R4.9).

This is a `conditions` shape change (new `website`/`email` fields), so it is a
deliberate `SCHEMA_VERSION` bump per CONTEXT.md — additive, so older cycles stay
renderable and the front-end treats missing fields as unknown.

### Front-end rendering additions

- **Provider filter**: a topbar filter-group of the brands present in the loaded
  cycle (derived from the data, not hard-coded), filtering markers by
  `conditions.brand` alongside the existing grade filter (R3.4).
- **Fuel colours**: AVGAS grade badges render red, the Jet A-1 indicator black,
  per the international convention (R2.8).
- **Links**: `conditions.phone` → `tel:`, `conditions.website` → `http(s)`
  anchor, `conditions.email` → `mailto:` (R2.10).
- **FR/EN toggle**: the verbatim source text is split into its French and English
  renderings with a small per-popup toggle (R2.11).

Text-unextractable military charts (LFRJ, LFRL) yield `unknown` and are recorded,
not fatal (R4.7). Since only `available` aerodromes reach the dataset, `nil` /
`unknown` records are dropped from the map and logged.

### Shared: coordinate join (`coordinates.py`)

Fetch OpenAIP's daily per-country airport export (GeoJSON) from its public S3
bucket `openaip-system-exports`, served anonymously over HTTPS. The endpoint is
kept **configurable** — OpenAIP has changed its export location before
(deprecated `.aip` XML → a GCS bucket → now S3). The pipeline reads the base URL
and per-country key pattern from config:

```
OPENAIP_EXPORT_BASE   = "https://storage.openaip.net/openaip-system-exports/"
OPENAIP_KEY_TEMPLATE  = "{country}_apt.geojson"   # {country} = ISO cc lowercase
```

Confirmed against the live bucket listing: exports follow `<cc>_<type>.<format>`
(e.g. `at_apt.geojson`, `be_apt.geojson`, `ch_apt.geojson`), so France airports
resolve to `https://storage.openaip.net/openaip-system-exports/fr_apt.geojson`.
These two config values are the single point to update if OpenAIP relocates
again — no code change beyond config. The fetch is public and keyless. Build an
`ICAO -> [lon,lat] (+ name)` index, join each `available` fuel record by ICAO.
If an AVGAS aerodrome has no OpenAIP match, drop it and record it in the report
(R6.3). OpenAIP name is used when the parser didn't supply one.

### Shared: assembly, validation, publish

- **`assemble.py`**: merge all enabled providers' records, keep `available`
  only, join coordinates, build the FeatureCollection + metadata, validate every
  feature against `schema.py` (R5.4, R5.6).
- **`validate.py`** (never-worse guard, R7.4): abort publish if
  `feature_count < FLOOR` (absolute; catches total breakage such as WebDAV auth
  failure) OR `feature_count < prev_count * (1 - MAX_DROP)` (relative; catches
  partial breakage). `FLOOR` and `MAX_DROP` are configurable constants
  (initial: FLOOR ≈ 200 given France's ~296, MAX_DROP = 0.20). Previous count
  comes from the latest existing Release's metadata.
- **`publish.py`**: create/replace Release `airac-<YYNN>` with asset
  `dataset.geojson`; regenerate `index.json` by listing existing Releases +
  the new one; mark the newest as `latest`. On any failure: do not publish, do
  not update the manifest, leave the prior latest intact (R7.3, R7.5).

### Shared: AIRAC gating (`airac.py`)

AIRAC effective dates are computed, not stored. The cycle is a fixed 28-day
period anchored to a known epoch (cycle `2001` effective `2020-01-02`); every
cycle is exactly 28 days after the previous, so `effective_date(cycle_id)` and
`cycle_for_date(date)` are pure arithmetic from the epoch (28 days = 4 whole
weeks, so calendar/leap-year shifts are absorbed by the date math — no special
cases). `is_airac_today()` returns the current cycle id if today is an effective
date, else `None`; `current_cycle()` returns the in-force cycle. The cycle id is
`YYNN` (year's last two digits + the 1-based cycle ordinal within that year).
Unit tests pin the epoch and several known effective dates against the public
AIRAC schedule so the arithmetic is verified against a real source. The workflow
runs daily and exits early (no-op) unless today is an AIRAC date or the run is
manually dispatched.

### Front-end (`web/`)

Plain HTML/JS, no build. Load order:

1. Resolve the manifest via **data-source resolution** (see below) → `index.json`.
2. Populate the AIRAC dropdown; select `latest` by default (R9.1, R9.2).
3. Fetch the selected cycle's `dataset.geojson` from the URL the manifest gives
   for that cycle, and render tolerant of its `schema_version` (older cycles stay
   renderable; missing fields → unknown, never assumed present).
4. Render with Leaflet: OSM tiles, `markercluster` for density (R1.4), a marker
   per feature.

**Data-source resolution (production vs. local).** The front-end first tries to
load a local manifest at `data/index.json` (relative to the site). If present,
it uses it and its cycle URLs (which point at local dataset files) — this is the
local-preview path. If absent, it falls back to the published manifest shipped
with the deployed site, whose cycle URLs are GitHub Release asset URLs. This lets
the exact same `web/` run locally against locally-generated data or in production
against Releases, with no code branch beyond the initial try/fallback. `web/data/`
is gitignored; production never contains it.

UI chrome:
- **Top bar**: AIRAC cycle dropdown | grade filter (checkboxes 100LL / UL91 /
  100/130 / AVGAS, R3.3) | provider filter (brands present in the loaded cycle,
  R3.4) | search box (ICAO or name, R3.1; technical/no-match → standard
  "no aerodrome found", R3.2).
- **Marker popup** (R2): name + ICAO; AVGAS grade badges (red per the fuel-colour
  convention, R2.8); Jet A-1 as a secondary line/badge (black, R2.8) if present
  (never affects the marker, R2.3); fuel provider (brand); condition flags as
  small labels; clickable phone/website/email links (R2.10); AMDT date; verbatim
  `source_text` in a collapsible `<details>` with a FR/EN toggle (R2.11).
- **Footer / info panel**: freshness (effective date + AIRAC cycle, shown only
  if both known, R9.1); "not an official source" disclaimer (R9.3); SIA +
  OpenAIP attribution (R9.4, R6.4); a link to the project source repository on
  GitHub (R9.5).

Switching cycles re-fetches that cycle's dataset and updates the freshness
display. Dataset load failure shows a clear error, not a blank map (R1.5).

### Local development / preview

The whole pipeline and front-end run locally end-to-end with no publishing:

- **`run_pipeline.py --local`** runs the full pipeline (AIRAC gate can be
  bypassed with `--cycle <YYNN>` for a chosen cycle) but, instead of publishing a
  Release, writes `dataset.geojson` and a **local `index.json`** into `web/data/`.
  The local manifest's cycle URLs point at the sibling local dataset file(s), not
  Release URLs. `--dry-run` (fixtures, no network) can be combined for a fully
  offline build.
- **`--keep-intermediates`** (default off) persists each chart's converted
  markdown to `<workspace>/md/<code>/<ICAO>.md` as it is parsed, so a
  misclassification can be inspected against the exact text the parser saw
  without re-running the PDF→markdown conversion. Off by default so normal runs
  (including CI) write nothing extra; the dumped markdown lives only in the
  workspace, is never committed, and is never shipped with the site.
- **`--reparse-only`** (default off) rebuilds the dataset from the charts
  already downloaded into `<workspace>/pdf/<code>/`, skipping retrieval. It still
  fetches OpenAIP coordinates and applies the never-worse guard, so the output is
  a normal dataset — just built without re-downloading ~420 PDFs. This lets a
  parser fix (e.g. a brand-detection correction) be re-applied without the
  network round-trip. Note the dominant cost is the PDF→markdown conversion
  (~1 s/chart, done sequentially), not the download, so reparse still takes a
  few minutes for a full country — it saves the retrieval time, not the parse
  time. Requires `--workspace`; incompatible with `--dry-run` (fixtures, not
  charts). If the workspace has no charts for an enabled provider, the run
  reports it rather than silently emitting an empty dataset (which the guard
  would reject anyway). `no-pdf`/fetch-error diagnostics are empty in this mode
  (retrieval didn't run).
- **Serve `web/`** over `http://localhost` with any static server (e.g.
  `python -m http.server` from `web/`); the front-end's data-source resolution
  finds `data/index.json` and renders the locally-generated map. `file://` is not
  supported because it breaks `fetch`.
- Real (non-fixture) local generation for France needs autorouter credentials in
  `AUTOROUTER_USER`/`AUTOROUTER_PASS` (shell env or a gitignored `.env`; see
  `pipeline/README.md`); OpenAIP needs none. The canonical quickstart lives in
  the top-level `README.md`.

## Data Models

- **AIRAC cycle** — computed, not stored: a `YYNN` id and its effective date are
  derived arithmetically from the 28-day epoch (see AIRAC gating). No data file.
- **FuelRecord** — parser output (see interface). Internal to the pipeline.
- **Normalized Feature / FeatureCollection** — the published contract (see
  schema above). GeoJSON, one per cycle.
- **Manifest** — `index.json`. `latest` = newest successfully published cycle
  (valid because the pipeline never pre-publishes future cycles; see ADR-0001).
  Each cycle echoes its `schema_version` so the front-end knows the shape before
  fetching:
  ```json
  { "latest": "2609",
    "cycles": [ { "cycle": "2609", "effective_date": "2026-09-03",
                  "schema_version": 1,
                  "url": "https://github.com/<repo>/releases/download/airac-2609/dataset.geojson" } ] }
  ```

## Error Handling

| Failure | Handling | Requirement |
|---------|----------|-------------|
| Provider chart-conversion dep missing/broken at startup | abort the live run fast, before retrieval, with an actionable message (dep + interpreter) | R7.10 |
| Per-chart PDF→text conversion throws at runtime | log the ICAO + error (WARNING; traceback at DEBUG), record `unknown`, continue | R4.7, R7.11 |
| Aerodrome VAC unparseable | classify `unknown`, record, continue | R4.7 |
| No VAC PDF for aerodrome | skip, record | R4.1 |
| AVGAS aerodrome missing OpenAIP coords | drop, record | R6.3 |
| Parser output non-conforming | reject that provider, exclude from build | R5.4 |
| Dataset below floor / big relative drop | abort publish, keep last good, exit non-zero | R7.4/R7.5 |
| Publish / deploy step fails | last deployed site + last Release remain live | R7.5, R8.4 |
| Run does not publish (skipped on a non-AIRAC date, or guard-failed) | the Pages deploy is gated on the run's `status=published`, so a non-publishing run leaves the last good site + manifest live rather than deploying `web/` with a stale/empty manifest over it | R7.5, R8.4 |
| GitHub read-after-write lag: `list_releases()` right after an upload omits the just-uploaded asset | merge the just-published release (from the upsert's own return value) into the manifest, so the current cycle is never dropped | R7.3 |
| WebDAV / OpenAIP transient error | bounded retry + backoff; if still failing, treat as run failure | R7.7 |
| Front-end dataset load fails | show error message, not a blank map | R1.5 |
| Freshness metadata incomplete | show nothing rather than partial | R9.1 |
| LLM QA pass: malformed model output / model unavailable | drop that suggestion (or skip the pass), log a warning, never fail the run or the dataset (advisory) | R4.10 |

Politeness to sources (R7.7): capped concurrency (default 5–8 workers), retry
with exponential backoff, descriptive User-Agent, fresh fetch each run (runs are
~13×/year so no cross-run cache is needed).

## Security & Credentials

- Autorouter WebDAV uses HTTP Basic. The pipeline reads credentials **only** from
  the environment variables `AUTOROUTER_USER` / `AUTOROUTER_PASS` and knows
  nothing about where they came from — this keeps the code fully portable across
  Windows, Linux (CI), and macOS.
- In CI, those env vars are populated from GitHub Actions secrets, injected for
  the pipeline step only, never logged or echoed.
- For local development, they can be set directly in the shell, or placed in an
  **optional, gitignored `.env`** loaded via `python-dotenv` if present (never
  committed, never used in CI). The `.env` path is the recommended cross-platform
  local option. No OS-specific credential store is used.
- OpenAIP and OSM tiles need no credentials.
- `GITHUB_TOKEN` (provided by Actions) authorizes Release publishing and Pages
  deploy; no extra secrets.
- **Agents must never read secret files.** A repo invariant (AGENTS.md) forbids
  any AI agent from reading, searching, or printing `.env` / secret files (only
  `.env.example` is allowed). It is enforced by a Kiro `PreToolUse` hook
  (`.kiro/hooks/block-env-reads.json` → `block_env_reads.py`) that blocks any
  read/search tool targeting a `.env` file (exit 2), with `.env.example`
  explicitly allowed. Humans edit `.env` normally.

## Observability (logging)

The pipeline emits stage-by-stage logging to stderr via a shared `logconfig`
(INFO by default, DEBUG with `--verbose`), so a multi-minute run is not silent:
- **retrieval** logs connect/list, periodic download progress (~every 5% over
  the ~420-chart fetch), per-aerodrome errors, and a downloaded/no-pdf/error
  summary;
- **coordinates** logs the OpenAIP fetch URL and indexed count;
- **pipeline** logs run start (cycle/mode/providers), per-provider parse counts,
  assembly result (features / non-AVGAS / dropped-for-coords), the guard
  decision, and the terminal outcome; per-chart parsing is logged one line each
  at DEBUG (visible with `--verbose`), so parsing is not silent between the
  retrieval summary and the assembly count.
This is separate from the processing report (a per-run diagnostic artifact); the
log is transient run progress. In CI the same log appears in the Actions step.

**Fail-fast dependency check.** A live run first probes each enabled provider's
chart-conversion dependencies (for `lf`: `pymupdf` + `pymupdf4llm`) via a
provider `check_dependencies()`, before any retrieval. If an import fails
(commonly a broken interpreter — e.g. running system Python instead of the venv,
where `pymupdf`'s native `_extra` DLL won't load on Windows), the run aborts with
a message naming the failing import and `sys.executable`, instead of silently
converting every chart to empty text and producing an all-`unknown` dataset that
trips the never-worse guard with no visible cause. `--dry-run` (fixtures, no PDF
conversion) skips the check. Complementary to this, a per-chart conversion that
throws at runtime is logged (not swallowed), so a partial or systematic failure
is never invisible.

## Extraction QA pass (advisory LLM, R4.10, ADR-0003)

An optional, advisory pass that finds extraction gaps the deterministic parser
missed. It sits **beside** the pipeline, never inside the data path.

**Boundary (non-negotiable).** The QA pass reads `(icao, source_text, parsed
fields)` and produces suggestions only. It never writes the dataset, never gates
the guard, never runs in the publish job, and never edits code. R4.9 (all
published fields are deterministic/code-only) is therefore untouched.

**Module: `avgasmap/llm_review.py`** (pipeline-level, provider-agnostic — it
consumes normalized records, not France specifics):
- `review_records(records, *, model, client) -> list[Suggestion]`. Pure over an
  injected client (a thin Ollama HTTP wrapper, mirroring how retrieval/publish
  inject their clients) so tests run without a real model.
- Per record, prompt the model with the source text and the parsed fields and
  ask **only** for discrepancies, as JSON. The prompt hardening (learned from the
  3B false-positive run) instructs the model to: flag only what is **literally in
  the source text** but missing/wrong in the parsed fields; treat an **absent
  brand/contact as normal** (most aerodromes name none — never a discrepancy);
  never treat operator/aeroclub names, `CIV`/`MIL`, or `PPR` as a fuel brand;
  never report a value the parsed fields **already contain**; and never invent a
  grade absent from the text.
- `Suggestion` shape: `{icao, kind, detail, confidence}` where `kind` ∈ a closed
  set (`missing_grade`, `wrong_state`, `other`) so findings aggregate into
  patterns. Malformed model output for a record is dropped with a logged warning
  (advisory ⇒ best-effort). **Scope note:** `missed_brand`/`missed_contact` were
  deliberately removed after two real runs — they produced essentially only false
  positives (the model flagged correct null brands/contacts and invented brands
  from operator/aeroclub names), and a manual oracle audit confirmed the
  deterministic brand/contact detection was already correct. Brand/contact
  quality is owned by the deterministic rules, not the LLM pass; the LLM focuses
  where it adds signal: grades and fuel state.
- Determinism knobs: model pinned, `temperature=0`, fixed seed where the backend
  supports it. Even so, treated as non-deterministic and never load-bearing.

**Scope.** By default the pass reviews **all** records for the enabled providers
(the most thorough option; the intended first use is a full audit). CPU-only
inference over ~420 records is the cost, so the pass runs only in its own
non-blocking job / opt-in local mode, never in the publish path. A future
`--llm-review-subset` could narrow to the lossy set (unknown/nil + suspicious
`available`) if run time becomes a problem, but all-records is the default.

**Model.** Pinned to an instruction-tuned model reliable at structured JSON and
at *not* inventing findings — default `qwen3:8b` (configurable via `--llm-model`).
It was chosen by comparing candidate CI-runnable models on how often they falsely
flag a correct record (lower is better — this is the pass's real risk) versus how
many genuine extraction gaps they catch:

| Model | False-alarm rate | Bug recall | Note |
|---|---|---|---|
| gemma3:4b | 2% | 0% | silent — catches nothing (useless) |
| phi4-mini | 15% | 8% | near-silent |
| **qwen3:8b** | **23%** | **83%** | best FP/recall balance — chosen |
| qwen2.5:7b-instruct | 40% | 67% | earlier default; qwen3 dominates it |
| llama3.1:8b | 100% | 83% | flags everything (useless) |

`qwen3:8b` is a reasoning model, hence slower (its "thinking" is *why* its
false-alarm rate and recall are both better). It fits a ~12 GB GPU; on the
CPU-only CI runner it is slow, which is acceptable because the pass runs in a
separate non-blocking workflow off the publish path. A smaller model can be
substituted via `--llm-model` where speed matters more than recall. Even so, at
~23% false alarms the pass is a triage aid, never authoritative (ADR-0003).

**Output.** Suggestions are written to a `suggestions.json` artifact and
summarized in the processing report, **grouped by `kind`** so a maintainer sees
patterns (e.g. "12 × missing_grade") not 273 one-offs. A pattern is a
parser-rule bug: the fix is a new deterministic rule in `grades.py` /
`conditions.py` plus a regression fixture, applied by a human/agent in a normal
spec-tracked change. The suggestion is the pointer; the rule is the fix.

**Where it runs.** A separate workflow `.github/workflows/llm-review.yml`:
checkout → install Ollama (`curl -fsSL https://ollama.com/install.sh | bash`) →
pull the pinned model → run the pipeline in review mode that builds records and
calls `review_records` → upload `suggestions.json` + report as artifacts. It
never publishes a Release or deploys Pages.

Triggers:
- **`workflow_run`** after `pipeline.yml` completes, gated on
  `conclusion == 'success'`, so every *published* cycle is automatically QA'd.
  Because this fires after the publish run finished, the review resolves the
  cycle itself via `airac.current_cycle()` (the in-force cycle on any day, not
  only on an exact AIRAC boundary — avoids a midnight-rollover race).
- **`workflow_dispatch`** for on-demand runs (optional explicit cycle input).

Non-blocking guarantee (ADR-0003): the review is a *downstream* workflow, so it
runs after publishing is already done; its success, failure, or output cannot
affect the publish run, the published dataset, or the guard. Locally, an opt-in
`--llm-review` flag on `run_pipeline.py` does the same against a local Ollama.
Inference is local only; no chart data or secrets leave the runner.

## Testing Strategy

- **Parser unit tests** run against a fixture set of real French AVT blocks
  (regenerated into `pipeline/tests/fixtures/lf/`), covering: 100LL / UL91 /
  100/130 normalization, generic-AVGAS fallback (bare AVGAS → generic grade,
  specific grade preferred), Jet-A1 boolean, positional
  NIL, MIL/CIV split, table-layout fallback (LFOH), value-after-lubricants
  (LFBG), and unparseable military charts (LFRJ/LFRL → `unknown`).
- **Schema validation tests**: conforming records pass; malformed records are
  rejected (R5.4).
- **Join tests**: matched ICAO gets coordinates; unmatched AVGAS aerodrome is
  dropped and reported (R6.3).
- **Guard tests**: below-floor and large-relative-drop inputs abort publish;
  healthy input passes (R7.4).
- **AIRAC gate tests**: `is_airac_today()` true only on calendar dates.
- **Front-end**: manual smoke test (map renders, cycle switch reloads data,
  grade filter, search, popup content, freshness/disclaimer/attribution). No
  heavy test harness for the no-build front-end in v1.

## Requirements Traceability (highlights)

- R1 map/markers/cluster/error → Front-end.
- R2 fuel detail popup → Front-end + schema `properties`.
- R3 search/filter → Front-end top bar.
- R4 France parsing → `providers/lf/*` + `retrieval`.
- R5 modular contract → `interface.py`, `schema.py`, provider registry.
- R6 OpenAIP coordinates → `coordinates.py`.
- R7 AIRAC-gated no-commit pipeline, guard, report → `airac`, `validate`,
  `publish`, `report`, workflow.
- R8 build-and-deploy hosting → workflow + `web/` + manifest.
- R9 freshness / cycle selector / disclaimer / attribution → Front-end.
