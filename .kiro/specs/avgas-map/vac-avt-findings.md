# VAC "10 - AVT" extraction — spike findings

Spike to understand how AVGAS availability is documented in French VACs, so we
can spec the France provider (Requirement 4). Source: autorouter WebDAV
(`/webdav/France/<ICAO> - <name>/VFR/AD 2 <ICAO> VAC.pdf`). Conversion:
`pymupdf4llm` (PDF -> Markdown). Test harness: `scripts/vac_avt_test.py`.

## Sample

438 `LF**` aerodrome folders found; all processed. 420 had a VAC PDF (18 had
none — military/restricted fields). Downloads run 10-way parallel and are cached
to `out/pdf/`; conversion and extraction are separate cached stages.

| Classification | Count | Meaning |
|----------------|-------|---------|
| AVGAS present | 296 | An AVGAS grade (100LL / UL91 / 100/130) found in item 10 - AVT |
| No fuel (NIL) | 96 | AVT explicitly says NIL — a real "no fuel" signal |
| Fuel but no AVGAS | 26 | Only non-AVGAS grades (e.g. military F18/F34/F35, JET A1) |
| AVT missing/unmatched | 2 | LFRJ + LFRL (military "TRANSIT VFR", text not extractable) |
| No VAC PDF | 18 | LFBC, LFBM, LFKS, LFMO, LFOA, LFOE, LFPI, LFPV, LFSI, LFSO, LFSX, LFTL, LFWB, LFWD, LFWH, LFWM, LFWN, LFWO |

Anchor hit rate on aerodromes that have a text VAC: 418/420 (>99%). LFOH (table
layout) was recovered by the fallback described below; only the 2 military
charts remain unparseable.

## How the AVT field is structured

- Item is labelled **`10 - AVT`**, immediately followed by item **`11 - RFFS`**.
  These two labels bound the fuel field reliably.
- Content is **bilingual**: French first, English in italics
  (`Carburants / _Fuel_ : ...`).
- The field carries **more than grades** — payment methods, hours, PPR, and
  MIL/CIV splits. Examples:
  - LFAV: `Carburants / Fuel : (AIR BP) 100 LL-JET A1. (CIV-MIL) Cash, BP card.`
  - LFBY: `MIL : F34 - CIV : 100 LL - UL 91` + payment phone numbers.
  - LFAE: `AVGAS UL91 : reserved for based ACFT` (a conditional availability).
- **`NIL`** is used explicitly when no fuel is offered. This must map to a
  distinct "no fuel" state, not "unknown" (per AGENTS.md flight-safety framing).

## AVGAS grade wording (normalize these)

- `100 LL`, `100LL`, `100 LL-JET A1` -> **100LL**
- `UL 91`, `UL91` -> **UL91**
- Generic `AVGAS` sometimes appears alongside a specific grade; treat the
  specific grade as authoritative.
- Non-AVGAS grades to exclude: `JET A1`, military `F18 / F34 / F35` (JET),
  and lubricants `O135 / O155 / H515`.

## Edge cases for the provider to handle

1. **Table-rendered VACs break text-order extraction.** LFOH (Le Havre) renders
   AD 2 as a Markdown table; the `10 - AVT` label and its value land in separate
   cells, so a naive "label -> next item" scan misses it. The fuel data is still
   present (`AVGAS 100LL : Automate H24 ...`). *Solved* with a fallback: when the
   `10 - AVT` anchor yields nothing, scan for a line starting with a fuel
   keyword (`AVGAS` / `Carburant`) + `:`. This fires only when the primary
   anchor is empty, so it can't disturb the 417 already-working files.
2. **Value continues after a `Lubrifiants` break.** LFBG's grades (`F18 - F34 -
   F35`) sit on a line after the fuel/oil split; a fixed short window can clip
   them. Capture the full item-10 block up to item 11.
3. **Some aerodromes have no VFR/VAC PDF** (military/CAP fields: LFBC, LFBM,
   LFKS, LFMO, LFOA, etc.). Provider must skip and record, not fail (Req 4.5).
4. **Folder listing is noisy.** `France/` contains non-French ICAOs (Libyan
   `HL..`, Rwandan `HR..`) and `LF##` ULM strips with no VAC. Filter to
   `^LF[A-Z]{2}`.

