"""Threshold validation tests (parent spec 7.5, plan Task 19).

Here the assertions ARE the deliverable. "The build fails on a non-monotonic
threshold set" is not something you can confirm by reading output -- a bad
threshold file looks exactly like a good one. The only way to know the validator
works is to hand it documents that are broken in known ways.

Every fixture below is a REAL bug lifted from config/legacy_thresholds.json, not
an invented one. Each is a case where the sheet you are porting would leave a
cell uncoloured, or colour it by a rule that could never fire.
"""

import copy

import pytest

from ingest import thresholds
from ingest.registry import STATS, VIEWS, Direction, Tier


def _tiers(direction: Direction) -> list[dict]:
    """A well-formed seven-tier ladder."""
    if direction is Direction.HIGHER_IS_BETTER:
        rungs = [("elite", 90), ("good", 80), ("average", 70), ("below", 60), ("poor", 50)]
        op = "gte"
    else:
        rungs = [("elite", 10), ("good", 20), ("average", 30), ("below", 40), ("poor", 50)]
        op = "lte"
    out = [{"tier": "record", "op": "gte", "threshold": 100, "source": "max"}]
    out += [{"tier": t, "op": op, "threshold": v, "source": "p50"} for t, v in rungs]
    out.append({"tier": "worst", "op": "always", "threshold": None, "source": "fallback"})
    return out


def valid_doc() -> dict:
    """A document that satisfies every 7.5 rule, for fixtures to break."""
    return {
        "as_of_season": 2025,
        "views": {
            view: {
                "granularity": "season" if view.startswith("season") else "week",
                "season_type": view.split("_")[1],
                "stats": {
                    name: {
                        "direction": str(stat.direction),
                        "kind": str(stat.kind),
                        "tiers": _tiers(stat.direction),
                    }
                    for name, stat in STATS.items()
                    if view in stat.views
                },
            }
            for view in VIEWS
        },
    }


def drop_tier(doc: dict, view: str, stat: str, *tiers: str) -> dict:
    entry = doc["views"][view]["stats"][stat]
    entry["tiers"] = [t for t in entry["tiers"] if t["tier"] not in tiers]
    return doc


def set_tier(doc: dict, view: str, stat: str, tier: str, **fields) -> dict:
    for t in doc["views"][view]["stats"][stat]["tiers"]:
        if t["tier"] == tier:
            t.update(fields)
    return doc


# Each entry: (id, mutation, substring the error must mention).
#
# The first seven are the legacy bugs named in the plan. The rest cover rules
# that legacy happened not to violate but that a future edit easily could.
FIXTURES = [
    (
        "legacy_season_INT_gap_31_to_35",
        # `red: lte 30` then `record: gt 35`. Interceptions 31-35 matched no tier
        # at all. In our schema that is `worst` failing to be the catch-all.
        lambda d: set_tier(d, "season_REG", "interceptions", "worst", op="lte", threshold=35),
        "worst must be op='always'",
    ),
    (
        "legacy_week_INT_only_four_tiers",
        # green/orange/red/record and nothing else -- three of the seven absent,
        # leaving 4-6 interceptions in a week matching nothing.
        lambda d: drop_tier(d, "week_REG", "interceptions", "elite", "average", "worst"),
        "missing tiers",
    ),
    (
        "legacy_season_RTD_no_elite",
        # record: gte 15 jumped straight to green: gte 3, with no dark_green.
        lambda d: drop_tier(d, "season_REG", "rushing_tds", "elite"),
        "missing tiers",
    ),
    (
        "legacy_season_RYDS_worst_unreachable",
        # `red: gte 0` swallowed every non-negative value, so `dark_red: lte 100`
        # below it could never fire.
        lambda d: set_tier(d, "season_REG", "rushing_yards", "worst", op="lte", threshold=100),
        "worst must be op='always'",
    ),
    (
        "legacy_season_RATT_worst_unreachable",
        lambda d: set_tier(d, "season_REG", "rushing_attempts", "worst", op="lte", threshold=25),
        "worst must be op='always'",
    ),
    (
        "legacy_season_CMPpct_floors_at_poor",
        # `red: gte 38.6` was the bottom of the ladder. A 30% completion season
        # matched nothing and rendered uncoloured.
        lambda d: drop_tier(d, "season_REG", "completion_pct", "worst"),
        "missing tiers",
    ),
    (
        "legacy_week_FUM_absent_entirely",
        # FUM existed in season_REG, season_POST and week_POST but not week_REG.
        lambda d: d["views"]["week_REG"]["stats"].pop("fumbles") and d,
        "missing stat 'fumbles'",
    ),
    (
        "tied_adjacent_rungs",
        lambda d: set_tier(d, "season_REG", "passing_yards", "good", threshold=90),
        "out of order or tied",
    ),
    (
        "rungs_inverted",
        lambda d: set_tier(d, "season_REG", "passing_yards", "elite", threshold=10),
        "out of order or tied",
    ),
    (
        "ladder_op_contradicts_direction",
        lambda d: set_tier(d, "season_REG", "passing_yards", "good", op="lte"),
        "must use 'gte'",
    ),
    (
        "record_less_extreme_than_elite",
        lambda d: set_tier(d, "season_REG", "passing_yards", "record", threshold=5),
        "less extreme than the ladder's top rung",
    ),
    (
        "whole_view_missing",
        lambda d: d["views"].pop("week_POST") and d,
        "missing view 'week_POST'",
    ),
]


