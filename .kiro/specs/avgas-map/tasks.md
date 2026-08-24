# Implementation Plan

Incremental, test-backed build order. Each task builds on the previous ones and
ends in working, verifiable code. Terms follow [`CONTEXT.md`](../../../CONTEXT.md);
decisions follow `docs/adr/`. Domain-specific rules are in
[`vac-avt-findings.md`](vac-avt-findings.md).

The contract is the normalized dataset: build it and its validation first
(tasks 1–3) before anything that produces or consumes it.

- [ ] 1. Scaffold the pipeline package and pin dependencies
  - Create `pipeline/` package layout (`avgasmap/`, `tests/`, `data/`,
    `run_pipeline.py`, `requirements.txt`, `README.md`) per the design.
  - Pin `pymupdf4llm`, `pymupdf`, `webdavclient3`, `python-dotenv`, and a test
    runner (`pytest`) in `requirements.txt`.
  - Add `.env.example` (AUTOROUTER_USER/PASS template); gitignore `pipeline/.env`
    and `web/data/`. The entry point loads `.env` if present (optional), then
    reads credentials from env vars only.
  - Add a stub `run_pipeline.py` CLI that parses args (`--country`, `--cycle`,
    `--dry-run`) and exits cleanly.
  - Verify: `pip install -r requirements.txt` succeeds and `python run_pipeline.py --help` runs.
  - _Requirements: 5, 7_

- [ ] 2. Define the normalized schema and its validator
  - Implement `schema.py`: the `Feature` `properties` shape, the FeatureCollection
    `metadata` (incl. `schema_version`, `effective_date`, `airac_cycle`,
    `attribution`, `feature_count`), and a `validate_feature`/`validate_dataset`
    that rejects non-conforming records.
  - Encode the closed vocabularies: `avgas_grades` ⊆ {`100LL`,`UL91`,`100/130`};
    `fuel_state` ∈ {`available`,`nil`,`unknown`}; the closed `conditions` shape
    (booleans + `payment`/`brand`/`phone`); `source_text`; `amdt`.
  - Write tests: conforming feature passes; each malformed variant is rejected.
  - _Requirements: 2, 4.3, 4.4, 5.4_ (ADR-0002 for ICAO identity)

- [ ] 3. Define the CountryParser interface and provider registry
  - Implement `interface.py`: `FuelRecord` TypedDict and `CountryParser` protocol
    (`code` = lowercased ICAO prefix, `icao_pattern`, `openaip_iso`,
    `chart_paths`, `parse`), producing ICAO-keyed fuel records with no
    coordinates and no retrieval.
  - Implement `providers/__init__.py` as a registry of enabled country parsers.
  - Write tests: a fake in-memory parser registers and yields schema-valid records.
  - _Requirements: 5.1, 5.2, 5.3_

- [ ] 4. Build the `lf` (France) AVT extraction (fixture-driven, no network)
- [ ] 4.1 Set up the lf fixture set
  - Add representative real AVT blocks under `tests/fixtures/lf/` covering:
    100LL, UL91, 100/130, generic-AVGAS-with-specific, positional NIL,
    fuel-but-no-AVGAS, MIL/CIV split, table-layout (LFOH), value-after-lubricants
    (LFBG), and unparseable military (LFRJ/LFRL).
  - _Requirements: 4_
- [ ] 4.2 Implement AVT anchoring and table fallback (`providers/lf/avt.py`)
  - Convert VAC PDF→markdown (`pymupdf4llm`); anchor `10 - AVT` .. `11 - RFFS`;
    apply the fallback scan when the anchor is empty/table-rendered; capture the
    full item-10 block; extract `AMDT NN/YY`.
  - Tests against fixtures incl. the LFOH table and LFBG lubricants cases.
  - _Requirements: 4.2, 4.6, 4.7, 4.8_