## Embedded-font extraction limits (root cause of the "weird characters")

VAC PDFs use subsetted Type1 fonts (`Gen_Helvetica-LT-Narrow`, random prefix
like `EMOHDD+`) with **empty encoding and no ToUnicode table**. Text is stored
as font-specific byte codes, not Unicode. MuPDF recovers most body text from the
glyph *names*, but where even that fails the extractor emits U+FFFD (`�`).

- The `�` runs are almost entirely the **stylized banner font** — "APPROCHE A
  VUE" on standard VACs, "TRANSIT VFR" on military ones. 403/420 files contain
  `�`, but it lands inside the AVT block in only 1. So it's cosmetic noise, not
  a data problem, for the civil VACs.
- **Military "TRANSIT VFR" charts are largely unextractable as text.** LFRL
  yields 13 real letters out of 1665 chars (the rest are control bytes); LFRJ
  ~1238 of 4067. Their body is effectively vector-drawn glyphs. No text
  extractor (pymupdf4llm, pdfminer/markitdown) recovers them — only OCR would,
  and these are naval air stations with no civil AVGAS, so low value to chase.

Decision: keep **pymupdf4llm** as the converter. markitdown/pdfminer emits zero
`�` but scrambles reading order, detaching item labels from their values, which
breaks the reliable `10 - AVT` -> value anchoring. OCR is the only real fix for
the military charts and is deferred (out of scope for v1 value).

## Metadata available

- `AMDT NN/YY` (e.g. `AMDT 01/25`) appears on the page — supports the AIRAC /
  effective-date requirements (Req 2.4, 6, 8).
- Source attribution present: `© Service de l'Information Aéronautique, France`.

## Implications for requirements

- **Req 4.2 (extract fuel grades):** anchor on `10 - AVT` .. `11 - RFFS`;
  normalize grade wording. A table-layout fallback (scan for a line starting
  `AVGAS`/`Carburant` + `:`) recovers detached values — recovered LFOH.
- **Req 2.3 (conditions):** AVT routinely includes hours / PPR / MIL-CIV /
  payment — model conditions as a first-class field, not folded into the grade.
- **Req 2.5 & AGENTS.md (unknown vs unavailable):** distinguish three states —
  AVGAS present, explicitly NIL (no fuel), and AVT-unparseable (unknown).

## What the AVT field actually contains (survey of 418 extracted blocks)

| Signal | Present in |
|--------|-----------|
| AVGAS 100LL | 275 (66%) |
| AVGAS UL91 | 29 (7%) |
| AVGAS 100/130 | 2 |
| JET A1 (not AVGAS) | 133 (32%) |
| Military F-grade (F18/F34/F35, = JET) | 10 |
| Explicit NIL | 205 (49%)* |
| O/R (on request) | 131 (31%) |
| PPR (prior permission) | 59 (14%) |
| Operating hours (HHMM-HHMM) | 79 (19%) |
| HOR / H24 / SR / SS hours ref | 148 (35%) |
| MIL vs CIV split | 57 (14%) |
| Payment / carte / cash | 236 (57%) |
| Fuel brand (TOTAL / AIR BP / Shell) | 134 (32%) |
| Self-service / automate | 88 (21%) |
| Reserved for based ACFT | 20 (5%) |
| Phone number | 65 (16%) |

*NIL count includes the Lubricants sub-field, so NIL must be read positionally
(attached to the fuel value, not the oil value), not by mere presence.

Block length: min 3, median 147, max 1122 chars. Bilingual: French value with a
free English translation in italics after `/`; parse off the French.

## Extraction contract (decided) — deterministic, code-only, NO LLM at runtime

Parse each AVT block into these fields with pure regex/rule-based code:

1. **AVGAS grades** — normalized list, closed vocabulary (`100LL`, `UL91`,
   `100/130`). High confidence.
2. **JET A1** — boolean. High confidence.
3. **Fuel status** — `available` / `nil` / `unknown` (the three-state safety
   distinction; NIL read positionally).
4. **Payment / brand / phone / self-service** — flags/values from closed-ish
   vocabularies and a phone regex.
