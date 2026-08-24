"""Grading tests (parent spec 8, plan Tasks 21-22).

Every case here fails silently in production. A mis-graded cell does not raise or
look broken -- it renders as a perfectly plausible colour, and the only way to
notice would be to know the right answer for that exact season and check by hand.
So the assertions are the only thing standing between a sign error and a table
that quietly grades the worst seasons best.
"""

import json
from pathlib import Path

import polars as pl
import pytest

from ingest import grade
from ingest.registry import STATS, Tier

THRESHOLDS_PATH = Path(__file__).parents[2] / "config" / "thresholds_v2025.json"


def ladder(direction: str = "higher_is_better", prorate: str = "none") -> dict:
    """A synthetic stat config: record 100, then 90/80/70/60/50."""
    if direction == "higher_is_better":
        rungs, op = [("elite", 90), ("good", 80), ("average", 70), ("below", 60), ("poor", 50)], "gte"
    else:
        rungs, op = [("elite", 10), ("good", 20), ("average", 30), ("below", 40), ("poor", 50)], "lte"
    tiers = [{"tier": "record", "op": "gte", "threshold": 100, "prorate": prorate}]
    tiers += [{"tier": t, "op": op, "threshold": v, "prorate": prorate} for t, v in rungs]
    tiers.append({"tier": "worst", "op": "always", "threshold": None, "prorate": prorate})
    return {"direction": direction, "tiers": tiers}


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,op,threshold,expected",
    [
        (100, "gte", 100, True),
        (99.9, "gte", 100, False),
        (100, "gt", 100, False),
        (2, "lte", 2, True),
        (3, "lte", 2, False),
        (1, "lt", 2, True),
        (0, "always", None, True),
        (-5, "always", None, True),
    ],
)
def test_compare(value, op, threshold, expected):
    assert grade.compare(value, op, threshold) is expected


def test_compare_rejects_unknown_operator():
    with pytest.raises(grade.GradingError, match="unknown threshold operator"):
        grade.compare(1, "approximately", 1)


# ---------------------------------------------------------------------------
# grade_record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (150, Tier.RECORD),
        (100, Tier.RECORD),
        (99, Tier.ELITE),
        (80, Tier.GOOD),
        (70, Tier.AVERAGE),
        (60, Tier.BELOW),
        (50, Tier.POOR),
        (49, Tier.WORST),
        (0, Tier.WORST),
    ],
)
def test_first_matching_tier_wins(value, expected):
    assert grade.grade_record(value, 17, ladder(), 17) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (200, Tier.RECORD),   # most interceptions ever -- an infamy record
        (5, Tier.ELITE),      # fewest
        (20, Tier.GOOD),
        (50, Tier.POOR),
        (51, Tier.WORST),
    ],
)
def test_lower_is_better_grades_with_lte(value, expected):
    assert grade.grade_record(value, 17, ladder("lower_is_better"), 17) is expected


def test_negative_value_grades_to_bottom_not_none():
    """rush_yards_per_att of -0.5 is a real, gradeable, bad number.

    Returning None here would be indistinguishable from a sentinel, and the cell
    would render as "no data" for a QB who was in fact sacked into the ground.
    """
    assert grade.grade_record(-0.5, 17, ladder(), 17) is Tier.WORST


@pytest.mark.parametrize("value", [None, "Perfect", "Incalculable", "Not Recorded"])
def test_sentinels_are_never_graded(value):
    assert grade.grade_record(value, 17, ladder(), 17) is None


def test_zero_games_returns_none_and_does_not_raise():
    assert grade.grade_record(4000, 0, ladder(prorate="games"), 17) is None
    assert grade.grade_record(4000, None, ladder(prorate="games"), 17) is None


def test_zero_games_still_grades_an_unprorated_stat():
    """A rate needs no games count, so nothing divides and nothing fails."""
    assert grade.grade_record(95, 0, ladder(), 17) is Tier.ELITE


@pytest.mark.parametrize("games", [1, 2, 4, 8, 12, 16, 17])
@pytest.mark.parametrize(
    "full_season_value,expected",
    [(105, Tier.RECORD), (95, Tier.ELITE), (85, Tier.GOOD),
     (75, Tier.AVERAGE), (65, Tier.BELOW), (55, Tier.POOR), (45, Tier.WORST)],
)
def test_prorate_is_linear(games, full_season_value, expected):
    """A player ON PACE for X grades the same at any point in the season.

    This is the property that makes record mode an on-pace indicator (design
    10.5). It has to hold at every tier and every games count, because a break in
    it shows up as a cell that changes colour when the player's pace did not --
    which looks like normal week-to-week variation and would never be questioned.
    """
    config = ladder(prorate="games")
    on_pace_value = full_season_value * games / 17
    assert grade.grade_record(on_pace_value, games, config, 17) is expected


def test_prorate_scales_the_threshold_not_the_value():
    """8 games at 2,400 yards is on pace for 5,100 -- a record pace."""
    config = ladder(prorate="games")
    assert grade.grade_record(48, 8, config, 17) is Tier.RECORD   # 100/17*8 = 47.1
    assert grade.grade_record(46, 8, config, 17) is Tier.ELITE    # 90/17*8 = 42.4