- [ ] 4.3 Implement grade + fuel-state classification (`providers/lf/grades.py`)
  - Normalize to the closed AVGAS vocabulary; drop generic `AVGAS` when a
    specific grade is present; exclude JET A1 / military F-grades / lubricants;
    detect Jet A-1 as a secondary boolean; read NIL positionally; classify
    `available`/`nil`/`unknown` deterministically (no LLM).
  - Tests cover every fixture's expected grades and state.
  - _Requirements: 4.3, 4.4, 4.9, 2.3_
- [ ] 4.4 Implement condition-flag detection (`providers/lf/conditions.py`)
  - Detect the closed `conditions` shape (booleans + payment/brand/phone);
    retain the full block as `source_text`.
  - Tests assert flags and that nothing is lost to `source_text`.
  - _Requirements: 2.5, 4.5_
- [ ] 4.5 Assemble `LfParser` (`providers/lf/__init__.py`; `code="lf"`, `openaip_iso=["fr"]`)
  - Implement `chart_paths` (filter `^LF[A-Z]{2}`, require a `VFR/` VAC, skip the
    rest) and `parse` (compose 4.2–4.4 into a schema-valid `FuelRecord`).
  - Tests: end-to-end fixture → validated `FuelRecord`; military charts → `unknown`.
  - _Requirements: 4.1, 4.2, 4.7, 5.4_

- [ ] 5. Implement shared autorouter WebDAV retrieval (`retrieval.py`)
  - Fetch chart PDFs from `https://www.autorouter.aero/webdav` (HTTP Basic from
    `AUTOROUTER_USER`/`AUTOROUTER_PASS` env vars) into a workspace dir; expose
    the local paths the parser's `chart_paths` expects.
  - Bounded concurrency (configurable, default ~5–8), retry with backoff,
    descriptive User-Agent; fetch-fresh each run (no cross-run cache); never log
    secrets.
  - Tests: retry/backoff and concurrency-cap logic against a mock WebDAV server;
    missing creds → clear error, no fetch.
  - _Requirements: 4.1, 5.1, 7.7_

- [ ] 6. Implement OpenAIP coordinate join (`coordinates.py`)
  - Fetch `{OPENAIP_EXPORT_BASE}{country}_apt.geojson` (default base
    `https://storage.openaip.net/openaip-system-exports/`, key `fr_apt.geojson`),
    build an ICAO→[lon,lat]+name index, join by exact ICAO.
  - AVGAS aerodrome with no exact match → drop + record (never a null/wrong pin);
    base URL and key template are config values.
  - Tests: matched ICAO gets coords; unmatched AVGAS aerodrome dropped+reported;
    endpoint override via config.
  - _Requirements: 6.1, 6.2, 6.3_ (ADR-0002)

- [ ] 7. Implement dataset assembly (`assemble.py`)
  - Run enabled parsers, keep `available` records only, join coordinates, build
    the FeatureCollection + metadata (schema_version, cycle, effective_date,
    attribution incl. SIA + OpenAIP), validate every feature; reject a
    non-conforming provider's output.
  - Tests: mixed records → AVGAS-only features; attribution + schema_version
    present; non-conforming provider excluded.
  - _Requirements: 1.2, 2.3, 5.4, 5.6, 6.4, 9.4_

- [ ] 8. Implement AIRAC date computation + gating (`airac.py`)
  - Compute cycles arithmetically from the fixed epoch (cycle `2001` =
    `2020-01-02`, +28 days per cycle): `effective_date(cycle_id)`,
    `cycle_for_date(date)`, `is_airac_today()`, `current_cycle()`. No data file.
  - Tests: pin the epoch and several known effective dates against the public
    AIRAC schedule; verify `YYNN` id formatting and the today-gate.
  - _Requirements: 7.2_

- [ ] 9. Implement the never-worse guard (`validate.py`)
  - Absolute floor AND relative-drop check against the most recent successfully
    published dataset's feature count (cycle-agnostic); on failure abort publish,
    leave prior latest intact, exit non-zero; thresholds are configurable
    constants with a documented manual override.
  - Tests: below-floor aborts; large relative drop aborts; healthy passes;
    re-run of same cycle compares against last published.
  - _Requirements: 7.4, 7.5_

