"""AIRAC cycle date arithmetic and the pipeline's today-is-AIRAC gate.

AIRAC cycles are a fixed 28-day period anchored to a known epoch. We compute
everything from that epoch — no stored calendar (see design.md). 28 days is a
whole number of weeks, so calendar/leap-year shifts are absorbed by date math.

Epoch: cycle 2001 (the 1st cycle of 2020) became effective 2020-01-02. Every
subsequent cycle is exactly 28 days later. Cycle id is `YYNN` = the year's last
two digits + the 1-based ordinal of the cycle within that year.

Verified against the public AIRAC schedule (see tests).
"""

from __future__ import annotations

from datetime import date, timedelta

CYCLE_LENGTH_DAYS = 28
# Anchor: first cycle of 2020.
_EPOCH = date(2020, 1, 2)
_EPOCH_YEAR = 2020


def effective_date(cycle_id: str) -> date:
    """Return the effective date for a `YYNN` cycle id.

    Computed by finding the first cycle of the cycle's year (the first cycle
    whose effective date falls in that calendar year) and stepping NN-1 cycles.
    """
    if not (len(cycle_id) == 4 and cycle_id.isdigit()):
        raise ValueError(f"cycle id must be 4 digits YYNN, got {cycle_id!r}")
    yy = int(cycle_id[:2])
    nn = int(cycle_id[2:])
    if nn < 1:
        raise ValueError(f"cycle ordinal must be >= 1, got {nn}")
    year = 2000 + yy
    first = _first_cycle_date_of_year(year)
    return first + timedelta(days=(nn - 1) * CYCLE_LENGTH_DAYS)


def _first_cycle_date_of_year(year: int) -> date:
    """Effective date of the first AIRAC cycle whose date is in `year`.

    The first cycle of a year is the earliest cycle boundary on/after Jan 1.
    """
    jan1 = date(year, 1, 1)
    delta_days = (jan1 - _EPOCH).days
    # Number of whole cycles since epoch, rounded up to the first boundary >= Jan 1.
    n = -(-delta_days // CYCLE_LENGTH_DAYS)  # ceil division
    return _EPOCH + timedelta(days=n * CYCLE_LENGTH_DAYS)


def cycle_for_date(d: date) -> str:
    """Return the `YYNN` id of the cycle in force on date `d`.

    The in-force cycle is the one whose effective date is the latest boundary
    on or before `d`.
    """
    delta_days = (d - _EPOCH).days
    n = delta_days // CYCLE_LENGTH_DAYS  # cycles since epoch (0-based)
    boundary = _EPOCH + timedelta(days=n * CYCLE_LENGTH_DAYS)
    year = boundary.year
    first = _first_cycle_date_of_year(year)
    ordinal = (boundary - first).days // CYCLE_LENGTH_DAYS + 1
    return f"{year % 100:02d}{ordinal:02d}"


def is_effective_date(d: date) -> bool:
    """True if `d` is exactly an AIRAC cycle boundary (an effective date)."""
    return (d - _EPOCH).days % CYCLE_LENGTH_DAYS == 0


def is_airac_today(today: date | None = None) -> str | None:
    """Return the cycle id if `today` is an AIRAC effective date, else None."""
    today = today or date.today()
    if is_effective_date(today):
        return cycle_for_date(today)
    return None


def current_cycle(today: date | None = None) -> str:
    """Return the `YYNN` cycle in force on `today` (defaults to today)."""
    return cycle_for_date(today or date.today())