def test_missing_catch_all_raises_rather_than_returning_none():
    """A silent None here would look exactly like a sentinel."""
    config = ladder()
    config["tiers"] = [t for t in config["tiers"] if t["tier"] != "worst"]
    with pytest.raises(grade.GradingError, match="missing its 'worst' catch-all"):
        grade.grade_record(0, 17, config, 17)


# ---------------------------------------------------------------------------
# grade_record against the real generated thresholds
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_thresholds() -> dict:
    return json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "stat,value,games,expected",
    [
        # Peyton Manning 2013: 5,477 yards and 55 TDs over 16 games.
        ("passing_tds", 55, 16, Tier.RECORD),
        ("passing_yards", 5477, 16, Tier.RECORD),
        # Lamar Jackson 2019: 1,206 rushing yards on 176 carries over 15 games.
        ("rushing_yards", 1206, 15, Tier.RECORD),
        ("rushing_attempts", 176, 15, Tier.RECORD),
        # A replacement-level line grades at the bottom (parent 11.4).
        ("passing_yards", 400, 17, Tier.WORST),
        ("passer_rating", 45.0, 17, Tier.WORST),
    ],
)
def test_known_seasons_against_shipped_thresholds(real_thresholds, stat, value, games, expected):
    view = real_thresholds["views"]["season_REG"]
    assert grade.grade_record(
        value, games, view["stats"][stat], view["prorate_denominator_games"]
    ) is expected


def test_every_shipped_stat_grades_without_raising(real_thresholds):
    """Exercises every tier of every stat in every view.

    Cheap insurance that the shipped document has no operator or catch-all the
    grader cannot handle -- the failure it prevents is a crash mid-backfill.
    """
    for view_name, view in real_thresholds["views"].items():
        denominator = view["prorate_denominator_games"]
        for name, config in view["stats"].items():
            for probe in (-10, 0, 0.5, 50, 1_000_000):
                tier = grade.grade_record(probe, 16, config, denominator)
                assert tier is None or isinstance(tier, Tier), f"{view_name}.{name}"


# ---------------------------------------------------------------------------
# performance_percentiles
# ---------------------------------------------------------------------------


def frame(values, qualified, season=2025) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season": [season] * len(values),
            "season_type": ["REG"] * len(values),
            "passing_yards": values,
            "interceptions": values,
            "is_qualified": qualified,
        }
    )


PARTITION = ["season", "season_type"]


def test_unqualified_row_still_receives_a_percentile():
    """Placed on the scale without helping to define it.

    Filtering the frame to qualified rows is the obvious implementation and it
    silently drops these rows entirely -- they would render ungraded forever.
    """
    df = frame([4000, 3000, 2000, 50], [True, True, True, False])
    out = grade.performance_percentiles(df, STATS["passing_yards"], PARTITION)
    assert out[3] is not None
    assert 0.0 <= out[3] <= 1.0


def test_unqualified_outlier_does_not_move_a_qualified_percentile():
    """The single easiest thing in this project to get subtly wrong.

    Both implementations produce plausible numbers, so the only way to tell them
    apart is to add a garbage row and check that nothing moved.
    """
    base = frame([4000, 3000, 2000], [True, True, True])
    polluted = frame([4000, 3000, 2000, 1, 2, 3], [True, True, True, False, False, False])

    a = grade.performance_percentiles(base, STATS["passing_yards"], PARTITION)
    b = grade.performance_percentiles(polluted, STATS["passing_yards"], PARTITION)
    assert list(a) == list(b)[:3]


def test_lower_is_better_inverts():
    """Fewest interceptions must score highest, not lowest."""
    df = frame([2, 10, 30], [True, True, True])
    out = grade.performance_percentiles(df, STATS["interceptions"], PARTITION)
    assert out[0] > out[1] > out[2]
    assert out[0] == pytest.approx(1.0)


def test_higher_is_better_orders_upward():
    df = frame([4000, 3000, 2000], [True, True, True])
    out = grade.performance_percentiles(df, STATS["passing_yards"], PARTITION)
    assert out[0] > out[1] > out[2]
    assert out[0] == pytest.approx(1.0)


def test_sentinels_receive_no_percentile():
    df = frame([4000, None, 2000], [True, True, True])
    out = grade.performance_percentiles(df, STATS["passing_yards"], PARTITION)
    assert out[1] is None
    assert out[0] is not None and out[2] is not None


def test_percentiles_stay_in_range():
    df = frame([4000, 3000, 2000, 500, 50], [True, True, True, True, False])
    out = grade.performance_percentiles(df, STATS["passing_yards"], PARTITION)
    assert all(0.0 <= v <= 1.0 for v in out if v is not None)


def test_partitions_are_independent():
    """A 2024 season must not be ranked against 2025."""
    df = pl.concat([frame([4000, 2000], [True, True], 2024),
                    frame([500, 100], [True, True], 2025)])
    out = grade.performance_percentiles(df, STATS["passing_yards"], PARTITION)
    assert out[0] == pytest.approx(1.0)
    assert out[2] == pytest.approx(1.0)  # best of 2025, despite being tiny


def test_cohort_of_only_unqualified_rows_yields_nulls():
    """No scale exists, so no row can be placed on one."""
    df = frame([100, 200], [False, False])
    out = grade.performance_percentiles(df, STATS["passing_yards"], PARTITION)
    assert out.null_count() == 2
