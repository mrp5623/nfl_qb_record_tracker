"""Record-mode threshold generation (parent spec section 7).

Record mode grades a stat against fixed global thresholds derived from every
season since 1999, so a 2003 season and a 2025 season are held to the same bar.
This module produces those thresholds; `grade.py` (Task 21) applies them.

Section 7.2's two populations are the reason this is not one query:

    record tier        max over ALL finalized rows
    every other tier   percentile_cont over finalized AND QUALIFIED rows

A record needs no qualifier -- you cannot accumulate an extreme total without
playing -- while the distribution is the opposite: including mop-up duty would
define "average" using appearances nobody would call a season.

Three refinements to that, all decided at the 2026-08-23 review after seeing what
the raw queries produced. Each is explained at the constant that implements it:
NORMALIZED_VIEWS, RATE_RECORD_MIN_GAMES, and `_record_expression`.

Usage:
    from ingest import load, thresholds

    with load.get_connection() as conn:
        doc = thresholds.generate_all(conn, as_of_season=2025)
"""

import math
from datetime import datetime, timezone

import psycopg
from psycopg import sql

from ingest.registry import STATS, VIEWS, Direction, Kind, Prorate, Stat, Tier

# Percentile cutpoints for a higher-is-better stat, best tier first. Five
# cutpoints carve the distribution into six bins; `record` sits above them and
# `worst` catches everything below, giving the seven tiers of D5.
#
# Parent section 14.2 offers p95/p85/p60/p35/p15 as a stricter fallback if the
# generated scale reads too generous at the Task 20 review.
CUTPOINTS: dict[Tier, float] = {
    Tier.ELITE: 0.90,
    Tier.GOOD: 0.75,
    Tier.AVERAGE: 0.50,
    Tier.BELOW: 0.25,
    Tier.POOR: 0.10,
}

# Which table and season_type each view reads.
VIEW_SOURCES: dict[str, tuple[str, str]] = {
    "season_REG": ("player_season", "REG"),
    "season_POST": ("player_season", "POST"),
    "week_REG": ("player_week", "REG"),
    "week_POST": ("player_week", "POST"),
}

# Proration (D3) answers "is this player on pace?", which is only a question
# about a regular season in progress. A single week is already one week, and a
# postseason is one to four games -- scaling either to 17 would be nonsense.
PRORATE_VIEWS: frozenset[str] = frozenset({"season_REG"})
PRORATE_DENOMINATOR_GAMES = 17

# Where counting-stat percentiles are taken over a PER-GAME rate scaled to 17
# games rather than over the raw season total (decided 2026-08-23).
#
# D9's 10-attempts-per-game rule qualifies a QB who played two games and threw
# twenty passes, so the median qualified regular season is only 10 games long.
# Percentiles over raw totals therefore describe half-seasons -- and proration
# then scales that bar UP by the player's games, grading a 17-game starter
# against a threshold set by half-seasons. Normalizing first puts every season on
# equal footing and lands the result in the "per 17 games" units proration
# already expects. It also reproduces the legacy sheet: passing_tds p50 comes out
# at 18 against a hand-picked 18, completions at 300 against 285.
#
# season_POST is deliberately excluded. Its median qualified row is 2 games and
# 160 of 347 are a single game, so scaling to a 4-game denominator would put
# "average" past what all but 16 postseasons in history ever reached. There, the
# raw total is the achievement: a deep run is supposed to out-rank a one-and-done.
NORMALIZED_VIEWS: frozenset[str] = PRORATE_VIEWS

# Minimum games for a season-level RATE record (decided 2026-08-23).
#
# `is_qualified` is a strong enough filter for a distribution but not for a
# record, because a rate over a tiny sample produces a nonsense extreme: the
# unfiltered completion_pct record is Trent Edwards going 1-for-1 in 2012, and
# even the qualified record is Mike Glennon's 90.9% over a handful of 2016
# appearances. A full-season floor reproduces the legacy sheet exactly --
# completion_pct 74.4 (Brees 2018) and passer_rating 122.5 (Rodgers 2011).
#
# Counting stats need no floor in either direction, since an extreme total
# already implies the playing time. Week views need none either: a single game IS
# the sample, and the week record then correctly comes out at a perfect 158.3.
RATE_RECORD_MIN_GAMES = 14