- [ ] 10. Implement Release publishing + manifest (`publish.py`)
  - Create/replace Release `airac-<YYNN>` with asset `dataset.geojson` using
    `GITHUB_TOKEN`; regenerate `index.json` by listing existing Releases + the
    new one; set `latest` = newest successfully published cycle; echo each
    cycle's `schema_version` and `effective_date`. Commit nothing to the repo.
  - Tests (mock GitHub API): asset uploaded under the right tag; manifest lists
    all cycles and marks latest; failure leaves prior state untouched.
  - _Requirements: 7.3, 7.5, 8.2_ (ADR-0001)

- [ ] 11. Implement the processing report (`report.py`)
  - Produce a human-readable report (counts + per-aerodrome skips: no-VAC,
    unparseable, unmatched-coords); write to a workspace file and to
    `$GITHUB_STEP_SUMMARY`; never commit it.
  - Tests: report includes each skip category with reasons.
  - _Requirements: 4.7, 6.3, 7.6_

- [ ] 12. Wire the pipeline entry point (`run_pipeline.py`)
  - Compose: AIRAC gate → retrieval → parse → OpenAIP join → assemble → guard →
    publish + manifest → report. Support `workflow_dispatch`-style manual run and
    a `--dry-run` that skips publish.
  - Add `--local`: run the full pipeline but write `dataset.geojson` + a local
    `index.json` (cycle URLs pointing at the sibling local file) into `web/data/`
    instead of publishing a Release; `--cycle <YYNN>` bypasses the AIRAC gate;
    combinable with `--dry-run` for a fully offline fixture build.
  - Add stage progress logging (`logconfig.py`, stderr, INFO/`-v` DEBUG) so a
    long run is observable: retrieval download progress, OpenAIP fetch, assembly
    counts, guard decision, outcome. (Requirement 7.8.)
  - Tests: dry-run over fixtures yields a valid in-memory dataset without network
    or publish; `--local` writes a `web/data/index.json` + dataset and no Release.
  - _Requirements: 5.5, 7.1, 7.2, 7.3, 7.4, 8.5_

- [ ] 13. Build the static front-end (`web/`)
- [ ] 13.1 Map shell + manifest load + cycle dropdown
  - `index.html`/`app.js`/`style.css` with Leaflet + OSM tiles + markercluster
    (pinned in `vendor/`).
  - Implement data-source resolution: try local `data/index.json` first, fall
    back to the published manifest; use the resolved manifest's per-cycle URLs.
  - Populate the AIRAC dropdown, default to `latest`, fetch that cycle's dataset;
    render tolerant of the cycle's `schema_version` (missing fields → unknown).
  - Full interactive map immediately; dataset-load failure shows an error, not a
    blank map. Initial view fits the dataset.
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 8.1, 8.2, 8.3, 8.5, 9.2_
- [ ] 13.2 AVGAS markers + detail popup
  - Marker per feature (AVGAS-only); popup with name+ICAO, grade badges, Jet A-1
    secondary line, condition-flag labels, AMDT, and `source_text` in a
    collapsible `<details>`.
  - _Requirements: 1.2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_
- [ ] 13.3 Search + grade filter
  - Search by ICAO or name (focus match; no-match and technical-failure both show
    the standard "no aerodrome found"); grade-filter checkboxes (100LL/UL91/100/130).
  - _Requirements: 3.1, 3.2, 3.3_
- [ ] 13.4 Freshness + disclaimer + attribution chrome
  - Footer/info panel: effective date + AIRAC cycle shown only when both known;
    "not an official source" disclaimer; SIA + OpenAIP attribution.
  - _Requirements: 9.1, 9.3, 9.4, 6.4_

