"""Tests for AIRAC date arithmetic and the today-gate.

Known effective dates verified against the public AIRAC schedule:
  - 2001 = 2020-01-02 (the epoch anchor)
  - 2505 = 2025-05-15
Every cycle is exactly 28 days after the previous.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from avgasmap import airac


@pytest.mark.parametrize(
    "cycle,expected",
    [
        ("2001", date(2020, 1, 2)),   # epoch
        ("2002", date(2020, 1, 30)),  # +28d
        ("2013", date(2020, 12, 3)),  # last cycle of 2020
        ("2101", date(2021, 1, 28)),  # first cycle of 2021
        ("2505", date(2025, 5, 15)),  # verified public date
    ],
)
def test_effective_date_known_cycles(cycle, expected):
    assert airac.effective_date(cycle) == expected


def test_consecutive_cycles_are_28_days_apart():
    d1 = airac.effective_date("2505")
    d2 = airac.effective_date("2506")
    assert (d2 - d1).days == 28


def test_cycle_for_date_roundtrips():
    for cycle in ["2001", "2101", "2313", "2505", "2609"]:
        eff = airac.effective_date(cycle)
        assert airac.cycle_for_date(eff) == cycle


def test_cycle_for_date_between_boundaries_returns_current():
    eff = airac.effective_date("2505")
    # A few days into the cycle still reports 2505.
    assert airac.cycle_for_date(eff + timedelta(days=10)) == "2505"
    # The day before the next boundary is still 2505.
    assert airac.cycle_for_date(eff + timedelta(days=27)) == "2505"
    # The next boundary flips to 2506.
    assert airac.cycle_for_date(eff + timedelta(days=28)) == "2506"


def test_is_airac_today_only_on_boundaries():
    eff = airac.effective_date("2505")
    assert airac.is_airac_today(eff) == "2505"
    assert airac.is_airac_today(eff + timedelta(days=1)) is None
    assert airac.is_airac_today(eff - timedelta(days=1)) is None


def test_current_cycle_defaults_and_value():
    assert airac.current_cycle(date(2025, 5, 20)) == "2505"


def test_cycle_id_format_is_yynn():
    cid = airac.cycle_for_date(date(2026, 9, 3))
    assert len(cid) == 4 and cid.isdigit()
    assert cid == "2609"


def test_invalid_cycle_id_rejected():
    with pytest.raises(ValueError):
        airac.effective_date("26-9")
    with pytest.raises(ValueError):
        airac.effective_date("2600")  # ordinal 0