# Counting stats land on whole numbers; rates get one decimal, matching the
# precision the legacy sheet used (122.5 RTG, 74.4 CMP%, 158.3 week RTG).
RATE_DECIMALS = 1


def percentile_cutpoints() -> dict[Tier, float]:
    """The five distribution cutpoints, as fractions from the bottom.

    Stated for a higher-is-better stat. `_fraction_for` flips them for
    lower-is-better stats, where the good end of the distribution is p10.
    """
    return dict(CUTPOINTS)


def _fraction_for(tier: Tier, direction: Direction) -> float:
    """The percentile fraction that marks `tier` for a stat of `direction`.

    percentile_cont always measures from the bottom of the ordering, so for a
    lower-is-better stat every cutpoint mirrors: elite is p10, not p90. Getting
    this backwards produces a threshold set that grades the worst seasons best,
    and nothing about the JSON would look wrong.
    """
    fraction = CUTPOINTS[tier]
    if direction is Direction.LOWER_IS_BETTER:
        return round(1.0 - fraction, 2)
    return fraction


def _ladder_operator(direction: Direction) -> str:
    """The comparison a value must satisfy to reach a distribution tier."""
    return "lte" if direction is Direction.LOWER_IS_BETTER else "gte"


def _round_distribution(value: float, kind: Kind) -> float:
    """Round a percentile to review-friendly precision."""
    if kind is Kind.COUNTING:
        return float(round(value))
    return round(value, RATE_DECIMALS)


def _round_record(value: float, kind: Kind) -> float:
    """Round a record DOWN, so the season that set it still matches its own tier.

    The record operator is always `gte` (see `_record_expression`), so rounding
    to nearest can push the threshold above the value it came from. A max passer
    rating of 122.46 rounded to 122.5 is a bar the season that set it fails, and
    the record tier would then belong to nobody.
    """
    step = 1.0 if kind is Kind.COUNTING else 10.0 ** -RATE_DECIMALS
    return round(math.floor(value / step) * step, RATE_DECIMALS)


def _record_expression(stat: Stat) -> str:
    """Why the record is `max` even for a stat where lower is better.

    Not executable -- this exists to hold the reasoning next to the code.

    A `min` over interceptions returns 0, achieved by anyone who threw fifteen
    passes without being picked. That is not a record, it is an absence. The
    legacy sheet already knew this: its INT entry read `record: gt 35`, the MOST
    interceptions ever thrown, and SCK% simply had no record tier at all.

    So `record` here means "historically extreme", not "best". For passing yards
    that is the most yards; for interceptions it is the most interceptions, an
    infamy record. Both are records in the record-book sense, and the rule
    collapses to one line: the record is `max(col)` with operator `gte`, for
    every stat in every direction.

    It is checked FIRST, above the ladder, which also closes the legacy gap bug
    where 31-35 interceptions matched no tier at all (Task 19's first fixture).
    """
    return f"max({stat.field})"


def _value_expression(view: str, stat: Stat, table: str) -> sql.Composable:
    """What the distribution percentiles are taken over.

    Either the raw column, or a per-game rate scaled to 17 games -- see
    NORMALIZED_VIEWS for why. Casting to numeric matters: both operands are
    integers for a counting stat, and Postgres integer division would silently
    truncate 3400/17 worth of precision to whole yards per game.
    """
    col = sql.Identifier(stat.field)
    if view in NORMALIZED_VIEWS and stat.prorate is Prorate.GAMES:
        return sql.SQL("({col}::numeric / games_played) * {n}").format(
            col=col, n=sql.Literal(PRORATE_DENOMINATOR_GAMES)
        )
    return col