5. **Operating hours / O/R / PPR / reserved-for-based** — presence **flags**
   (not a fully structured schedule).
6. **Free text (remainder)** — the AVT text not captured by the fields above,
   kept verbatim (bilingual) for display. This is the catch-all so nothing is
   lost; it is not parsed further.

### Why code, not LLM

- **Static hosting / no cost invariant (AGENTS.md):** a rules parser runs free
  in the GitHub Actions pipeline; an LLM adds an API dependency, cost, and a
  runtime network call.
- **Flight-safety determinism:** same input -> same output, every run, and it's
  auditable ("classified 100LL because it matched pattern X"). An LLM can drift
  or hallucinate a grade — unacceptable for safety data.
- **Testable:** 418 real AVT blocks are cached (`out/avt/`) as a fixture set.
- **The data suits it:** grades are a closed vocabulary written consistently;
  conditions are detectable tokens. Regex is the right tool.

Deliberately NOT built in v1: deep structuring of the free-text conditions into
a normalized schedule object. Extract flags + keep raw text; defer richer
parsing unless a later requirement needs it. An LLM, if ever used, would be an
offline QA/fallback pass on the residue (e.g. the 2 OCR-only military charts),
never a runtime dependency.

## Data source & access

- **Source:** autorouter WebDAV at `https://www.autorouter.aero/webdav`. It
  mirrors the SIA eAIP VAC PDFs. (The SIA eAIP itself is the authoritative
  origin — Req 4.1 / attribution.)
- **Auth:** HTTP Basic (`WWW-Authenticate: Basic realm="autorouter/webdav"`),
  using an autorouter account. Not OAuth — plain Basic over HTTPS.
- **Credential handling (spike, superseded):** the spike used a DPAPI-encrypted
  PowerShell file. **This approach is dropped.** The production pipeline reads
  credentials only from env vars `AUTOROUTER_USER` / `AUTOROUTER_PASS` (portable,
  OS-agnostic): GitHub Actions secrets in CI, shell env or an optional gitignored
  `.env` locally. No `.cred` file, no DPAPI, no pwsh helper.
- **Rate/scale:** downloads run 10 parallel workers, each with its own WebDAV
  client (webdavclient3 `Client` is not documented as thread-safe). Full France
  download (~420 PDFs) completes in a couple of minutes this way.

## Discovered WebDAV layout

- France aerodromes live under `France/<ICAO> - <name>/`, e.g.
  `France/LFAV - Valenciennes Denain/`.
- The VAC prose (with item `10 - AVT`) is a single PDF in the `VFR/` subfolder:
  `France/<folder>/VFR/AD 2 <ICAO> VAC.pdf`.
- The `Airport/` subfolder holds the fuller IFR text (`AD 2 <ICAO>.pdf`); other
  subfolders (`Approach/`, `Arrival/`, `Departure/`) hold instrument charts —
  not used here.
- `France/` also contains non-French ICAOs (Libyan `HL..`, Rwandan `HR..`) and
  `LF##` ULM strips. Filter to `^LF[A-Z]{2}` and require a `VFR/` folder.

## Environment & tooling

- **Python 3.12**, packages: `pymupdf4llm` (+ `pymupdf`) for PDF->Markdown,
  `webdavclient3` for WebDAV. (`markitdown` was trialled then removed; some of
  its transitive deps — `pdfminer.six`, `pdfplumber`, `pypdfium2`, `onnxruntime`,
  `magika` — may remain installed but are unused.)
- No `requirements.txt` committed yet; the real provider should pin these.

## Spike scripts (in `scripts/`, throwaway — not production code)

- `vac_avt_test.py` — staged pipeline. Stages run in order by default; flags
  select one: `--download` (parallel fetch to `out/pdf/`), `--convert`
  (PDF->MD to `out/md/`), `--extract` (MD->AVT + `out/report.md`; no network,
  no creds). `--force` re-does cached work. Holds the working extraction logic:
  `extract_avt` (+ table fallback), `find_avgas_grades`, `is_nil`, `classify`.
- `run_vac_test.ps1` — decrypts the credential and runs the pipeline; forwards
  stage flags.
