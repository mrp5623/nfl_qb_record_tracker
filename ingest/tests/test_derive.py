"""Tests for derive.py -- required by D12: known correct answers, and this module
gets edited across Tasks 10-13.

Expected values are real, verified against the original sheet's cached 2025
week 18 data or against published records.
"""

import pytest

from ingest.derive import (
    Sentinel,
    any_a,
    completion_pct,
    int_pct,
    passer_rating,
    rush_yards_per_att,
    sack_pct,
    sentinels_for_row,
    snap_pct,
    td_int_ratio,
    td_pct,
    total_tds,
    total_yards,
    yards_per_attempt,
    yards_per_completion,
)


def _rounded(value: float | None, places: int = 1) -> float:
    """Round for comparison, asserting the value exists first.

    The derive functions return `float | None`, and `round()` rejects None. The
    assert both satisfies the type checker and turns an unexpected None into a
    clear failure instead of a TypeError.
    """
    assert value is not None, "expected a number, got None"
    return round(value, places)


# --- passer rating: hand-verified against the sheet's cached week 18 values ---

@pytest.mark.parametrize(
    "cmp_, att, yds, td, ints, expected, note",
    [
        (27, 42, 331, 1, 1, 86.5, "Goff, no clamping"),
        (22, 29, 259, 4, 0, 142.1, "Trubisky, c clamps"),
        (20, 44, 136, 0, 1, 43.4, "Lance, low end"),
        (20, 25, 350, 4, 0, 158.3, "perfect: all four clamp"),
    ],
)
def test_passer_rating(cmp_, att, yds, td, ints, expected, note):
    assert _rounded(passer_rating(cmp_, att, yds, td, ints)) == expected, note


def test_passer_rating_cannot_exceed_maximum():
    # Absurd inputs must still clamp to the 158.3 ceiling.
    assert _rounded(passer_rating(50, 50, 2000, 50, 0)) == 158.3


def test_passer_rating_no_attempts_is_none():
    assert passer_rating(0, 0, 0, 0, 0) is None


# --- rate stats: real week 18 2025 values ---

@pytest.mark.parametrize(
    "sacks, att, expected, who",
    [(6, 31, 16.2, "Brissett"), (2, 42, 4.5, "Goff"), (1, 34, 2.9, "Leonard"), (0, 35, 0.0, "Young")],
)
def test_sack_pct(sacks, att, expected, who):
    assert _rounded(sack_pct(sacks, att)) == expected, who


@pytest.mark.parametrize(
    "func, args, expected",
    [
        (completion_pct, (27, 42), 64.3),
        (yards_per_completion, (331, 27), 12.3),
        (yards_per_attempt, (331, 42), 7.9),
        (td_pct, (1, 42), 2.4),
        (int_pct, (1, 42), 2.4),
        (td_int_ratio, (2, 1), 2.0),
        (rush_yards_per_att, (20, 1), 20.0),
    ],
)
def test_rate_stats(func, args, expected):
    assert _rounded(func(*args)) == expected


def test_negative_rushing_is_kept_not_nulled():
    # Bryce Young, week 18 2025: -1 yard on 2 carries.
    assert rush_yards_per_att(-1, 2) == -0.5
    assert total_yards(266, -1) == 265


# --- zero denominators return None, never a substitute number ---

@pytest.mark.parametrize(
    "func, args",
    [
        (completion_pct, (0, 0)),
        (yards_per_completion, (0, 0)),
        (yards_per_attempt, (0, 0)),
        (td_pct, (0, 0)),
        (int_pct, (0, 0)),
        (td_int_ratio, (3, 0)),      # no interceptions -> Perfect sentinel
        (sack_pct, (0, 0)),
        (rush_yards_per_att, (0, 0)),
        (any_a, (0, 0, 0, 0, 0, 0)),
        (snap_pct, (0, 0)),
    ],
)
def test_zero_denominator_returns_none(func, args):
    assert func(*args) is None


# --- ANY/A and totals ---

def test_any_a():
    # Goff week 18 2025, real values from the pipeline: 331 yds, 1 TD, 1 INT,
    # 2 sacks for 15 yards, 42 attempts.
    # (331 + 20*1 - 45*1 - 15) / (42 + 2) = 291 / 44
    assert _rounded(any_a(331, 1, 1, 15, 42, 2), 2) == 6.61


def test_any_a_expects_positive_sack_yards():
    """nflverse stores sack yards negative; load.py flips the sign on ingest.

    If that ever regresses, ANY/A silently *adds* the yards instead of
    subtracting them and every value comes out too high.
    """
    correct = any_a(331, 1, 1, 15, 42, 2)
    if_sign_regressed = any_a(331, 1, 1, -15, 42, 2)
    assert correct < if_sign_regressed # pyright: ignore[reportOperatorIssue]


def test_any_a_subtracts_sack_yards():
    with_sacks = any_a(300, 2, 0, 30, 40, 5)
    without = any_a(300, 2, 0, 0, 40, 5)
    assert with_sacks < without # pyright: ignore[reportOperatorIssue]


def test_totals():
    assert total_tds(4, 1) == 5
    assert total_yards(331, 0) == 331


# --- sentinels (Task 13) -----------------------------------------------------

PLAYED = {
    "attempts": 42, "completions": 27, "interceptions": 1,
    "sacks": 2, "rushing_attempts": 3, "team_offensive_snaps": 70,
}


def _with(**overrides) -> dict:
    return {**PLAYED, **overrides}


def test_perfect_when_no_interceptions():
    # Aaron Rodgers, week 18 2025: 0 INTs.
    s = sentinels_for_row(_with(interceptions=0), 2025)
    assert s["td_int_ratio"] == Sentinel.PERFECT


def test_interception_thrown_means_no_sentinel():
    assert "td_int_ratio" not in sentinels_for_row(_with(interceptions=1), 2025)


def test_incalculable_without_carries():
    # Jared Goff, week 18 2025: 0 rushing attempts.
    s = sentinels_for_row(_with(rushing_attempts=0), 2025)
    assert s["rush_yards_per_att"] == Sentinel.INCALCULABLE


@pytest.mark.parametrize(
    "stat, season, expected_present",
    [
        ("qbr", 2005, True), ("qbr", 2006, False),
        # nflverse's 2012 snap asset is empty, so the gate is 2013 not 2012.
        ("snap_pct", 2011, True), ("snap_pct", 2012, True), ("snap_pct", 2013, False),
    ],
)
def test_era_gates(stat, season, expected_present):
    s = sentinels_for_row(PLAYED, season)
    if expected_present:
        assert s[stat] == Sentinel.NOT_RECORDED
    else:
        assert s.get(stat) != Sentinel.NOT_RECORDED


def test_not_recorded_is_distinct_from_incalculable():
    """The two must never collapse -- they render differently (parent §6.2)."""
    assert Sentinel.NOT_RECORDED != Sentinel.INCALCULABLE
    s = sentinels_for_row(_with(rushing_attempts=0), 2005)
    assert s["qbr"] == Sentinel.NOT_RECORDED
    assert s["rush_yards_per_att"] == Sentinel.INCALCULABLE


def test_no_attempts_is_incalculable_not_perfect():
    """A quarterback who never threw has zero interceptions, but there is
    nothing perfect about that. Documented tie-break: attempts win."""
    s = sentinels_for_row(_with(attempts=0, completions=0, interceptions=0), 2025)
    assert s["td_int_ratio"] == Sentinel.INCALCULABLE