def _record_min_games(view: str, stat: Stat) -> int | None:
    """The games floor on this stat's record population, or None for no floor.

    Only season_REG has one. A 14-game floor is meaningless in a view whose
    longest possible row is a four-game postseason -- applied there it matches
    zero rows, and every rate stat drops out of the view entirely.
    """
    if view in PRORATE_VIEWS and stat.kind is Kind.RATE:
        return RATE_RECORD_MIN_GAMES
    return None


def _record_filter(view: str, stat: Stat) -> sql.Composable:
    """Restriction on the record population, or `true` for none.

    Counting stats get no restriction in either direction: an extreme total
    already implies the playing time.

    Rate stats need *some* floor or the record is whoever went 1-for-1. Where a
    games count exists and a full season is a meaningful unit, that floor is
    RATE_RECORD_MIN_GAMES. Everywhere else -- weeks, and the postseason where no
    row can reach 14 games -- `is_qualified` is the available proxy, requiring 10
    attempts per game rather than a games count.
    """
    if stat.kind is not Kind.RATE:
        return sql.SQL("true")
    floor = _record_min_games(view, stat)
    if floor is None:
        return sql.SQL("is_qualified")
    return sql.SQL("games_played >= {n}").format(n=sql.Literal(floor))


def _qualified_filter(view: str, stat: Stat) -> sql.Composable:
    """Restriction on the distribution population.

    The `games_played > 0` guard only matters where the value expression divides
    by it. `is_qualified` does not imply a nonzero games count: the rule is
    `attempts >= 10 * games_played`, which 0 attempts in 0 games satisfies.
    """
    if view in NORMALIZED_VIEWS and stat.prorate is Prorate.GAMES:
        return sql.SQL("is_qualified and games_played > 0")
    return sql.SQL("is_qualified")


def _query(view: str, stat: Stat, fractions: list[float]) -> sql.Composed:
    """Build the two-population query for one stat.

    Column and table names cannot be query parameters -- `%s` only ever stands
    for a value -- so they are composed with `sql.Identifier`, which quotes and
    escapes them. These names come from our own registry rather than user input,
    but string-formatting SQL is a habit worth not having.

    `filter (where ...)` narrows one aggregate to a subset of the rows the query
    already selected. It is what lets both populations be measured in one pass:
    the max sees the record population, the percentiles see the qualified one.
    """
    table, _ = VIEW_SOURCES[view]
    col = sql.Identifier(stat.field)
    value = _value_expression(view, stat, table)
    record_where = _record_filter(view, stat)
    qualified_where = _qualified_filter(view, stat)

    percentiles = sql.SQL(", ").join(
        sql.SQL(
            "percentile_cont({f}) within group (order by {value})"
            " filter (where {qual})"
        ).format(f=sql.Literal(f), value=value, qual=qualified_where)
        for f in fractions
    )
    return sql.SQL(
        """
        select max({col}) filter (where {record_where}) as record_value,
               count({col}) filter (where {record_where}) as record_n,
               count({col}) filter (where {qual}) as qualified_n,
               {percentiles}
        from {table}
        where season_type = %s
          and season <= %s
          and is_final = true
        """
    ).format(
        col=col,
        record_where=record_where,
        qual=qualified_where,
        percentiles=percentiles,
        table=sql.Identifier(table),
    )


