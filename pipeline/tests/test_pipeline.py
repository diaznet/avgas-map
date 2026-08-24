"""Tests for pipeline orchestration (offline: dry-run + injected gh/local)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from avgasmap import schema
from avgasmap.pipeline import RunConfig, run
from avgasmap.publish import Release
from tests.test_publish import MockGitHub


def test_dry_run_builds_valid_dataset_without_publish(tmp_path):
    cfg = RunConfig(cycle="2609", dry_run=True, workspace=str(tmp_path))
    out = run(cfg)
    assert out.status == "skipped"
    assert "dry-run" in out.detail
    assert out.feature_count > 0
    # Report written to workspace.
    assert (tmp_path / "report.md").is_file()


def test_dry_run_report_lists_unparseable_and_nil(tmp_path):
    cfg = RunConfig(cycle="2609", dry_run=True, workspace=str(tmp_path))
    out = run(cfg)
    rd = out.report_data
    # Fixtures include LFRJ (unknown) and LFNL (nil).
    assert "LFRJ" in rd.unparseable
    assert "LFNL" in rd.no_fuel


def test_skips_when_not_airac_date():
    # No cycle forced, and a non-AIRAC 'today'.
    cfg = RunConfig(dry_run=True)
    out = run(cfg, today=date(2025, 5, 16))  # day after 2505 effective
    assert out.status == "skipped"
    assert "AIRAC" in out.detail


def test_local_writes_web_data(tmp_path):
    web_data = tmp_path / "web" / "data"
    cfg = RunConfig(cycle="2609", dry_run=True, local=True,
                    workspace=str(tmp_path / "ws"), web_data_dir=str(web_data),
                    floor=1)
    out = run(cfg)
    assert out.status == "local"
    manifest = json.loads((web_data / "index.json").read_text(encoding="utf-8"))
    assert manifest["latest"] == "2609"
    dataset_file = web_data / manifest["cycles"][0]["url"]
    assert dataset_file.is_file()
    schema.validate_dataset(json.loads(dataset_file.read_text(encoding="utf-8")))


def test_guard_failure_aborts_publish(tmp_path):
    # Force a high floor so the small fixture dataset fails the guard.
    cfg = RunConfig(cycle="2609", dry_run=True, workspace=str(tmp_path), floor=9999)
    out = run(cfg)
    assert out.status == "failed"
    assert out.report_data.guard_ok is False


def test_publish_path_with_mock_github(tmp_path, monkeypatch):
    """Non-dry run with live-source functions monkeypatched to fixtures, and an
    injected mock GitHub client, exercises the publish + manifest path offline."""
    from avgasmap import pipeline
    from avgasmap.coordinates import Coordinate
    from avgasmap.providers.lf import LfParser
    from tests.fixtures.lf.cases import CASES

    parser = LfParser()
    recs = {icao: parser.parse_markdown(icao, c["markdown"]) for icao, c in CASES.items()}
    idx = {icao: Coordinate(lon=2.0, lat=48.0, name=f"{icao}") for icao in recs}

    monkeypatch.setattr(pipeline, "_collect_records_live",
                        lambda code, ws, keep_intermediates=False, reparse_only=False: (recs, [], []))
    monkeypatch.setattr(pipeline, "_fetch_index_live", lambda code: idx)

    gh = MockGitHub()
    cfg = RunConfig(cycle="2609", countries=["lf"], workspace=str(tmp_path), floor=1)
    out = run(cfg, gh=gh)

    assert out.status == "published"
    assert out.cycle == "2609"
    assert "airac-2609" in gh.uploads
    assert out.manifest["latest"] == "2609"
    # The published asset is a schema-valid dataset.
    published = json.loads(gh._assets["airac-2609"].decode())
    schema.validate_dataset(published)


def test_guard_failure_does_not_publish(tmp_path, monkeypatch):
    from avgasmap import pipeline
    from avgasmap.coordinates import Coordinate
    from avgasmap.providers.lf import LfParser
    from tests.fixtures.lf.cases import CASES

    parser = LfParser()
    recs = {icao: parser.parse_markdown(icao, c["markdown"]) for icao, c in CASES.items()}
    idx = {icao: Coordinate(lon=2.0, lat=48.0, name=icao) for icao in recs}
    monkeypatch.setattr(pipeline, "_collect_records_live",
                        lambda code, ws, keep_intermediates=False, reparse_only=False: (recs, [], []))
    monkeypatch.setattr(pipeline, "_fetch_index_live", lambda code: idx)

    gh = MockGitHub()
    cfg = RunConfig(cycle="2609", countries=["lf"], workspace=str(tmp_path), floor=9999)
    out = run(cfg, gh=gh)
    assert out.status == "failed"
    assert gh.uploads == []  # nothing published on guard failure


# --- fail-fast dependency check (R7.10) -------------------------------------

class _BrokenDepParser:
    """A provider whose chart-conversion dependency is missing/broken."""

    code = "zz"
    icao_pattern = r"^ZZ[A-Z]{2}$"
    openaip_iso = ["zz"]

    def check_dependencies(self) -> None:
        raise RuntimeError("cannot import frobnicator: no such module")

    def chart_paths(self, country_dir):  # pragma: no cover - never reached
        return {}

    def parse(self, icao, chart_path, md_dump_dir=""):  # pragma: no cover
        raise AssertionError("parse must not run when the dep check fails")


def _with_provider(parser):
    """Register a provider for the duration of a test, then clean up."""
    from avgasmap import providers
    providers.ensure_loaded()
    providers.register(parser)
    return providers


def test_live_run_aborts_when_dependency_missing(tmp_path):
    providers = _with_provider(_BrokenDepParser())
    try:
        cfg = RunConfig(cycle="2609", countries=["zz"], local=True,
                        workspace=str(tmp_path), floor=1)
        out = run(cfg)  # live (not dry-run) -> dependency check runs first
        assert out.status == "failed"
        assert "frobnicator" in out.detail  # names the failing dependency
        # Aborted before any workspace/retrieval work.
        assert not (tmp_path / "pdf").exists()
    finally:
        providers._REGISTRY.pop("zz", None)


def test_dry_run_skips_dependency_check(tmp_path):
    # Dry-run uses fixtures (no PDF conversion), so the broken dep check must NOT
    # run. (zz has no fixtures, so the run still ends 'skipped'/guard-related,
    # but never because of the dependency probe.)
    providers = _with_provider(_BrokenDepParser())
    try:
        cfg = RunConfig(cycle="2609", countries=["zz"], dry_run=True,
                        workspace=str(tmp_path), floor=1)
        out = run(cfg)
        assert "frobnicator" not in out.detail  # dep check was not invoked
    finally:
        providers._REGISTRY.pop("zz", None)


# --- --reparse-only (R7.12) -------------------------------------------------

def test_reparse_only_skips_retrieval(tmp_path, monkeypatch):
    from avgasmap import pipeline, retrieval
    import avgasmap.providers.lf as lf_pkg
    from tests.fixtures.lf.cases import CASES

    # Lay down a chart file so chart_paths finds it; retrieval must NOT run.
    pdf_dir = tmp_path / "pdf" / "lf"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "LFAV.pdf").write_bytes(b"%PDF-fake")

    def _boom(*a, **k):
        raise AssertionError("retrieval must be skipped in reparse-only mode")
    monkeypatch.setattr(retrieval, "retrieve_france", _boom)
    monkeypatch.setattr(lf_pkg, "_pdf_to_markdown", lambda path: CASES["LFAV"]["markdown"])

    recs, no_pdf, errs = pipeline._collect_records_live(
        "lf", str(tmp_path), reparse_only=True
    )
    assert "LFAV" in recs
    assert recs["LFAV"]["fuel_state"] == "available"
    assert no_pdf == [] and errs == []


def test_reparse_only_empty_workspace_is_surfaced(tmp_path, monkeypatch, caplog):
    from avgasmap import pipeline, retrieval
    monkeypatch.setattr(retrieval, "retrieve_france",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no retrieval")))
    # No pdf/lf directory at all -> no charts.
    with caplog.at_level("ERROR"):
        recs, no_pdf, errs = pipeline._collect_records_live(
            "lf", str(tmp_path), reparse_only=True
        )
    assert recs == {}
    assert any("no charts found" in r.message for r in caplog.records)


def test_cli_reparse_only_requires_workspace_and_rejects_dry_run():
    import run_pipeline
    with pytest.raises(SystemExit):
        run_pipeline.main(["--reparse-only"])  # no --workspace
    with pytest.raises(SystemExit):
        run_pipeline.main(["--reparse-only", "--workspace", ".", "--dry-run"])


def test_cli_writes_status_to_github_output(tmp_path, monkeypatch):
    # The CI workflow gates the Pages deploy on this status, so it must be
    # written to $GITHUB_OUTPUT. A non-published outcome must report as such.
    import run_pipeline
    from avgasmap import pipeline as pipeline_mod
    from avgasmap.pipeline import RunOutcome

    out_file = tmp_path / "gh_output"
    out_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    # run_pipeline.main does `from avgasmap.pipeline import run`, so patch it there.
    monkeypatch.setattr(pipeline_mod, "run",
                        lambda cfg: RunOutcome(status="skipped", cycle=None,
                                               detail="not an AIRAC date"))

    rc = run_pipeline.main(["--dry-run"])
    assert rc == 0  # skipped is not a failure
    assert "status=skipped" in out_file.read_text(encoding="utf-8")
