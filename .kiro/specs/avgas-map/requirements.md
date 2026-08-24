# Requirements Document

## Introduction

AVGAS-Map is a free, statically-hosted web application that displays a map of aerodromes offering AVGAS refueling, aimed at pilots planning fuel stops. Its scope is the EASA area, using aerodrome charts available through the autorouter WebDAV.

Chart documents are always retrieved from the autorouter WebDAV; this retrieval is shared and fixed for every country. What is modular is only the per-country parsing: each country plugs in a parser module that reads that country's chart documents (VAC/AIP) and extracts fuel information keyed by ICAO code. All parsers emit the same normalized dataset that the map consumes. Aerodrome coordinates are not extracted by parsers; the pipeline joins each aerodrome's fuel data to coordinates from OpenAIP's public per-country airport exports by ICAO code. The first provider to be implemented is France, which parses the official VAC charts (cartes VAC) published by the SIA — specifically item `10 - AVT` (fuel/carburants) of each aerodrome's VAC; see [`vac-avt-findings.md`](vac-avt-findings.md) for the ingestion spike that grounds the France provider requirement.

Data is fetched and processed by a GitHub Actions pipeline that runs on AIRAC effective dates. The pipeline commits nothing to the repository: each AIRAC cycle's dataset is published as a GitHub Release asset, and the static site is deployed to GitHub Pages via build-and-deploy (from a workflow artifact, not a committed folder), at no hosting cost. The site offers an AIRAC-cycle selector (defaulting to the latest cycle) that loads the chosen cycle's dataset. Fuel pricing is explicitly out of scope.

## Glossary

- **AVGAS**: Aviation gasoline (e.g., 100LL, UL91) used by piston aircraft.
- **EASA area**: The set of European states whose aerodrome charts are available through the autorouter WebDAV; the overall scope of the map.
- **autorouter WebDAV**: The source repository of aerodrome charts, organized per country, from which providers retrieve documents.
- **OpenAIP**: Community aeronautical data platform publishing daily per-country airport exports (GeoJSON, keyed by ICAO) from the public S3 bucket `openaip-system-exports` at `https://storage.openaip.net/openaip-system-exports/`, keyed `<cc>_apt.geojson` (e.g. `fr_apt.geojson`), downloadable anonymously over HTTPS; the source of aerodrome coordinates. The base URL and key pattern are kept configurable (OpenAIP has changed the export location before). Its data must remain free to use and requires attribution.
- **eAIP**: Electronic Aeronautical Information Publication, the official aeronautical reference for a country.
- **SIA**: Service de l'Information Aeronautique, publisher of the French eAIP (source for the first provider).
- **VAC**: Visual Approach Chart (carte VAC), per-aerodrome PDF. In the French AIP, item `10 - AVT` carries the fuel field, bounded by item `11 - RFFS`.
- **AVT**: The VAC fuel field (avitaillement / carburants). Bilingual (French, then English in italics).
- **Fuel state**: One of `available` (an AVGAS grade is present), `nil` (AVT explicitly says NIL — no fuel), or `unknown` (AVT could not be parsed).
- **AIRAC cycle**: The 28-day international schedule on which aeronautical data is updated. Identified as `YYNN` (e.g. `2609` = the 9th cycle of 2026); Release tags use the form `airac-2609`.
- **GitHub Release asset / manifest**: Each AIRAC cycle's dataset is stored as a GeoJSON asset on a per-cycle GitHub Release; a generated `index.json` manifest lists available cycles and marks the latest, and is shipped with the static site.
- **Country parser (provider)**: A country-specific module that parses that country's chart documents (retrieved from the autorouter WebDAV) and outputs fuel information keyed by ICAO for the normalized dataset. It does not perform retrieval.
- **Normalized dataset**: The common GeoJSON format all providers produce, consumed by the map.

## Requirements

### Requirement 1: View AVGAS aerodromes on an interactive map

**User Story:** As a pilot planning a fuel stop, I want to see aerodromes offering AVGAS on an interactive map, so that I can identify where I can refuel.

