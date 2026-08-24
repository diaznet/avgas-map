"""Processing report — human-readable diagnostics for a pipeline run.

Records what was published and, crucially, what was skipped and why: aerodromes
with no VAC, unparseable charts (unknown), fuel records with no OpenAIP
coordinate match, and any provider rejected wholesale. Written to a workspace
file and appended to the GitHub Actions job summary. NEVER committed (R7.6).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ReportData:
    cycle: str
    effective_date: str
    published_count: int = 0
    guard_ok: bool = True
    guard_reason: str = ""
    no_pdf: list[str] = field(default_factory=list)          # aerodromes with no VAC
    unparseable: list[str] = field(default_factory=list)     # fuel_state 'unknown'
    no_fuel: list[str] = field(default_factory=list)         # fuel_state 'nil'
    unmatched_coords: list[str] = field(default_factory=list)  # AVGAS but no coords
    fetch_errors: list[str] = field(default_factory=list)    # retrieval errors
    rejected_countries: dict[str, str] = field(default_factory=dict)


def _section(title: str, items: list[str]) -> list[str]:
    lines = [f"### {title} ({len(items)})", ""]
    if items:
        lines += [", ".join(items), ""]
    else:
        lines += ["_none_", ""]
    return lines


def render_markdown(data: ReportData) -> str:
    """Render the report as Markdown."""
    lines: list[str] = [
        f"# AVGAS-Map processing report — cycle {data.cycle}",
        "",
        f"- Effective date: **{data.effective_date}**",
        f"- Published AVGAS aerodromes: **{data.published_count}**",
        f"- Never-worse guard: **{'PASS' if data.guard_ok else 'FAIL'}**"
        + (f" — {data.guard_reason}" if data.guard_reason else ""),
        "",
    ]
    if data.rejected_countries:
        lines += ["### Rejected providers", ""]
        for cc, reason in sorted(data.rejected_countries.items()):
            lines.append(f"- **{cc}**: {reason}")
        lines.append("")
    lines += _section("Aerodromes with no VAC PDF", data.no_pdf)
    lines += _section("Unparseable charts (fuel state unknown)", data.unparseable)
    lines += _section("Explicit no-fuel (NIL)", data.no_fuel)
    lines += _section("AVGAS aerodromes dropped (no OpenAIP coordinate)", data.unmatched_coords)
    lines += _section("Fetch errors", data.fetch_errors)
    return "\n".join(lines).rstrip() + "\n"


def write_report(data: ReportData, workspace_path: str) -> str:
    """Write the report to `workspace_path` and append to the GH job summary.

    Returns the rendered markdown. The workspace file is a build artifact, never
    committed.
    """
    md = render_markdown(data)
    os.makedirs(os.path.dirname(os.path.abspath(workspace_path)), exist_ok=True)
    with open(workspace_path, "w", encoding="utf-8") as fh:
        fh.write(md)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(md)
        except OSError:
            pass  # summary is best-effort; never fail the run over it
    return md