- `probe_layout.py` / `run_probe.ps1` — dump a folder's WebDAV tree.
- `probe_fonts.py` — dump page-1 fonts + top-of-page spans (font root-cause).
- `survey_avt.py` — the signal-frequency survey over `out/avt/`.

## Outputs (all under `out/`, gitignored)

- `out/pdf/<ICAO>.pdf` — cached raw VAC PDFs (420).
- `out/md/<ICAO>.md` — converted markdown (420).
- `out/avt/<ICAO>.avt.md` — extracted AVT blocks (418 with content) — usable as
  a test fixture set for the real parser.
- `out/report.md` — summary table (ICAO, status, grades, AVT preview).
- `out/no_pdf.txt` — the 18 ICAOs with no VAC PDF.

## Reproduce

```powershell
# one-time: store autorouter creds (encrypted, per Windows user)
$cred = Get-Credential
$cred | Export-Clixml "$PWD\.autorouter.cred"

# full run (download -> convert -> extract)
pwsh -File scripts/run_vac_test.ps1

# re-extract only (no network / no creds needed) after tweaking regexes
python scripts/vac_avt_test.py --extract
```

## Current state & open items for the next (spec) session

- **Done:** access + auth understood; 438 folders enumerated; 420 VACs cached,
  converted, and AVT-extracted; extraction contract decided; converter decided
  (pymupdf4llm); LFOH table fallback working. Coverage: 418/420 text VACs.
- **Known unresolved (low value):** LFRJ, LFRL — military "TRANSIT VFR" charts,
  text not extractable without OCR; no civil AVGAS. Deferred.
- **Open decisions for the provider spec (not yet made):**
  - Coordinates + aerodrome name: NOT sourced here — item `10 - AVT` has no
    geo. Need another eAIP field/document (AD 2 header, or the eAIP AD index)
    for lat/long and name (Req 4.2). This spike only covered fuel.
  - AIRAC/effective date: `AMDT NN/YY` is on the page but not yet extracted.
  - Where credentials come from in CI (GitHub Actions secrets).
  - Whether to keep raw PDFs/MD as pipeline artifacts or re-fetch each run
    (mind the "never publish worse data than last time" invariant on failure).
- **Reusable asset:** `out/avt/*.avt.md` (418 real blocks) is the fixture set to
  test the deterministic parser against.

## Real-PDF validation (post-implementation, cycle 2608)

Running the real pipeline (420 VACs fetched live) surfaced facts the
hand-authored fixtures had missed:

1. **Download bug (retrieval):** webdavclient3 3.14.6's `download_from`
   unconditionally reads `response.headers['content-length']` for a progress
   callback; the autorouter server responds without that header, so every
   download raised `KeyError: 'content-length'`. Fixed by downloading with a
   plain authenticated `requests` GET (URL-encoding each path segment),
   bypassing the library's buggy method. `list` still uses webdavclient3.

2. **AVT anchor was too strict.** Real markdown renders the label as
   `**10 -** **AVT :**` — the hyphen is *inside* the bold and there is a
   `** **` gap before `AVT`. The original anchor (`10\s*[-]\s*\**\s*AVT`) did
   not tolerate the space-separated bold markers and missed ~half the charts.
   Fix: tolerate arbitrary runs of `*` and whitespace between `10`, the hyphen,
   and `AVT` (and likewise before the next item). Real label form to match:
   `Carburant / Fuel : 100LL ...` follows the `**AVT :**` marker.

3. **Some charts have no readable fuel text at all.** Font-subset extraction
   fails on certain VACs (e.g. LFAV) — no `Carburant`/`Fuel`/`100`/`RFFS`
   tokens recover as Unicode. These correctly classify `unknown` (not a false
   `available`), per the flight-safety framing.

4. **Progress logging clarity:** the retrieval progress line counts *attempts*
   (every outcome), so it must report `processed N/total — X ok, Y failed,
   Z no-pdf` rather than "fetched N", which reads as successes.

Coverage after the anchor fix rose sharply from the first (buggy) run; the
never-worse guard correctly FAILED the buggy 141-feature run (below the 200
floor), doing its job. Retrieval matched the spike exactly: 420 downloaded,
18 no-pdf, 0 errors.
