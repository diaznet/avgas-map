# AVGAS-Map pipeline

The Python data pipeline: retrieve aerodrome charts, parse fuel info per country,
join coordinates from OpenAIP, validate/assemble a normalized GeoJSON dataset,
and publish it per AIRAC cycle.

For the quickstart (install, generate locally, preview the map) see the
[top-level README](../README.md#run-locally). This file covers the internals.

## Module map

```
avgasmap/
  schema.py          normalized dataset schema + validator (the contract)
  interface.py       CountryParser protocol + FuelRecord type
  retrieval.py       shared autorouter WebDAV fetch (bounded, retrying, polite)
  coordinates.py     OpenAIP fetch + ICAO coordinate join
  assemble.py        parsers -> AVGAS-only features -> validated dataset
  airac.py           AIRAC cycle date arithmetic + today-gate
  airac_cli.py       tiny CLI used by the CI gate (--today)
  validate.py        never-worse guard (floor + relative-drop)
  publish.py         GitHub Release asset + manifest generation
  report.py          processing report (job summary + artifact)
  pipeline.py        orchestration (compose all stages)
  providers/
    lf/              the France parser (VAC 10-AVT), keyed by ICAO prefix "lf"
run_pipeline.py      CLI entry point
```

The **normalized dataset is the contract** (`schema.py`): every parser's output
and the published GeoJSON conform to it. Country-specific quirks stay inside the
provider; retrieval, the OpenAIP join, assembly, guard, and publish are shared.

## Credentials

The pipeline reads credentials **only** from environment variables
`AUTOROUTER_USER` / `AUTOROUTER_PASS` — it is OS-agnostic and knows nothing about
where they come from.

- **CI:** GitHub Actions secrets, injected as env vars for the run.
- **Local:** export them in your shell, or copy `.env.example` to a `.env` at the
  **repository root** and fill them in. `run_pipeline.py` loads that `.env` if
  `python-dotenv` is installed and the file exists. The `.env` is gitignored and
  must never be committed; it is never used in CI.
- **Agents must never read `.env`.** A repo invariant (see [AGENTS.md](../AGENTS.md))
  forbids any AI agent from reading, searching, or printing `.env`/secret files;
  only `.env.example` is allowed. It's enforced by a `PreToolUse` hook
  (`.kiro/hooks/`). Humans edit `.env` normally.
- Only real (non-`--dry-run`) France runs need credentials. OpenAIP and OSM tiles
  need none.

## CLI

```
python run_pipeline.py [--country CC ...] [--cycle YYNN] [--local] [--dry-run]
                       [--override-guard] [--workspace DIR]
```

- `--dry-run` — build from bundled fixtures; no network, no publish.
- `--local` — write `web/data/dataset-<cycle>.geojson` + `index.json` instead of
  publishing a Release (for local preview).
- `--cycle YYNN` — force a cycle, bypassing the today-is-AIRAC gate.
- `--override-guard` — bypass the relative-drop guard (the absolute floor is
  always enforced).
- `--workspace DIR` — where intermediate files and `report.md` are written
  (default: a temp dir; CI points this somewhere the artifact upload can find).

Exit code is non-zero only when a run fails the guard, so CI aborts the deploy
and the previously deployed site stays live.

## AIRAC dates

Computed, not stored (`airac.py`). Cycles are a fixed 28-day period anchored to
cycle `2001` = 2020-01-02; `effective_date(cycle)` and `cycle_for_date(date)` are
pure arithmetic. The cycle id is `YYNN` (year's last two digits + 1-based ordinal
within the year). No calendar file to maintain. Verified in tests against known
dates (e.g. 2505 = 2025-05-15).

## The never-worse guard

Before publishing, `validate.check()` compares the new feature count against the
most recent successfully published count:

- **Absolute floor** (`DEFAULT_FLOOR = 200`) — always enforced; catches total
  breakage (e.g. a failed fetch producing near-zero features).
- **Relative drop** (`DEFAULT_MAX_DROP = 0.20`) — aborts on a >20% drop vs. the
  previous publish; catches partial breakage. Bypass with `--override-guard`
  for a legitimately large change (the floor still applies).

Tune the constants in `validate.py`. France alone yields ~296 AVGAS aerodromes,
so the 200 floor leaves headroom.

## OpenAIP endpoint

Configured in `coordinates.py`:

```
OPENAIP_EXPORT_BASE   = "https://storage.openaip.net/openaip-system-exports/"
OPENAIP_KEY_TEMPLATE  = "{country}_apt.geojson"   # e.g. fr_apt.geojson
```

These are the single place to update if OpenAIP relocates its export again
(it has before). The join is by exact ICAO code — no fuzzy matching (see
[ADR-0002](../docs/adr/0002-icao-is-sole-identity-no-fuzzy-match.md)).

## Tests

```bash
# from pipeline/, with the venv active
python -m pytest
```

The France parser is tested against fixtures in `tests/fixtures/lf/cases.py`
modelling the documented spike edge cases (grades, positional NIL, table-layout
fallback, unparseable military charts, etc.). Network and GitHub are mocked; the
whole suite runs offline.

> Note: the fixtures are hand-authored from the spike's documented examples
> (the spike's cached output was removed). A real-PDF run
> (`python run_pipeline.py --local` with credentials) is the way to confirm the
> parser against live `pymupdf4llm` output.

## Adding a country

Providers are named by their **lowercased ICAO prefix** (see
[CONTEXT.md](../CONTEXT.md) "Country parser"), e.g. `lf` for France, `ed` for
Germany — not the ISO country code.

Add a `providers/<icao_prefix>/` package implementing the `CountryParser`
protocol:

- `code` — the lowercased ICAO prefix (the package name), e.g. `"ed"`.
- `icao_pattern` — regex an ICAO must match, e.g. `r"^ED[A-Z]{2}$"`.
- `openaip_iso` — ISO country code(s) for the OpenAIP fetch, e.g. `["de"]`
  (this is the only place the ISO code is used).
- `chart_paths(country_dir)` and `parse(icao, chart_path) → FuelRecord`.

Register it in `providers/__init__.py` (keyed by `code`) and add its fuel-source
attribution in `assemble.FUEL_ATTRIBUTION` (keyed by `code`). Retrieval, the
OpenAIP join, assembly, publishing, and the front-end need no changes. The
dataset's `country` property and attribution key are the uppercased ICAO prefix
(e.g. `ED`).