- [ ] 14. Add the GitHub Actions workflow (`.github/workflows/pipeline.yml`)
  - Daily `schedule` + `workflow_dispatch`; early-exit unless AIRAC date (or
    manual). Inject `AUTOROUTER_USER`/`AUTOROUTER_PASS` secrets (never echoed);
    use `GITHUB_TOKEN` for Release + Pages.
  - Steps: run pipeline → on success publish Release + regenerate manifest →
    build-and-deploy `web/` + manifest to Pages via workflow artifact (no repo
    commits) → emit report to job summary + upload artifact.
  - Verify: manual dispatch produces a Release asset and a deployed site; a
    forced guard failure aborts deploy and leaves the prior site live.
  - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 8.1, 8.3, 8.4_

- [ ] 15. Verify the local end-to-end path
  - Confirm `run_pipeline.py --local` (with `--dry-run` for offline, or real creds
    for live France) writes `web/data/`, then serve `web/` via
    `python -m http.server` and load the map in a browser from `http://localhost`.
  - Confirm the front-end renders the locally-generated dataset (markers, popup,
    filter, search, freshness/disclaimer/attribution) with no Release involved.
  - Ensure `web/data/` is gitignored.
  - _Requirements: 8.5_

- [ ] 16. Write the top-level `README.md` (canonical: overview + quickstart)
  - Project overview, live map link (placeholder until deployed), the
    "not an official source" flight-safety disclaimer, and SIA + OpenAIP
    attribution.
  - Quickstart (canonical home): clone, install pipeline deps, generate locally
    (`--local`/`--dry-run`), serve `web/`, view the map. Link out to
    `pipeline/README.md` for internals and to the spec/`CONTEXT.md`/ADRs.
  - _Requirements: 8.5, 9.3, 9.4_

- [ ] 17. Write `pipeline/README.md` (canonical: pipeline-dev internals)
  - Credential setup: `AUTOROUTER_USER`/`AUTOROUTER_PASS` via shell env or an
    optional gitignored `.env` (from `.env.example`), never committed, never in
    CI; the AIRAC date arithmetic; OpenAIP endpoint config; running the fixture
    tests; guard thresholds + manual override. Link back to the top-level README
    quickstart (no duplicated steps).
  - _Requirements: 5, 7_

- [ ] 18. Add the secrets-guard hook (`.kiro/hooks/`)
  - Add a Kiro `PreToolUse` hook (`block-env-reads.json` → `block_env_reads.py`)
    that blocks any read/search tool targeting a `.env` file (exit 2), allowing
    `.env.example`. Document the "agents never read secrets" invariant in
    `AGENTS.md` and reference it from `pipeline/README.md`.
  - Verify: a `.env`-targeted read/grep is blocked; `.env.example` and normal
    files pass.

- [ ] 19. Add generic-AVGAS fallback grade (Option B)
  - Extend the closed vocabulary to `{100LL, UL91, 100/130, AVGAS}` in
    `schema.py`; `AVGAS` is the generic value meaning "AVGAS available, grade
    unspecified".
  - In `providers/lf/grades.py`, `find_avgas_grades` returns `["AVGAS"]` when a
    bare AVGAS token is present but no specific grade matched, and drops the
    generic value when a specific grade is present (specific wins). Fold "91 UL"
    into the UL91 pattern.
  - Update `CONTEXT.md` glossary and the spec (R2.2, R4.3a, design).
  - Tests: bare AVGAS → `available` + `["AVGAS"]`; specific-plus-AVGAS → specific
    only; NIL still `nil`; JET A1 alone still no grade; schema accepts `AVGAS`.
  - _Requirements: 2.2, 4.3, 4.3a_

- [ ] 20. Add `--keep-intermediates` debug option
  - Add the `--keep-intermediates` CLI flag (default off) and a matching
    `RunConfig` field; thread it to the live parse loop.
  - In `LfParser.parse`, accept an optional markdown-dump directory; when set,
    write the converted markdown to `<workspace>/md/<code>/<ICAO>.md` before
    parsing. Add a per-chart DEBUG log line so parsing is observable with `-v`.
  - Off by default writes nothing extra; never committed, never shipped with the
    site (workspace-only). Keep `parse_markdown` pure (no I/O).
  - Tests: with the flag, markdown files are written per parsed chart under
    `md/<code>/`; without it, no `md/` dir is created; `parse_markdown` unchanged.
  - _Requirements: 7.8, 7.9_

