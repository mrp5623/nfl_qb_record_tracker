import json
from pathlib import Path

import pytest

from ingest.registry import (
    STATS,
    VIEWS,
    Direction,
    Kind,
    Prorate,
    Tier,
    legacy_tier_to_semantic,
    stats_for_view,
)


def test_qbr_is_absent_from_postseason_views():

    qbr = STATS["qbr"]
    assert "season_POST" not in qbr.views
    assert "week_POST" not in qbr.views, f"qbr should not be graded in the postseason, got {qbr.views}"


@pytest.mark.parametrize("view", VIEWS)
def test_every_view_has_stats(view):

    assert stats_for_view(view), f"{view} has no stats"


@pytest.mark.parametrize(
    "field, direction",
    [
        ("interceptions", Direction.LOWER_IS_BETTER),
        ("int_pct", Direction.LOWER_IS_BETTER),
        ("sacks", Direction.LOWER_IS_BETTER),
        ("sack_yards", Direction.LOWER_IS_BETTER),
        ("passing_yards", Direction.HIGHER_IS_BETTER),
    ],
)
def test_stat_directions(field, direction):

    assert STATS[field].direction is direction


@pytest.mark.parametrize("stat", STATS.values(), ids=lambda s: s.field)
def test_rate_stats_are_never_prorated(stat):

    expected = Prorate.NONE if stat.kind is Kind.RATE else Prorate.GAMES
    assert stat.prorate is expected


def test_unknown_legacy_tier_raises():
   
    assert legacy_tier_to_semantic("dark_green") is Tier.ELITE

    with pytest.raises(ValueError, match="not a valid legacy tier name"):
        legacy_tier_to_semantic("drk_green")

LEGACY_PATH = Path(__file__).parents[2] / "config" / "legacy_thresholds.json"

STATS_WITH_LEGACY_KEY = [s for s in STATS.values() if s.legacy_key is not None]


@pytest.fixture(scope="module")
def legacy_keys() -> set[str]:
   
    data = json.loads(LEGACY_PATH.read_text())
    return {key for view in data["views"].values() for key in view["stats"]}


@pytest.mark.parametrize("stat", STATS_WITH_LEGACY_KEY, ids=lambda s: s.field)
def test_legacy_key_exists_in_legacy_file(stat, legacy_keys):
    assert stat.legacy_key in legacy_keys, (
        f"{stat.field} claims legacy key {stat.legacy_key!r}, "
        f"which is not in {LEGACY_PATH.name}"
    ) 
