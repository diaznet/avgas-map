"""Tiny CLI for the AIRAC gate used by CI.

`python pipeline/avgasmap/airac_cli.py --today` prints the current cycle id if
today (UTC) is an AIRAC effective date, otherwise prints nothing and exits 0.
Kept dependency-free and runnable from the repo root.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avgasmap import airac  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AIRAC gate helper")
    p.add_argument("--today", action="store_true", help="Print cycle id if today is an AIRAC date")
    args = p.parse_args(argv)

    today = datetime.now(timezone.utc).date()
    cid = airac.is_airac_today(today)
    if args.today and cid:
        print(cid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