- [ ] 21. Fail fast on missing/broken conversion dependencies
  - Add `check_dependencies()` to the `lf` provider (import-probe `pymupdf` +
    `pymupdf4llm`), raising a clear error naming the failing import.
  - In `pipeline.run`, for a live (non-dry-run) run, call each enabled provider's
    `check_dependencies()` before retrieval; on failure abort with an actionable
    message including `sys.executable`, and return a failed outcome (no empty
    dataset, no silent guard trip). Add the optional hook to the CountryParser
    protocol (providers without conversion deps may omit it).
  - Keep the per-chart conversion failure logged, not swallowed (already done).
  - Tests: a provider whose dependency import fails aborts the live run with the
    dependency named; dry-run is unaffected; a healthy provider proceeds.
  - _Requirements: 7.10, 7.11_

- [ ] 22. UX feedback batch: provider detection, contacts, colours, links, filter
- [ ] 22.1 Bump SCHEMA_VERSION and extend the conditions shape
  - Add `website` and `email` (string|null) to the closed `conditions` shape in
    `schema.py`; bump `SCHEMA_VERSION`. Keep additive/back-compatible.
  - Tests: records with/without the new fields validate; old-shape records still
    accepted where applicable.
  - _Requirements: 2.10, 4.5, 4.5b_
- [ ] 22.2 Provider (brand) detection incl. card-implied brand (`conditions.py`)
  - Detect brand from a directly-named brand OR an accepted brand fuel card
    (`carte TOTAL`⇒TOTAL, `Sterling`/`carte BP`⇒AIR BP, `carte SHELL`⇒SHELL …),
    preferring a named brand. Fixtures for card-only cases (e.g. LFPZ Sterling).
  - Tests: named-brand, card-only, and named-wins-over-card cases.
  - _Requirements: 2.9, 4.5a_
- [ ] 22.3 Contact extraction: website + email (`conditions.py`)
  - Extract a website URL (`http(s)://…`, incl. shortened `totalenergi.es/…`)
    and an email; normalise phone. Tests incl. LFPN booking URL.
  - _Requirements: 2.10, 4.5b_
- [ ] 22.4 source_text artifact cleanup + FR/EN preservation (`providers/lf`)
  - Strip stray/unbalanced `_` italic markers from `source_text` without
    changing wording; keep FR and EN renderings separable (leading-`_` = EN).
  - Tests: hanging-underscore fixture cleaned; FR/EN split recoverable.
  - _Requirements: 2.11, 4.5c_
- [ ] 22.5 Front-end: provider filter control (`web/`)
  - Topbar filter-group populated from brands present in the loaded cycle;
    filter markers by `conditions.brand` with the grade filter. No-brand markers
    shown unless a brand filter excludes them (define behaviour in render()).
  - _Requirements: 3.4_
- [ ] 22.6 Front-end: AVGAS red / Jet A-1 black (`style.css`, `app.js`)
  - Restyle grade badges red; Jet A-1 indicator black. (R2.8)
- [ ] 22.7 Front-end: clickable phone / website / email (`app.js`)
  - Render `tel:`, `http(s)` anchor (rel="noopener noreferrer" target=_blank),
    `mailto:`. escapeHtml-safe. (R2.10)
- [ ] 22.8 Front-end: FR/EN source-text toggle (`app.js`, `style.css`)
  - Small per-popup FR/EN toggle over the split verbatim text. (R2.11)
- [ ] 22.9 Verify: pytest + venv regenerate + browser smoke check
  - All tests green; regenerate dataset with venv; serve web/ and confirm
    filter/colours/links/toggle render.

