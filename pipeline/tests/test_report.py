"""Tests for the processing report."""

from __future__ import annotations

from avgasmap.report import ReportData, render_markdown, write_report


def _data(**kw) -> ReportData:
    base = dict(cycle="2609", effective_date="2026-09-03", published_count=296)
    base.update(kw)
    return ReportData(**base)


def test_render_includes_headline_numbers():
    md = render_markdown(_data())
    assert "cycle 2609" in md
    assert "2026-09-03" in md
    assert "296" in md
    assert "PASS" in md


def test_render_shows_guard_failure_reason():
    md = render_markdown(_data(guard_ok=False, guard_reason="below floor"))
    assert "FAIL" in md
    assert "below floor" in md


def test_render_lists_each_skip_category():
    md = render_markdown(
        _data(
            no_pdf=["LFBC", "LFBM"],
            unparseable=["LFRJ", "LFRL"],
            no_fuel=["LFNL"],
            unmatched_coords=["LFZZ"],
            fetch_errors=["LFXX: timeout"],
        )
    )
    assert "LFBC, LFBM" in md
    assert "LFRJ, LFRL" in md
    assert "LFNL" in md
    assert "LFZZ" in md
    assert "LFXX: timeout" in md


def test_render_shows_rejected_providers():
    md = render_markdown(_data(rejected_countries={"lf": "schema error at LFAV"}))
    assert "Rejected providers" in md
    assert "lf" in md and "schema error" in md


def test_empty_categories_show_none():
    md = render_markdown(_data())
    assert "_none_" in md


def test_write_report_creates_file(tmp_path):
    path = tmp_path / "out" / "report.md"
    md = write_report(_data(), str(path))
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == md


def test_write_report_appends_to_github_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    summary.write_text("existing\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    write_report(_data(), str(tmp_path / "report.md"))
    content = summary.read_text(encoding="utf-8")
    assert content.startswith("existing")
    assert "cycle 2609" in content