@pytest.mark.parametrize("mutate,expected", [(f[1], f[2]) for f in FIXTURES],
                         ids=[f[0] for f in FIXTURES])
def test_validate_rejects(mutate, expected):
    broken = mutate(valid_doc())
    with pytest.raises(thresholds.ThresholdValidationError, match=expected):
        thresholds.validate(broken)


def test_validate_accepts_a_good_document():
    """A validator that rejects everything is not a validator."""
    thresholds.validate(valid_doc())


def test_collapsed_exemption_only_waives_ties():
    """The declared exemption must not become a blanket pass for that stat.

    week_REG rushing_tds genuinely cannot support seven distinct tiers, so its
    ties are waived. Everything else about it is still checked.
    """
    tied = set_tier(valid_doc(), "week_REG", "rushing_tds", "good", threshold=90)
    with pytest.raises(thresholds.ThresholdValidationError):
        thresholds.validate(tied)
    thresholds.validate(tied, collapsed={"week_REG": ["rushing_tds"]})

    still_broken = drop_tier(valid_doc(), "week_REG", "rushing_tds", "worst")
    with pytest.raises(thresholds.ThresholdValidationError, match="missing tiers"):
        thresholds.validate(still_broken, collapsed={"week_REG": ["rushing_tds"]})


def test_all_violations_reported_at_once():
    """One run should tell you everything wrong, not just the first thing."""
    doc = drop_tier(valid_doc(), "season_REG", "passing_yards", "elite")
    doc = drop_tier(doc, "week_REG", "attempts", "worst")
    doc["views"]["season_POST"]["stats"].pop("fumbles")

    with pytest.raises(thresholds.ThresholdValidationError) as excinfo:
        thresholds.validate(doc)
    message = str(excinfo.value)
    assert "season_REG.passing_yards" in message
    assert "week_REG.attempts" in message
    assert "season_POST: missing stat 'fumbles'" in message


def test_shipped_milestones_declare_only_real_stats():
    """config/milestones.json must not drift from the registry.

    A `_collapsed` entry naming a stat that no longer exists would silently waive
    nothing, and the tie it was hiding would start failing the build for reasons
    nobody could trace back to this file.
    """
    collapsed = thresholds.load_milestones().get("_collapsed", {})
    for view, names in collapsed.items():
        assert view in VIEWS, f"_collapsed names unknown view {view!r}"
        for name in names:
            assert name in STATS, f"_collapsed names unknown stat {name!r}"
            assert view in STATS[name].views, f"{name!r} is not shown in {view!r}"


def test_tier_order_covers_every_tier():
    """TIER_ORDER drives completeness, so it must not drift from the enum."""
    assert set(thresholds.TIER_ORDER) == set(Tier)
    assert thresholds.TIER_ORDER[0] is Tier.RECORD
    assert thresholds.TIER_ORDER[-1] is Tier.WORST