- [ ] 23. Add `--reparse-only` (rebuild from cached charts, skip retrieval)
  - Add the `--reparse-only` CLI flag + `RunConfig.reparse_only`; require
    `--workspace`, reject with `--dry-run`.
  - In `_collect_records_live`, when reparse_only: skip `retrieval.retrieve_*`,
    enumerate charts via `chart_paths(<workspace>/pdf/<code>)`, parse them;
    `no_pdf`/errors empty. If no charts found, log a clear error.
  - Coordinates + guard still run. Tests: reparse over a temp workspace with
    fixture PDFs rebuilds a dataset without retrieval; empty workspace surfaces
    the no-charts condition; `--reparse-only --dry-run` is rejected.
  - _Requirements: 7.12_

- [ ] 24. Follow-up fixes: whole-word brand match + GitHub link
  - Brand detection matches brands as whole words (`\b`), not substrings, so
    `aviation` no longer reads as the `AVIA` brand (LFGB false positive). Applied
    to the live dataset via `--reparse-only` (AVIA 10 → 1, only LFSM genuine).
  - Add a "Source on GitHub" link to the site footer (R9.5).
  - Tests: `aviation` yields no brand; a genuine `AVIA` station still detected.
  - _Requirements: 2.9, 4.5a, 9.5_

- [ ] 25. Advisory LLM extraction-QA pass (report-only, ADR-0003)
- [ ] 25.1 Suggestion model + Ollama client seam (`avgasmap/llm_review.py`)
  - Define the `Suggestion` shape `{icao, kind, detail, confidence}` with a
    closed `kind` set (`missing_grade`, `wrong_state`, `missed_brand`,
    `missed_contact`, `other`). Define a minimal `LlmClient` protocol (one
    `generate(prompt) -> str`) so tests inject a fake; provide a thin Ollama HTTP
    client impl. Pin model + temperature 0.
  - Tests: Suggestion validation; client protocol satisfied by the fake.
  - _Requirements: 4.10_
- [ ] 25.2 `review_records` + prompt (never invents grades)
  - `review_records(records, *, model, client)` prompts per record with
    source_text + parsed fields, asks for JSON discrepancies only, and instructs
    the model to flag only grades present in the text (never invent one). Parse
    the JSON into `Suggestion`s; drop malformed output with a logged warning.
  - Default scope = ALL records for enabled providers. Model pinned to
    `qwen2.5:3b-instruct` (configurable).
  - Tests (fake client): a planted "text says UL91, grades empty" record yields a
    `missing_grade` suggestion; a clean record yields none; malformed model
    output is dropped, not fatal; the pass never mutates the input records.
  - _Requirements: 4.10_
- [ ] 25.3 Report integration + `suggestions.json` artifact
  - Group suggestions by `kind` in the processing report (pattern counts, not
    one-offs); write `suggestions.json` to the workspace. Never touch the
    dataset, guard, or exit code.
  - Tests: report shows grouped counts; artifact written; dataset/guard unchanged.
  - _Requirements: 4.10, 7.6_
- [ ] 25.4 CLI opt-in + separate workflow
  - Add `--llm-review` to `run_pipeline.py` (opt-in, off by default, reviews all
    records; not part of a normal/publish run). Add
    `.github/workflows/llm-review.yml`: workflow_dispatch (+ optional schedule),
    install Ollama, pull pinned model, run review mode, upload
    `suggestions.json` + report; NEVER publish a Release or deploy Pages.
  - Verify: `--help` shows the flags; the workflow has no publish/deploy steps.
  - _Requirements: 4.10_