#### Acceptance Criteria

1. WHEN the user opens the web application THEN the system SHALL display the full interactive map immediately, covering the EASA area, with an initial view that fits the aerodromes currently present in the dataset (the system SHALL NOT gate interactivity on a loading placeholder).
2. WHEN the map data has loaded THEN the system SHALL render a marker for each aerodrome known to offer AVGAS, and SHALL use the presence of an AVGAS grade as the sole criterion for placing a marker (aerodromes offering only non-AVGAS fuel such as Jet A-1 SHALL NOT be marked).
3. WHEN the user pans or zooms the map THEN the system SHALL keep aerodrome markers positioned at their correct geographic coordinates.
4. WHERE many markers are close together THEN the system SHALL cluster or otherwise manage markers so the map remains readable.
5. IF the aerodrome dataset fails to load THEN the system SHALL display a clear error message to the user rather than a blank map.

### Requirement 2: View aerodrome fuel details

**User Story:** As a pilot, I want to see details about an aerodrome's fuel availability when I select it, so that I can confirm it meets my needs.

#### Acceptance Criteria

1. WHEN the user selects an aerodrome marker THEN the system SHALL display the aerodrome name and ICAO code.
2. WHEN an aerodrome is selected THEN the system SHALL display which AVGAS fuel grades are available (from the closed vocabulary `100LL`, `UL91`, `100/130`, plus the generic `AVGAS` meaning "AVGAS available, grade unspecified") as recorded in the source data.
3. WHERE the source records Jet A-1 availability THEN the system MAY display Jet A-1 as a secondary detail, but Jet A-1 SHALL NOT affect whether an aerodrome is treated as offering AVGAS or shown on the map.
4. WHEN an aerodrome is selected THEN the system SHALL indicate its fuel state as one of `available`, `nil` (source explicitly states no fuel), or `unknown` (source could not be parsed), and SHALL visually distinguish these three states.
5. WHERE the source records fuel conditions (e.g., operating hours, on-request, prior permission, MIL/CIV split, payment method, brand, reserved for based aircraft) THEN the system SHALL surface those conditions as presence indicators AND SHALL display the original AVT free text verbatim (bilingual) so no detail is lost.
6. WHEN an aerodrome is selected THEN the system SHALL display the effective date / AIRAC cycle (e.g., `AMDT NN/YY`) of the source data so the pilot knows how current it is.
7. WHERE the source data does not clearly specify a detail THEN the system SHALL indicate the detail is unknown rather than implying it is unavailable.
8. WHEN displaying fuel grades THEN the system SHALL colour AVGAS grade indicators red and any Jet A-1 indicator black, following the international fuel-colour convention (AVGAS = red, Jet = black).
9. WHERE the source records a fuel-provider brand — whether named directly (e.g. `TOTAL`, `AIR BP`) or implied by an accepted brand fuel card (e.g. `carte TOTAL` ⇒ TOTAL, `Sterling`/`carte BP` ⇒ AIR BP) — THEN the system SHALL record and display that brand as the aerodrome's fuel provider.
10. WHERE the source records a phone number, a website URL, or an email address THEN the system SHALL surface each as a usable link (phone as `tel:`, website as an `http(s)` link, email as `mailto:`).
11. WHEN displaying the verbatim source text AND the source carries a separate English translation (an italic English block distinct from the French) THEN the system SHALL let the user switch between the French and English renderings (a per-popup FR/EN toggle); WHERE the source has no separate English translation (e.g. an inline-bilingual entry such as `Carburant / Fuel : …` with no distinct English block) THEN the system SHALL show the source text without a toggle rather than fabricate an English rendering. In all cases the system SHALL NOT display leftover markup artifacts (e.g. stray underscores from the source-to-text conversion).

### Requirement 3: Find and filter aerodromes

**User Story:** As a pilot, I want to search and filter aerodromes, so that I can quickly find a relevant fuel stop.

#### Acceptance Criteria

