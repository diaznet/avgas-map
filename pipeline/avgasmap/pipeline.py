"""Pipeline orchestration: compose the stages into one run.

Stages: AIRAC gate -> retrieval -> parse -> OpenAIP join -> assemble -> guard ->
publish (Release + manifest) OR local (write web/data/) -> report.

Modes:
  - normal: fetch from autorouter + OpenAIP, publish a Release, deploy handled by CI.
  - --local: same build, but write dataset + local manifest to web/data/ (no publish).
  - --dry-run: build from fixtures, no network, no publish.

Kept dependency-light and testable: the heavy I/O (retrieval, OpenAIP fetch,
GitHub) is injected or guarded so tests can run offline.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date

from avgasmap import airac, assemble, coordinates, providers, publish, report, validate
from avgasmap.coordinates import Coordinate
from avgasmap.logconfig import get_logger

log = get_logger(__name__)


@dataclass
class RunConfig:
    countries: list[str] | None = None      # None => all enabled
    cycle: str | None = None                # forces cycle, bypasses AIRAC gate
    local: bool = False
    dry_run: bool = False
    workspace: str = ""                     # temp dir if empty
    web_data_dir: str = ""                  # defaults to repo web/data
    floor: int = validate.DEFAULT_FLOOR
    max_drop: float = validate.DEFAULT_MAX_DROP
    override_guard: bool = False
    keep_intermediates: bool = False        # dump converted markdown for debugging
    reparse_only: bool = False              # rebuild from cached charts, skip retrieval
    llm_review: bool = False                # advisory LLM extraction-QA pass (ADR-0003)
    llm_model: str = ""                     # override the pinned QA model


@dataclass
class RunOutcome:
    status: str                              # "published" | "local" | "skipped" | "failed"
    cycle: str | None = None
    feature_count: int = 0
    manifest: dict | None = None
    report_md: str = ""
    detail: str = ""
    report_data: report.ReportData | None = field(default=None)


def _repo_root() -> str:
    # this file: <repo>/pipeline/avgasmap/pipeline.py -> up 3 = <repo>
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _resolve_cycle(cfg: RunConfig, today: date | None = None) -> str | None:
    if cfg.cycle:
        return cfg.cycle
    return airac.is_airac_today(today)


# --- Fixture source for --dry-run (offline) --------------------------------

def _fixture_records() -> dict[str, dict]:
    """Build lf (France) fuel records from the bundled test fixtures (offline)."""
    from avgasmap.providers.lf import LfParser
    from tests.fixtures.lf.cases import CASES

    parser = LfParser()
    return {icao: parser.parse_markdown(icao, c["markdown"]) for icao, c in CASES.items()}


def _fixture_index(records: dict[str, dict]) -> dict[str, Coordinate]:
    """Synthetic coordinates for every fixture ICAO (so 'available' ones join)."""
    idx: dict[str, Coordinate] = {}
    for i, icao in enumerate(sorted(records)):
        idx[icao] = Coordinate(lon=2.0 + i * 0.1, lat=48.0 + i * 0.1, name=f"{icao} (fixture)")
    return idx


# --- Live source stages (real network) -------------------------------------

def _collect_records_live(
    code: str, workspace: str, keep_intermediates: bool = False,
    reparse_only: bool = False,
) -> tuple[dict[str, dict], list[str], list[str]]:
    """Retrieve + parse one provider (by code). Returns (records, no_pdf, errors).

    When `keep_intermediates` is set, each chart's converted markdown is written
    to `<workspace>/md/<code>/<ICAO>.md` for debugging (workspace-only, never
    committed or shipped).

    When `reparse_only` is set, retrieval is skipped and the charts already in
    `<workspace>/pdf/<code>/` are re-parsed (no_pdf/errors are empty). Used to
    re-apply a parser fix without re-downloading.
    """
    from avgasmap import retrieval

    if code != "lf":
        # Only the lf (France) provider is implemented; others plug in here.
        return {}, [], []

    dest = os.path.join(workspace, "pdf", code)
    if reparse_only:
        # Skip retrieval; parse whatever charts are already in the workspace.
        no_pdf, fetch_errors = [], []
        log.info("[%s] reparse-only: using charts already in %s", code, dest)
    else:
        results = retrieval.retrieve_france(dest)
        no_pdf = [r.icao for r in results if r.outcome == "no-pdf"]
        fetch_errors = [f"{r.icao}: {r.outcome}" for r in results if r.outcome.startswith("error")]

    md_dir = ""
    if keep_intermediates:
        md_dir = os.path.join(workspace, "md", code)
        os.makedirs(md_dir, exist_ok=True)
        log.info("[%s] keeping intermediate markdown under %s", code, md_dir)

    parser = providers.get_parser(code)
    paths = parser.chart_paths(dest)
    if reparse_only and not paths:
        # Nothing to reparse — surface it clearly rather than emit an empty set
        # that would later trip the guard with a misleading reason.
        log.error("[%s] reparse-only: no charts found in %s — nothing to parse "
                  "(run a normal retrieval first?)", code, dest)
    records: dict[str, dict] = {}
    for icao, path in paths.items():
        log.debug("[%s] parsing %s", code, icao)
        records[icao] = parser.parse(icao, path, md_dump_dir=md_dir)
    return records, no_pdf, fetch_errors


def _run_llm_review(records_by_country: dict[str, dict[str, dict]],
                    workspace: str, model: str | None) -> None:
    """Advisory LLM QA over all parsed records. Report-only; never raises.

    Writes `<workspace>/suggestions.json` and appends a grouped section to the
    GitHub job summary. Failures here NEVER fail the run (ADR-0003, R4.10).
    """
    from avgasmap import llm_review

    used_model = model or llm_review.DEFAULT_MODEL
    all_records = [r for recs in records_by_country.values() for r in recs.values()]
    log.info("LLM extraction-QA: reviewing %d record(s) with %s ...",
             len(all_records), used_model)
    try:
        client = llm_review.OllamaClient(model=used_model)
        suggestions = llm_review.review_records(all_records, client=client, model=used_model)
    except Exception as exc:  # noqa: BLE001 - advisory pass must never fail a run
        log.warning("LLM review skipped (%s)", exc)
        return

    llm_review.write_suggestions(suggestions, os.path.join(workspace, "suggestions.json"))
    md = llm_review.render_suggestions_markdown(suggestions, model=used_model)
    log.info("LLM extraction-QA: %d suggestion(s); wrote suggestions.json",
             len(suggestions))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write("\n" + md)
        except OSError:
            pass


def _fetch_index_live(code: str) -> dict[str, Coordinate]:
    """Fetch + merge the OpenAIP coordinate index for a provider's ISO code(s).

    OpenAIP files are ISO-keyed, so we use the provider's declared openaip_iso
    (e.g. lf -> ['fr']), not the provider code.
    """
    parser = providers.get_parser(code)
    index: dict[str, Coordinate] = {}
    for iso in parser.openaip_iso:
        index.update(coordinates.fetch_country_index(iso))
    return index


# --- Orchestration ----------------------------------------------------------

def run(cfg: RunConfig, *, today: date | None = None,
        previous_count: int | None = None,
        gh: publish.GitHubReleases | None = None) -> RunOutcome:
    """Execute one pipeline run according to cfg."""
    providers.ensure_loaded()

    cycle = _resolve_cycle(cfg, today)
    if cycle is None:
        return RunOutcome(status="skipped", detail="today is not an AIRAC effective date")

    eff = airac.effective_date(cycle).isoformat()
    # Provider codes = lowercased ICAO prefixes (e.g. "lf").
    codes = cfg.countries or (["lf"] if cfg.dry_run else list(providers.enabled_parsers()))
    mode = "dry-run" if cfg.dry_run else ("local" if cfg.local else "publish")
    log.info("Run start: cycle=%s (effective %s), mode=%s, providers=%s",
             cycle, eff, mode, codes)

    # Fail fast: a live run needs each provider's chart-conversion deps. If the
    # interpreter can't import them (e.g. a broken pymupdf), abort now with a
    # clear message instead of silently producing an all-'unknown' dataset that
    # trips the never-worse guard. Dry-run uses fixtures, so it skips this.
    if not cfg.dry_run:
        for code in codes:
            parser = providers.get_parser(code)
            check = getattr(parser, "check_dependencies", None)
            if check is None:
                continue
            try:
                check()
            except Exception as exc:  # noqa: BLE001 - surface as a failed run
                log.error("[%s] dependency check failed: %s", code, exc)
                return RunOutcome(status="failed", cycle=cycle, detail=str(exc))

    workspace = cfg.workspace or tempfile.mkdtemp(prefix="avgasmap-")
    os.makedirs(workspace, exist_ok=True)
    log.info("Workspace: %s", workspace)

    records_by_country: dict[str, dict[str, dict]] = {}
    indexes_by_country: dict[str, dict[str, Coordinate]] = {}
    no_pdf: list[str] = []
    fetch_errors: list[str] = []

    for code in codes:
        if cfg.dry_run:
            recs = _fixture_records() if code == "lf" else {}
            records_by_country[code] = recs
            indexes_by_country[code] = _fixture_index(recs)
            log.info("[%s] dry-run: %d fixture records", code, len(recs))
        else:
            log.info("[%s] retrieving + parsing charts ...", code)
            recs, npdf, ferr = _collect_records_live(
                code, workspace, keep_intermediates=cfg.keep_intermediates,
                reparse_only=cfg.reparse_only,
            )
            log.info("[%s] parsed %d aerodromes (%d no-pdf, %d fetch errors)",
                     code, len(recs), len(npdf), len(ferr))
            log.info("[%s] fetching OpenAIP coordinates ...", code)
            indexes_by_country[code] = _fetch_index_live(code) if recs else {}
            log.info("[%s] OpenAIP: %d aerodromes indexed", code,
                     len(indexes_by_country[code]))
            records_by_country[code] = recs
            no_pdf += npdf
            fetch_errors += ferr

    # Advisory LLM extraction-QA pass (ADR-0003, R4.10). Report-only: it never
    # touches the dataset, guard, or exit code. Runs over ALL parsed records.
    if cfg.llm_review:
        _run_llm_review(records_by_country, workspace, cfg.llm_model or None)

    log.info("Assembling normalized dataset ...")
    asm = assemble.assemble(
        records_by_country, indexes_by_country, airac_cycle=cycle, effective_date=eff
    )
    dataset = asm.dataset
    feature_count = dataset["metadata"]["feature_count"]
    log.info("Assembled %d AVGAS features (%d non-AVGAS, %d dropped for missing coords)",
             feature_count, len(asm.non_avgas), len(asm.unmatched_coords))
    if asm.rejected_countries:
        log.warning("Rejected providers: %s", asm.rejected_countries)

    # Never-worse guard. In dry-run the fixture set is deliberately tiny, so the
    # production floor doesn't apply unless the caller set a custom one.
    floor = cfg.floor
    if cfg.dry_run and cfg.floor == validate.DEFAULT_FLOOR:
        floor = 1
    guard = validate.check(
        feature_count, previous_count,
        floor=floor, max_drop=cfg.max_drop, override=cfg.override_guard,
    )

    # Build the report data (unparseable = unknown records; no_fuel = nil records).
    unparseable, no_fuel = _split_non_avgas(records_by_country)
    rdata = report.ReportData(
        cycle=cycle,
        effective_date=eff,
        published_count=feature_count,
        guard_ok=guard.ok,
        guard_reason=guard.reason,
        no_pdf=sorted(no_pdf),
        unparseable=unparseable,
        no_fuel=no_fuel,
        unmatched_coords=asm.unmatched_coords,
        fetch_errors=sorted(fetch_errors),
        rejected_countries=asm.rejected_countries,
    )
    report_path = os.path.join(workspace, "report.md")
    report_md = report.write_report(rdata, report_path)
    log.info("Report written: %s", report_path)

    if guard.ok:
        log.info("Never-worse guard: PASS")
    else:
        log.error("Never-worse guard: FAIL — %s", guard.reason)
        return RunOutcome(
            status="failed", cycle=cycle, feature_count=feature_count,
            report_md=report_md, detail=guard.reason, report_data=rdata,
        )

    if cfg.local:
        manifest = _write_local(cfg, dataset, cycle)
        log.info("Local dataset + manifest written under web/data/ (cycle %s)", cycle)
        return RunOutcome(
            status="local", cycle=cycle, feature_count=feature_count,
            manifest=manifest, report_md=report_md, report_data=rdata,
        )

    if cfg.dry_run:
        # Built and validated, but neither local nor published.
        log.info("Dry-run complete: dataset built and validated, not published")
        return RunOutcome(
            status="skipped", cycle=cycle, feature_count=feature_count,
            report_md=report_md, detail="dry-run: not published", report_data=rdata,
        )

    # Publish a Release + regenerate the manifest.
    if gh is None:
        gh = _build_github_client()
    log.info("Publishing Release %s ...", publish.tag_for_cycle(cycle))
    result = publish.publish_cycle(cycle, dataset, gh)
    # Ship the manifest with the site: write web/index.json so the deploy step
    # picks it up. Cycle datasets live in Releases (their URLs are in here).
    _write_site_manifest(cfg, result.manifest)
    log.info("Published %s; manifest lists %d cycle(s), latest=%s",
             result.published_tag, len(result.manifest.get("cycles", [])),
             result.manifest.get("latest"))
    return RunOutcome(
        status="published", cycle=cycle, feature_count=feature_count,
        manifest=result.manifest, report_md=report_md, report_data=rdata,
    )


def _split_non_avgas(records_by_country: dict[str, dict[str, dict]]) -> tuple[list[str], list[str]]:
    unparseable: list[str] = []
    no_fuel: list[str] = []
    for recs in records_by_country.values():
        for icao, rec in recs.items():
            if rec["fuel_state"] == "unknown":
                unparseable.append(icao)
            elif rec["fuel_state"] == "nil":
                no_fuel.append(icao)
    return sorted(unparseable), sorted(no_fuel)


def _write_local(cfg: RunConfig, dataset: dict, cycle: str) -> dict:
    """Write dataset + a LOCAL manifest into web/data/ for local preview."""
    web_data = cfg.web_data_dir or os.path.join(_repo_root(), "web", "data")
    os.makedirs(web_data, exist_ok=True)

    dataset_name = f"dataset-{cycle}.geojson"
    with open(os.path.join(web_data, dataset_name), "w", encoding="utf-8") as fh:
        json.dump(dataset, fh, ensure_ascii=False)

    from avgasmap import schema

    manifest = {
        "latest": cycle,
        "cycles": [
            {
                "cycle": cycle,
                "effective_date": dataset["metadata"]["effective_date"],
                "schema_version": schema.SCHEMA_VERSION,
                "url": dataset_name,  # relative to web/data/, local file
            }
        ],
    }
    with open(os.path.join(web_data, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return manifest


def _write_site_manifest(cfg: RunConfig, manifest: dict) -> None:
    """Write the published manifest to web/index.json for the Pages deploy."""
    web_dir = os.path.dirname(cfg.web_data_dir) if cfg.web_data_dir else os.path.join(_repo_root(), "web")
    os.makedirs(web_dir, exist_ok=True)
    with open(os.path.join(web_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)


def _build_github_client() -> publish.GitHubReleases:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        raise RuntimeError("GITHUB_REPOSITORY and GITHUB_TOKEN are required to publish.")
    return publish.RestGitHubReleases(repo, token)