- [ ] 25.5 Harden the QA prompt + bump default model (from first-run findings)
  - First 3B run: 340 suggestions, ~all false positives (null brand/contact
    flagged as gaps, brands invented from aeroclub/CIV/PPR text, values we
    already parsed re-flagged). Fix:
  - Rewrite the prompt: flag only what is literally in the source text but
    missing/wrong in PARSED; absent brand/contact is normal, not a discrepancy;
    operator/aeroclub names, CIV/MIL, PPR are NOT brands; never re-report a value
    PARSED already has.
  - Bump `DEFAULT_MODEL` to `qwen2.5:7b-instruct` (better instruction-following;
    fits a ~12 GB GPU). CI workflow passes a smaller model explicitly.
  - Tests: a record whose PARSED already has the brand yields no missed_brand; a
    null brand with no brand in text yields nothing; genuine missing_grade still
    caught.
  - _Requirements: 4.10_

- [ ] 26. Extend source_text cleanup: strip ** and control chars (audit finding)
  - Manual oracle audit (all 273 records) found 6 with leftover `**` bold markers
    and/or `\u0007` control chars (LFBY, LFMI, LFMY, LFTF, LFXB, LFYR); grades and
    states were all correct.
  - Extend `clean_source_text` to strip `**` and stray control characters
    (keep balanced `_italic_`), without altering wording.
  - Tests: a record with `**`/bell is cleaned; balanced italics preserved.
  - _Requirements: 4.5c_

- [ ] 27. Narrow LLM QA kinds to missing_grade + wrong_state (from run findings)
  - Two runs of missed_brand/missed_contact were ~all false positives; the manual
    audit confirmed deterministic brand/contact detection is already correct.
  - Drop `missed_brand`/`missed_contact` from `SUGGESTION_KINDS`; keep
    `missing_grade`, `wrong_state`, `other`. Update the prompt to ask only about
    grades and fuel state.
  - Tests: kinds set is the narrowed set; a missing_grade case still works.
  - _Requirements: 4.10_

- [ ] 28. Adopt qwen3:8b as the QA default
  - Compared CI-runnable models on false-alarm rate vs. bug-catch recall; qwen3:8b
    (23% FP / 83% recall) had the best balance and dominated the earlier
    qwen2.5:7b default (40% / 67%). See the model comparison table in design.md.
  - Set `DEFAULT_MODEL = "qwen3:8b"`; update CLI help + llm-review.yml default.
  - The QA workflow stays a separate non-blocking job (no publish/deploy).
  - Tests: default-model assertion updated.
  - _Requirements: 4.10_

- [ ] 29. Auto-run LLM QA after each successful publish (non-blocking)
  - Add a `workflow_run` trigger to `llm-review.yml` on `pipeline.yml` completion,
    gated on `conclusion == 'success'`, so each published cycle is QA'd. Keep
    `workflow_dispatch` for on-demand.
  - On the auto path (no cycle input), resolve the cycle with
    `airac.current_cycle()` (in-force on any day; avoids the midnight-rollover
    race with an exact-AIRAC check). Make the dispatch `cycle` input optional.
  - Downstream workflow ⇒ inherently non-blocking: cannot affect the publish run,
    dataset, or guard (ADR-0003).
  - _Requirements: 4.10_

- [ ] 30. Serve datasets same-origin (fix Release-asset CORS)
  - Root cause: browser fetch of a GitHub Release asset URL from the Pages origin
    is CORS-blocked (302 to a storage host with no ACAO header). The published
    manifest's absolute Release URLs are unfetchable in-browser.
  - `publish.py`: add a way to fetch a Release asset's BYTES server-side
    (`download_asset(tag)` on the GitHub client). `publish_cycle` returns the
    published dataset bytes too.
  - `pipeline.py` publish path: write the current cycle's dataset to
    `web/data/dataset-<cycle>.geojson`; download every OTHER retained cycle's
    asset into `web/data/`; build the manifest with RELATIVE urls
    (`data/dataset-<cycle>.geojson`) and write it to `web/data/index.json` (and
    keep `web/index.json` as the published fallback, also relative).
  - `build_manifest`: emit relative `data/dataset-<cycle>.geojson` urls.
  - Front-end already resolves relative same-origin urls (no change needed).
  - Tests: manifest urls are relative; publish path writes all retained datasets
    into web/data/; mock client download_asset.
  - _Requirements: 8.2_