1. WHEN the user enters an ICAO code or aerodrome name in a search field THEN the system SHALL locate and focus the matching aerodrome on the map.
2. IF the search yields no match, OR the search cannot be completed due to a technical or data problem, THEN the system SHALL inform the user with the standard "no aerodrome found" message.
3. WHERE multiple AVGAS grades exist THEN the system SHALL allow the user to filter markers by fuel grade (e.g., show only aerodromes with UL91).
4. WHERE the dataset records fuel-provider brands THEN the system SHALL allow the user to filter markers by provider (e.g. show only TOTAL or AIR BP), with the available provider options derived from the data present in the loaded cycle.

### Requirement 4: First provider — France (VAC PDF parsing)

**User Story:** As the maintainer, I want the first country provider (France) to extract aerodrome fuel data from the official VAC charts, so that the map is populated from an authoritative source and the provider serves as the reference implementation of the common interface.

#### Acceptance Criteria

1. WHEN preparing the France provider's input THEN the system SHALL use the shared autorouter WebDAV retrieval to obtain the current French VAC PDFs for aerodromes matching `^LF[A-Z]{2}`, and SHALL skip non-French ICAOs and entries without a VAC PDF.
2. WHEN processing an aerodrome's VAC THEN the system SHALL extract the ICAO code, aerodrome name, and the fuel field bounded by item `10 - AVT` .. item `11 - RFFS`; the provider SHALL NOT be responsible for geographic coordinates (see Requirement 6).
3. WHEN extracting AVGAS grades THEN the system SHALL normalize wording to the closed vocabulary `100LL` (from `100 LL` / `100LL` / `100 LL-JET A1`), `UL91` (from `UL 91` / `UL91` / `91 UL`), and `100/130`, and SHALL exclude non-AVGAS grades (`JET A1`, military `F18` / `F34` / `F35`, lubricants `O###` / `H###`).
3a. WHERE the source mentions AVGAS but names no specific grade (a bare `AVGAS` token) THEN the system SHALL record the generic grade `AVGAS` so the aerodrome counts as offering AVGAS (`fuel_state = available`); WHERE a specific grade is also present, the specific grade takes precedence and the generic `AVGAS` is dropped.
4. WHEN determining fuel state THEN the system SHALL classify an aerodrome as `available` WHEN at least one AVGAS grade is present, as `nil` WHEN the AVT fuel value is explicitly NIL (read positionally against the fuel value and not the lubricants value), and as `unknown` WHEN the AVT field could not be located or parsed.
5. WHEN the AVT field carries conditions THEN the system SHALL capture presence flags (operating hours, on-request, prior permission, MIL/CIV split, payment/brand, self-service, reserved-for-based, phone, website, email) AND SHALL retain the full AVT block verbatim as free text; the system SHALL NOT be required to produce a structured schedule in v1.
5a. WHEN detecting the fuel-provider brand THEN the system SHALL recognise both directly-named brands and brands implied by an accepted brand fuel card (`carte TOTAL` ⇒ `TOTAL`; `carte BP` / `Sterling` ⇒ `AIR BP`; `carte SHELL` ⇒ `SHELL`; etc.), preferring a directly-named brand when both are present. Brand names SHALL be matched as whole words, never as substrings, so a common word that merely contains a brand name does not produce a false brand (e.g. the word `aviation` SHALL NOT be read as the `AVIA` brand).
5b. WHEN extracting contact details THEN the system SHALL capture a website URL and an email address from the AVT block when present, in addition to the phone number.
5c. WHEN retaining the verbatim AVT text THEN the system SHALL preserve the French and English renderings such that the front-end can present them separately, and SHALL strip conversion artifacts left by the PDF-to-text step — unbalanced/stray underscores, leftover bold markers (`**`), and stray control characters (e.g. `\u0007`) — without altering the substantive wording.
6. WHEN a VAC renders item `10 - AVT` as a table (label and value in separate cells) THEN the system SHALL apply a fallback that scans the AD 2.16 block for the fuel value rather than relying solely on inline label-to-value order.
7. IF a specific VAC cannot be parsed (e.g., text-unextractable military charts) THEN the system SHALL classify it `unknown`, record the failure in a processing report, and continue with the remaining aerodromes; OCR-based recovery is out of scope for v1.
8. WHEN the France provider finishes THEN the system SHALL output the extracted aerodromes in the normalized dataset format, including per-aerodrome effective date (`AMDT NN/YY`) and SIA source attribution as metadata.
9. WHERE fuel classification is performed THEN the system SHALL use deterministic, code-only (rule/regex) logic with no runtime LLM dependency, so results are reproducible and auditable. This applies to every field of the published dataset without exception.
10. WHERE a maintainer wants to find extraction gaps THEN the system MAY run an optional, advisory LLM quality-assurance pass that reads each aerodrome's `(source_text, parsed fields)` and emits structured suggestions focused on fuel grades and fuel state (e.g. a grade present in the text but missing from `avgas_grades`, or a mis-read `nil`/`available`); brand and contact detection are owned by the deterministic rules and are out of the LLM pass's scope (a first run showed the model only produced false positives there); the pass SHALL review all records for the enabled providers by default, SHALL write these suggestions only to the processing report / an artifact, SHALL run outside the publish path — a separate workflow, triggered automatically after a successful publish run (so each newly published cycle is QA'd) and also on demand, plus an opt-in local mode — such that the QA pass's execution, output, or failure never affects the publish run, the published dataset, or the never-worse guard; and SHALL NOT modify the published dataset, gate publishing, influence the never-worse guard, or edit code. The LLM SHALL run locally (no external API) so no chart data or secrets leave the runner, and SHALL be pinned (a fixed, instruction-tuned model — default `qwen3:8b`, configurable; a smaller model may be substituted where inference time matters — at temperature 0) for as much reproducibility as local inference allows. `qwen3:8b` was chosen for the best balance of a low false-alarm rate on correct records and a high catch rate for genuine extraction gaps (see the model comparison in the design). The audit prompt SHALL instruct the model to report ONLY discrepancies literally supported by the source text and to treat an absent brand/contact as normal (most aerodromes name none), never inventing a brand from operator/aeroclub names, MIL/CIV markers, or PPR text, and never reporting a value the parsed fields already contain. Turning a suggestion into an improvement is a human-reviewed step: a recurring suggestion becomes a new deterministic rule plus a regression fixture, never an automatic edit. (See ADR-0003.)

### Requirement 5: Modular multi-country architecture

**User Story:** As the maintainer, I want chart documents always retrieved from the autorouter WebDAV and only the per-country document parsing to be modular, so that new countries can be added by writing a parser without changing how data is fetched, combined, or displayed.

#### Acceptance Criteria

1. WHERE document retrieval is concerned THEN the system SHALL always fetch chart documents (VAC/AIP) from the autorouter WebDAV for every country, and a country module SHALL NOT introduce its own retrieval source or transport.
2. WHERE data ingestion is concerned THEN the system SHALL define a common parser interface that every country module implements, where a country module's sole responsibility is to parse that country's chart documents and produce fuel information keyed by ICAO code.
3. WHERE a country module is concerned THEN the system SHALL allow each country to parse its documents differently (different chart types, layouts, and languages), while the retrieval, OpenAIP coordinate join, dataset assembly, pipeline, and front-end remain shared and unchanged.
4. WHEN a country parser produces output that does not conform to the normalized dataset schema THEN the system SHALL reject that parser's output and exclude it from the build rather than allowing non-conforming data downstream.
5. WHEN a new country parser is added THEN the system SHALL integrate it into the build without requiring changes to retrieval, the front-end, or the pipeline wiring.
6. WHEN multiple country datasets exist THEN the system SHALL combine them into the dataset(s) consumed by the map.
7. WHERE a provider is named or keyed THEN the system SHALL identify it by its lowercased ICAO prefix (the shared two-letter ICAO region code of its aerodromes, e.g. `lf` for France), used for the provider package/folder, registry key, `code` attribute, iteration keys, and the dataset's `country` property and attribution key (uppercased in the dataset, e.g. `LF`). The ISO country code SHALL be used only where OpenAIP requires it (the `<iso>_apt.geojson` fetch), declared separately by the provider.

### Requirement 6: Aerodrome coordinates via OpenAIP join

**User Story:** As the maintainer, I want aerodrome coordinates sourced uniformly from OpenAIP, so that geometry is consistent across all countries and providers only handle fuel data.

#### Acceptance Criteria

1. WHEN the pipeline runs THEN the system SHALL retrieve OpenAIP's per-country airport exports for the relevant countries from the public OpenAIP bucket.
2. WHEN assembling the normalized dataset THEN the system SHALL join each provider's ICAO-keyed fuel record to its coordinates from the OpenAIP export by ICAO code.
3. IF an aerodrome with AVGAS has no matching OpenAIP coordinate THEN the system SHALL record the unmatched aerodrome in the processing report and SHALL exclude it from the map dataset rather than placing it at a wrong or null location.
4. WHERE OpenAIP data is used THEN the system SHALL comply with OpenAIP's terms (data remains free to use) and SHALL display OpenAIP attribution on the site.

### Requirement 7: Automated data pipeline via GitHub Actions

**User Story:** As the maintainer, I want the data fetched and processed automatically on AIRAC dates and published without committing to the repository, so that the map stays current with no manual work and no repository churn.

#### Acceptance Criteria

1. WHEN the pipeline runs THEN the system SHALL run the enabled country providers and regenerate the normalized dataset for the current AIRAC cycle.
2. WHERE scheduling is concerned THEN the system SHALL be triggered by a daily schedule that proceeds only on an AIRAC effective date (computed arithmetically from the fixed 28-day AIRAC epoch, no stored calendar) and SHALL no-op on non-AIRAC dates; the system SHALL also support a manual on-demand run (`workflow_dispatch`).
3. WHEN a new dataset passes the never-worse validation THEN the system SHALL publish it as an asset on a per-cycle GitHub Release (tag `airac-<YYNN>`) and SHALL regenerate the cycle manifest; the system SHALL NOT commit any dataset, report, or artifact to the repository.
4. WHEN validating a new dataset before publishing THEN the system SHALL apply both an absolute floor (minimum feature count) and a relative-drop check (against the previous cycle's feature count) and, IF either fails, SHALL abort publication, leave the previous cycle as the latest, log the failure, and exit non-zero.
5. IF a provider run or the publish step fails THEN the system SHALL surface the failure in the pipeline output and SHALL NOT overwrite or supersede the last known-good published cycle.
6. WHEN the pipeline records its outcome THEN the system SHALL write a processing report to the GitHub Actions job summary and upload it as a run artifact, and SHALL NOT commit the report to the repository.
7. WHERE external source access is concerned THEN the system SHALL fetch documents freshly each run using bounded concurrency with retry/backoff, so as not to overload the autorouter or OpenAIP servers.
8. WHILE the pipeline runs THEN the system SHALL emit progress logging to the console (stderr) covering each stage — retrieval (with periodic download progress over the long chart fetch), chart parsing (a per-chart line at DEBUG), coordinate fetch, assembly counts, guard decision, and final outcome — at INFO level by default, with a verbose (DEBUG) option, so a long run is observable rather than silent.
9. WHERE a maintainer needs to debug a country parser THEN the system SHALL support a `--keep-intermediates` option (default off) that persists each chart's converted intermediate text (the markdown produced from the source PDF) into the workspace under `<workspace>/md/<code>/<ICAO>.md`, so a misclassification can be inspected without re-running the conversion by hand; WHEN the option is off THEN the system SHALL NOT write any intermediate text, and in either case the intermediate text SHALL NOT be committed to the repository or shipped with the site.
10. WHEN a live (non-dry-run) run starts THEN the system SHALL verify that each enabled provider's chart-conversion dependencies can be imported before any retrieval, and IF a required dependency is missing or broken (e.g. an unimportable `pymupdf`/`pymupdf4llm`) THEN the system SHALL abort immediately with a clear, actionable error naming the failing dependency and the interpreter in use, rather than proceeding to produce an all-`unknown` dataset that silently trips the never-worse guard.
11. WHERE any per-chart conversion nonetheless fails at runtime THEN the system SHALL log the failure (with the offending ICAO and the error) rather than swallowing it silently, so a systematic conversion failure is visible in the run output.
12. WHERE a maintainer has already retrieved a cycle's charts into a workspace THEN the system SHALL support a `--reparse-only` option that skips retrieval and rebuilds the dataset by re-parsing the charts already present in the workspace (still fetching coordinates and applying the guard), so a parser fix can be re-applied without re-downloading; IF the workspace holds no charts for an enabled provider THEN the run SHALL surface that clearly rather than silently producing an empty dataset. `--reparse-only` requires a `--workspace` and is mutually exclusive with `--dry-run` (which uses fixtures, not charts).

### Requirement 8: Free static hosting via GitHub Pages

**User Story:** As the maintainer, I want the site hosted for free via build-and-deploy, so that the project has no running cost and no committed build output.

#### Acceptance Criteria

1. WHEN the site is built THEN the system SHALL produce static assets and deploy them to GitHub Pages from a workflow artifact (build-and-deploy), not from a committed folder or branch.
2. WHEN the front-end needs aerodrome data THEN the system SHALL load the cycle manifest shipped with the site and fetch the selected cycle's dataset from the **same origin** as the site (a relative path under the deployed site), because browsers cannot fetch GitHub Release asset URLs cross-origin (they 302-redirect to a storage host that sends no CORS header). GitHub Releases remain the per-cycle archive/source of truth; at deploy time the pipeline materializes every retained cycle's dataset into the deployed site (downloading prior cycles' assets server-side via the authenticated API, where CORS does not apply) so the manifest can use relative, same-origin URLs. No backend server is required.
3. WHEN a new AIRAC cycle is published THEN the system SHALL redeploy the site immediately (regenerating the manifest so the new cycle becomes selectable and latest), without batching.
4. WHERE hosting is concerned THEN the system SHALL NOT require any paid service to operate, and the last successfully deployed site SHALL remain the last known-good state if a later run fails.
5. WHERE local development is concerned THEN the system SHALL support generating a dataset locally and previewing the full map over a local static server without publishing a Release, using the same front-end code as production.

### Requirement 9: Data freshness and disclaimer

**User Story:** As a pilot, I want to know how current and reliable the data is, so that I do not rely on stale or unofficial information for flight safety.

#### Acceptance Criteria

1. WHEN the site loads AND both the effective date and the AIRAC cycle of the currently displayed dataset are available THEN the system SHALL display them; IF either is missing THEN the system SHALL NOT display partial freshness information.
2. WHEN the site loads THEN the system SHALL default the AIRAC-cycle selector to the latest available cycle, AND WHEN the user selects a different cycle THEN the system SHALL load and display that cycle's dataset and update the freshness display accordingly.
3. WHEN the site loads THEN the system SHALL display a disclaimer that the map is not an official source and must not be used as the sole reference for flight planning.
4. WHERE data is derived from an official source THEN the system SHALL attribute that source per country (e.g., SIA for France) AND SHALL display OpenAIP attribution for coordinate data as required.
5. WHEN the site loads THEN the system SHALL display a link to the project's source repository (GitHub) in the site chrome, so the project stays open and inspectable.

## Scope and Sequencing

- The product scope is the EASA area, using charts available through the autorouter WebDAV.
- Providers are added per country. France is the first provider to be implemented and doubles as the reference implementation of the common provider interface. Additional countries follow as their own providers behind the same interface; the map and pipeline must not need changes to add one.

## Out of Scope (v1)

- Fuel pricing information.
- Any specific country provider beyond France in the first iteration (the architecture supports the full EASA area; only France is implemented first).
- User accounts, user-submitted data, or comments.
- Routing / flight-plan calculation between aerodromes.
- Real-time NOTAM or fuel-outage status.
- Native mobile applications (responsive web is sufficient).
