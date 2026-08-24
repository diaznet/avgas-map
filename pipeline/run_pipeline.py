"""AVGAS-Map pipeline entry point (CLI).

Full orchestration is wired in a later task; this provides the stable CLI
surface and the credential/.env loading contract from the start.

Credential contract (portable, OS-agnostic): the pipeline reads AUTOROUTER_USER
and AUTOROUTER_PASS from environment variables only. In CI these come from
GitHub Actions secrets. Locally, they can be exported in the shell or placed in
a gitignored `.env` at the repository root (loaded here if python-dotenv is
installed and a .env exists). No OS-specific credential store is used.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _load_dotenv_if_present() -> None:
    """Load a repo-root .env into the environment if python-dotenv is available.

    Optional and local-only: absence of python-dotenv or of a .env file is not
    an error. CI never relies on this.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # Repo root is the parent of the pipeline/ directory.
    repo_root = Path(__file__).resolve().parent.parent
    env_path = repo_root / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description="Generate the AVGAS-Map dataset for an AIRAC cycle.",
    )
    p.add_argument(
        "--country",
        action="append",
        metavar="CC",
        help="Restrict to specific country codes (repeatable). Default: all enabled.",
    )
    p.add_argument(
        "--cycle",
        metavar="YYNN",
        help="Force a specific AIRAC cycle id, bypassing the today-is-AIRAC gate.",
    )
    p.add_argument(
        "--local",
        action="store_true",
        help="Write dataset + local manifest into web/data/ instead of publishing a Release.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Build from fixtures with no network and no publish.",
    )
    p.add_argument(
        "--override-guard",
        action="store_true",
        help="Bypass the relative-drop guard for a legitimately large change "
             "(the absolute floor is always enforced).",
    )
    p.add_argument(
        "--workspace",
        metavar="DIR",
        default="",
        help="Working directory for intermediate files + report.md "
             "(default: a temp dir).",
    )
    p.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="Persist each chart's converted markdown to "
             "<workspace>/md/<code>/<ICAO>.md for debugging (default off; "
             "workspace-only, never committed).",
    )
    p.add_argument(
        "--reparse-only",
        action="store_true",
        help="Rebuild the dataset from charts already in the workspace, skipping "
             "retrieval (re-apply a parser fix without re-downloading). Requires "
             "--workspace; not usable with --dry-run.",
    )
    p.add_argument(
        "--llm-review",
        action="store_true",
        help="Advisory LLM extraction-QA pass over all parsed records (local "
             "Ollama). Report-only: writes suggestions.json, never changes the "
             "dataset, guard, or code (ADR-0003). Opt-in; off by default.",
    )
    p.add_argument(
        "--llm-model",
        default="",
        help="Override the pinned LLM-review model (default qwen3:8b).",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose (DEBUG) logging.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_if_present()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # --reparse-only rebuilds from cached charts: it needs a workspace to read
    # them from, and makes no sense with --dry-run (which uses fixtures).
    if args.reparse_only:
        if args.dry_run:
            parser.error("--reparse-only cannot be combined with --dry-run")
        if not args.workspace:
            parser.error("--reparse-only requires --workspace <DIR> (where the "
                         "charts were previously downloaded)")

    # Import here so --help works even before deps are installed.
    from avgasmap.logconfig import configure
    from avgasmap.pipeline import RunConfig, run

    configure(verbose=args.verbose)

    cfg = RunConfig(
        countries=args.country,
        cycle=args.cycle,
        local=args.local,
        dry_run=args.dry_run,
        override_guard=args.override_guard,
        workspace=args.workspace,
        keep_intermediates=args.keep_intermediates,
        reparse_only=args.reparse_only,
        llm_review=args.llm_review,
        llm_model=args.llm_model,
    )
    try:
        outcome = run(cfg)
    except KeyboardInterrupt:
        print("\nInterrupted by user — nothing was published.", file=sys.stderr)
        return 130  # conventional exit code for SIGINT

    print(f"[{outcome.status}] cycle={outcome.cycle} features={outcome.feature_count}"
          + (f" — {outcome.detail}" if outcome.detail else ""))
    if outcome.status == "local" and outcome.manifest:
        print("Local manifest written to web/data/index.json. "
              "Serve web/ (e.g. `python -m http.server` from web/) to preview.")
    # A failed guard is a non-zero exit (CI aborts, prior site stays live).
    return 1 if outcome.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
