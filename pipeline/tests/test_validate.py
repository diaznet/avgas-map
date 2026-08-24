"""Tests for the never-worse guard."""

from __future__ import annotations

from avgasmap.validate import DEFAULT_FLOOR, check


def test_healthy_dataset_passes():
    r = check(new_count=300, previous_count=296)
    assert r.ok


def test_below_floor_aborts_even_with_prior():
    r = check(new_count=5, previous_count=296)
    assert not r.ok
    assert "floor" in r.reason


def test_below_floor_aborts_on_first_run():
    r = check(new_count=0, previous_count=None)
    assert not r.ok


def test_first_run_above_floor_passes():
    r = check(new_count=250, previous_count=None)
    assert r.ok


def test_large_relative_drop_aborts():
    # 296 -> 210 is a ~29% drop, exceeds 20% (and 210 is above the 200 floor).
    r = check(new_count=210, previous_count=296, floor=200, max_drop=0.20)
    assert not r.ok
    assert "%" in r.reason


def test_small_drop_within_threshold_passes():
    # 296 -> 250 is ~15.5% drop, within 20%.
    r = check(new_count=250, previous_count=296, floor=200, max_drop=0.20)
    assert r.ok


def test_override_bypasses_relative_but_not_floor():
    # A big legitimate drop, but still above the floor -> override allows it.
    r = check(new_count=210, previous_count=296, floor=200, override=True)
    assert r.ok
    # Override does NOT rescue a below-floor count.
    r2 = check(new_count=10, previous_count=296, floor=200, override=True)
    assert not r2.ok


def test_growth_always_passes():
    r = check(new_count=500, previous_count=296)
    assert r.ok


def test_default_floor_value():
    assert DEFAULT_FLOOR == 200