def _stat_thresholds(
    conn: psycopg.Connection, view: str, stat: Stat, as_of_season: int
) -> dict | None:
    """Every tier for one stat in one view, or None if the view has no data.

    Returns None rather than a half-empty entry when the stat was never recorded
    in this view. Task 19's completeness rule then fails loudly instead of the UI
    quietly rendering an ungraded column.
    """
    ordered = list(CUTPOINTS)
    fractions = [_fraction_for(tier, stat.direction) for tier in ordered]

    row = conn.execute(
        _query(view, stat, fractions), (VIEW_SOURCES[view][1], as_of_season)
    ).fetchone()
    if row is None:  # an aggregate query always returns one row; belt and braces
        return None

    record_value, record_n, qualified_n = row[0], row[1], row[2]
    percentile_values = row[3:]

    if record_n == 0 or record_value is None:
        return None

    ladder_op = _ladder_operator(stat.direction)
    prorate = (
        Prorate.GAMES
        if stat.prorate is Prorate.GAMES and view in PRORATE_VIEWS
        else Prorate.NONE
    )

    # `record` is always max/gte and always checked first -- see
    # `_record_expression` for why that holds even when lower is better.
    tiers: list[dict] = [
        {
            "tier": str(Tier.RECORD),
            "op": "gte",
            "threshold": _round_record(float(record_value), stat.kind),
            "source": "max",
            "prorate": str(prorate),
        }
    ]
    for tier, fraction, value in zip(ordered, fractions, percentile_values):
        if value is None:
            return None
        tiers.append(
            {
                "tier": str(tier),
                "op": ladder_op,
                "threshold": _round_distribution(float(value), stat.kind),
                "source": f"p{int(round(fraction * 100)):02d}",
                "prorate": str(prorate),
            }
        )

    # `worst` is the else branch, not a threshold. Every legacy view had a floor
    # below which a value matched no tier at all -- CMP% bottomed out at 38.6 and
    # anything worse rendered uncolored. An unconditional catch-all is the fix,
    # and Task 19 asserts it stays that way.
    tiers.append(
        {
            "tier": str(Tier.WORST),
            "op": "always",
            "threshold": None,
            "source": "fallback",
            "prorate": str(prorate),
        }
    )

    return {
        "direction": str(stat.direction),
        "kind": str(stat.kind),
        "display": stat.display,
        "population": {
            "record_n": record_n,
            "qualified_n": qualified_n,
            "record_min_games": _record_min_games(view, stat),
            "normalized_per_game": view in NORMALIZED_VIEWS
            and stat.prorate is Prorate.GAMES,
        },
        "tiers": tiers,
    }


def generate_thresholds(conn: psycopg.Connection, view: str, as_of_season: int) -> dict:
    """Every stat's thresholds for one view."""
    if view not in VIEW_SOURCES:
        raise KeyError(
            f"{view!r} is not a known view; expected one of {list(VIEW_SOURCES)}"
        )

    table, season_type = VIEW_SOURCES[view]
    stats: dict[str, dict] = {}
    for name, stat in STATS.items():
        if view not in stat.views:
            continue
        entry = _stat_thresholds(conn, view, stat, as_of_season)
        if entry is not None:
            stats[name] = entry

    return {
        "granularity": "season" if table == "player_season" else "week",
        "season_type": season_type,
        "prorate_denominator_games": (
            PRORATE_DENOMINATOR_GAMES if view in PRORATE_VIEWS else None
        ),
        "stats": stats,
    }


def generate_all(conn: psycopg.Connection, as_of_season: int) -> dict:
    """The full section 7.4 document, all four views."""
    return {
        "as_of_season": as_of_season,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutpoints": {str(tier): fraction for tier, fraction in CUTPOINTS.items()},
        "rate_record_min_games": RATE_RECORD_MIN_GAMES,
        "views": {view: generate_thresholds(conn, view, as_of_season) for view in VIEWS},
    }


def population_report(conn: psycopg.Connection, as_of_season: int) -> list[dict]:
    """How many rows D9's 10-attempts-per-game rule admits, per season and view.

    Task 20 asks for this alongside the thresholds. D9 is settled, but the
    qualified population is what defines every distribution tier, so it is worth
    seeing what it actually selects before signing off on the numbers.
    """
    report: list[dict] = []
    for view, (table, season_type) in VIEW_SOURCES.items():
        rows = conn.execute(
            sql.SQL(
                """
                select season,
                       count(*) as total,
                       count(*) filter (where is_qualified) as qualified
                from {table}
                where season_type = %s and season <= %s and is_final = true
                group by season
                order by season
                """
            ).format(table=sql.Identifier(table)),
            (season_type, as_of_season),
        ).fetchall()
        for season, total, qualified in rows:
            report.append(
                {
                    "view": view,
                    "season": season,
                    "total": total,
                    "qualified": qualified,
                    "pct": round(100.0 * qualified / total, 1) if total else None,
                }
            )
    return report
