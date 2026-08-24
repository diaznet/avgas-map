# Context: AVGAS-Map

Glossary of domain terms for AVGAS-Map. Definitions only — no implementation
details. When code or docs name one of these concepts, use the term as defined
here and avoid the listed synonyms.

## Terms

### Aerodrome
A real-world place where aircraft operate, identified by its **ICAO code**. The
ICAO code is its sole identity in this system. An aerodrome may or may not offer
AVGAS, and may or may not appear in any given data source.
- Avoid: "airport" (reserved for the OpenAIP raw export), "field", "station".

### ICAO code
The four-letter identifier of an aerodrome (e.g. `LFAV`). The **sole identity
and join key** across all data sources. No fuzzy name/coordinate matching is
used; an aerodrome is the same aerodrome only if the ICAO code matches exactly.

### Fuel record
A country parser's output describing one aerodrome's fuel situation, keyed by
ICAO code. Contains the fuel state, any AVGAS grades, a Jet A-1 flag, condition
flags, verbatim source text, and the source effective date. Produced from chart
documents; carries no coordinates.
- Avoid: calling this an "aerodrome" — it is *facts about* an aerodrome.

### Fuel state
One of exactly three values for an aerodrome's fuel:
- `available` — at least one AVGAS grade is present.
- `nil` — the source explicitly states no fuel (read positionally against the
  fuel value, not the lubricants value).
- `unknown` — the source could not be located or parsed.
"Unknown" never means "unavailable" (flight-safety framing).

### AVGAS grade
A grade of aviation gasoline for piston engines, from the closed vocabulary
`100LL`, `UL91`, `100/130`, plus the generic `AVGAS`. The generic `AVGAS` means
"AVGAS is available but the source names no specific grade"; it lets such an
aerodrome count as offering AVGAS. When a specific grade is present, it takes
precedence and the generic `AVGAS` is dropped. Jet A-1 and military/turbine
fuels are **not** AVGAS and never make an aerodrome count as offering AVGAS.

### Airport (OpenAIP airport)
A record in an OpenAIP per-country export (`<cc>_apt.geojson`), providing an
aerodrome's coordinates and name, keyed by ICAO. Used only as the coordinate
source. "Airport" refers exclusively to this raw OpenAIP export — everywhere
else, say "aerodrome".

### Map feature
A published GeoJSON `Point` feature on the map. It is a Fuel record with state
`available` joined by ICAO to its OpenAIP coordinates. AVGAS-only: aerodromes
whose fuel state is `nil` or `unknown` are never map features (they appear only
in the processing report).
- Avoid: "marker" (that's the rendered UI element) and "aerodrome" (a feature is
  the *published join*, not the place).

### Condition flags
The structured, non-grade fuel conditions attached to a fuel record, a closed
shape for v1:
- Booleans: `on_request`, `ppr`, `self_service`, `reserved_for_based`,
  `mil_civ_split`, `has_hours`.
- Optional values: `payment` (list of strings), `brand` (string or null),
  `phone` (string or null), `website` (string or null), `email` (string or null).
`brand` is the fuel provider: recognised either from a directly-named brand or
inferred from an accepted brand fuel card (`carte TOTAL` ⇒ `TOTAL`,
`Sterling`/`carte BP` ⇒ `AIR BP`, etc.), with a directly-named brand preferred.
Anything the parser detects that this shape does not capture remains in the
verbatim source text, so no information is lost. The shape is frozen *within a
schema version*: adding a new flag later is a deliberate schema-version bump
(new field + parser detection + popup rendering), never an ad-hoc field a parser
starts emitting silently. This keeps the normalized dataset a stable contract.

### Schema version
A version marker stamped on every dataset's metadata and echoed per cycle in the
manifest. Changing the published feature shape (e.g. adding a condition flag)
increments it, signalling a coordinated change across parser, dataset, and
front-end. Within a schema version the feature shape is fixed. Because all cycles
are retained forever, schema changes are additive-only within a major line and
the front-end must render older cycles tolerantly: show fields that are present,
treat missing fields as unknown, and never assume a field exists. This is what
keeps retained history renderable after the schema moves.

### Source text
The verbatim fuel text captured from a country's source document, stored on the
fuel record and displayed in the map feature's popup. Country-agnostic name; for
France it is the raw AVT block. (Earlier drafts called this `avt_raw`, a
France-specific name that must not leak into the shared contract.)

### Extraction QA pass
An optional, advisory LLM step that reviews already-parsed fuel records against
their verbatim source text and reports *suggestions* about likely extraction
gaps. It is **not** part of the data path: it never writes the published dataset,
never gates publishing, never touches the never-worse guard, and never edits
code. It runs locally (Ollama on the runner, no external API) and outside the
publish path. Its sole output is suggestions for humans; see "Extraction
suggestion". (Deterministic published extraction — the "no runtime LLM" rule,
R4.9 — is unaffected: the QA pass sits beside the pipeline, not inside it. ADR-0003.)
- Avoid: calling this "the parser" or "extraction" — it validates extraction, it
  does not perform it.

### Extraction suggestion
One structured, advisory finding from the Extraction QA pass about a single
aerodrome, e.g. a grade the text states but `avgas_grades` omits, a mis-read
`nil`, or a missed contact. Carries a `kind` (so suggestions aggregate into
patterns), the ICAO, a human-readable detail, and a confidence. A *pattern* of
the same `kind` across many aerodromes signals a deterministic parser-rule bug to
fix (with the suggestion doubling as a regression fixture). Suggestions never
change published data or code on their own — acting on one is a human-reviewed
step.

### Country parser (provider)
A country-specific module that parses that country's chart documents into fuel
records keyed by ICAO. It does not fetch documents (retrieval is shared) and does
not assign coordinates (the OpenAIP join does). France is the first parser.

**Naming rule (mandatory):** a provider is identified everywhere by its
**lowercased ICAO prefix** — the two-letter ICAO region code its aerodromes
share (France = `lf`, Germany = `ed`), not the ISO country code. This applies to
the provider's package/folder name, its registry key, its `code` attribute, the
keys used to iterate providers, and the `country` property + attribution key in
the published dataset (uppercased there, e.g. `LF`). Rationale: identity and
filtering are ICAO-based (`^LF[A-Z]{2}`), so the ICAO prefix is the natural key.
The one exception is the OpenAIP coordinate fetch (see OpenAIP ISO code).

### OpenAIP ISO code
The ISO 3166-1 alpha-2 country code(s) a provider declares **only** so the shared
OpenAIP join can fetch the right export file (`<iso>_apt.geojson`, e.g.
`fr_apt.geojson`). Distinct from the provider's ICAO-prefix identity (`lf`):
OpenAIP files are ISO-keyed, everything else is ICAO-prefix-keyed. A provider
maps its ICAO prefix to one or more OpenAIP ISO codes (France: `lf` → `fr`).

### AIRAC cycle
The 28-day international cycle on which aeronautical data changes, identified as
`YYNN` (e.g. `2609`). Data is published ~28 days before it takes effect.

### Latest cycle
The newest AIRAC cycle whose **effective date is on or before today**. Not
merely the newest cycle published. Future-effective cycles may exist as
pre-published Releases but are not "latest" until their effective date arrives.
The map defaults to the latest cycle.

### Effective date
The date an AIRAC cycle's data becomes legally in force. Distinct from the
publication date (~28 days earlier) and from a run date.

### VAC / AVT (France-specific)
VAC: a French Visual Approach Chart PDF. AVT: its fuel field, item `10 - AVT`
bounded by `11 - RFFS`. These terms are specific to the France parser and must
not be treated as universal — other countries use different chart types and
layouts behind the same parser interface.
