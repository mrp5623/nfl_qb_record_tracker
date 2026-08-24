"""Grading: turning a stat value into a tier or a percentile.

Two independent modes, and they answer different questions (parent spec 8):

    Record mode       how does this compare to every season since 1999?
                      Fixed global thresholds from config/thresholds_v2025.json.
    Performance mode  how does this compare to everyone else THIS season?
                      A percentile computed within the season or week.

Record mode doubles as an on-pace indicator. Counting-stat thresholds are stored
per 17 games and scaled down to the games a player has actually played, so a QB
with 2,000 yards through 8 games is measured against 8/17ths of each threshold.
That is what makes a mid-season cell mean "on pace for", and it is why a finished
16-game season can read as just short of a record that a 17-game schedule would
have delivered (D3).

Nothing in here touches the database or the network. It takes values and returns
tiers, which is what makes it the one module in the pipeline that is cheap to
test exhaustively.
"""

import operator
from typing import Any, Callable

import polars as pl

from ingest.registry import STATS, Direction, Stat, Tier

# Threshold operators, as they appear in the generated JSON.
#
# `always` is the `worst` tier's operator: an unconditional match that guarantees
# every value lands somewhere. It is the rule that makes the legacy "uncoloured
# cell" bug impossible -- see thresholds.validate().
_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "gte": operator.ge,
    "gt": operator.gt,
    "lte": operator.le,
    "lt": operator.lt,
}


class GradingError(Exception):
    """Raised when a threshold document contains something ungradeable."""


def compare(value: float, op: str, threshold: float | None) -> bool:
    """Does `value` satisfy this tier's condition?

    `always` ignores both value and threshold and matches. Any other unknown
    operator raises: a typo here would silently mis-colour a column, and a
    threshold file is generated rarely enough that failing loudly costs nothing.
    """
    if op == "always":
        return True
    if op not in _OPERATORS:
        raise GradingError(
            f"unknown threshold operator {op!r}; expected 'always' or one of "
            f"{sorted(_OPERATORS)}"
        )
    if threshold is None:
        raise GradingError(f"operator {op!r} needs a threshold, got None")
    return _OPERATORS[op](value, threshold)


def prorated_threshold(
    threshold: float, prorate: str, games_played: int, denominator_games: int
) -> float | None:
    """Scale a threshold to the games a player has actually played.

    Returns None when the scaling cannot be done, which the caller treats as
    "this row is not gradeable" rather than guessing.

    `prorate` is read per TIER, not per stat. One column can legitimately mix a
    prorated counting milestone with an absolute one, so the decision has to be
    made per threshold.
    """
    if prorate != "games":
        return threshold
    if not games_played or not denominator_games:
        return None
    return threshold / denominator_games * games_played


def grade_record(
    value: float | str | None,
    games_played: int | None,
    stat_config: dict,
    denominator_games: int | None,
) -> Tier | None:
    """The best tier `value` reaches, or None if it cannot be graded.

    `stat_config` is one stat's entry from the generated threshold document, so
    its `tiers` are already ordered best-to-worst and the first match wins
    (parent 8.1).

    Returns None in three cases, all of them "no tier applies" rather than
    "something went wrong":

    * `value` is None -- the numeric column is empty. Every sentinel row looks
      like this, because a sentinel leaves the number NULL and records the reason
      separately. Sentinels are never graded (parent 8.1): `Perfect` is already
      the most a TD/INT cell can say, and colouring it would say less.
    * `value` is a string -- a sentinel handed in directly rather than as None.
    * proration is needed but `games_played` is 0 or missing, which would divide
      by zero (design 8.2). No such row exists in the data today; this is here so
      that if one ever appears it produces an ungraded cell instead of a crash.
    """
    if value is None or isinstance(value, str):
        return None

    for tier in stat_config["tiers"]:
        threshold = prorated_threshold(
            tier["threshold"],
            tier.get("prorate", "none"),
            games_played or 0,
            denominator_games or 0,
        ) if tier["threshold"] is not None else None

        if tier["threshold"] is not None and threshold is None:
            return None  # proration impossible -- see docstring
        if compare(value, tier["op"], threshold):
            return Tier(tier["tier"])

    # Unreachable while `worst` is op='always', which thresholds.validate()
    # guarantees. If it ever fires, the threshold document lost its catch-all.
    raise GradingError(
        f"{value!r} matched no tier; the document is missing its 'worst' "
        f"catch-all"
    )


def grade_row(
    row: dict, view_config: dict, sentinels: dict[str, str] | None = None
) -> dict[str, str]:
    """Record-mode tiers for every gradeable stat in one row.

    Returns `{stat_name: tier}` for the `record_tiers` JSONB column, skipping
    stats that grade to None so the stored object stays small -- an absent key
    and a null value mean the same thing to the UI, and 1,621 season rows carry
    at least one sentinel.
    """
    sentinels = sentinels or {}
    denominator = view_config.get("prorate_denominator_games")
    games_played = row.get("games_played")

    tiers: dict[str, str] = {}
    for name, stat_config in view_config["stats"].items():
        if name in sentinels:
            continue
        tier = grade_record(row.get(name), games_played, stat_config, denominator)
        if tier is not None:
            tiers[name] = str(tier)
    return tiers


def performance_percentiles(
    df: pl.DataFrame, stat: Stat, partition: list[str]
) -> pl.Series:
    """Within-cohort percentile for one stat, one row per input row (parent 8.2).

    The cohort that DEFINES the scale is the qualified rows only, but EVERY row
    gets placed on it, qualified or not. Those are two different row sets in one
    operation, and conflating them is the easiest mistake in this project to make
    without noticing:

    * filter the frame first and the unqualified rows vanish entirely
    * rank the whole frame and a third-string QB's 12-yard afternoon drags down
      everyone the scale is supposed to describe

    So the rank is computed over a column that is null for unqualified rows --
    Polars ranks nulls as null, leaving them out of the denominator -- and each
    row is then placed by counting how many qualified values it beats.

    Lower-is-better stats invert, so the fewest interceptions scores highest.
    Sentinel rows have a null value and come back null: never graded (8.1).
    """
    col = stat.field
    if col not in df.columns:
        raise GradingError(f"{col!r} is not a column in the frame")

    # For a lower-is-better stat, negating turns "smallest is best" into
    # "largest is best" so one ordering serves both directions.
    sign = -1.0 if stat.direction is Direction.LOWER_IS_BETTER else 1.0

    value = (pl.col(col).cast(pl.Float64) * sign).alias("_v")
    in_cohort = (
        pl.col("is_qualified").fill_null(False) & pl.col(col).is_not_null()
    ).cast(pl.UInt32).alias("_c")

    work = (
        df.select([*partition, col, "is_qualified"])
        .with_row_index("_row")
        .with_columns(value, in_cohort)
        .sort("_v", nulls_last=True)
    )

    # Walking the sorted frame, the running total of cohort members is exactly
    # "how many qualified rows are at or below this value" -- which answers the
    # question for a row outside the cohort just as well as for one inside it.
    # Unqualified rows contribute 0 to the total, so they are placed on the scale
    # without shifting it.
    running = pl.col("_c").cum_sum().over(partition)
    work = work.with_columns(running.alias("_below"))

    # Everything sharing a value must share a percentile, so a tie group takes
    # the highest running total in the group rather than each row's own.
    work = work.with_columns(
        pl.col("_below").max().over([*partition, "_v"]).alias("_below"),
        pl.col("_c").sum().over(partition).alias("_n"),
    )

    return (
        work.with_columns(
            pl.when(pl.col("_v").is_null() | (pl.col("_n") == 0))
            .then(None)
            .otherwise((pl.col("_below") / pl.col("_n")).round(4))
            .alias(col)
        )
        .sort("_row")[col]
    )


def percentiles_for_row_set(
    df: pl.DataFrame, view_config: dict, partition: list[str]
) -> pl.DataFrame:
    """Percentiles for every stat in a view, as one column per stat.

    Returns the partition keys plus one column per stat, ready to be folded into
    the `season_percentiles` / `week_percentiles` JSONB.
    """
    out = df.select(partition)
    for name in view_config["stats"]:
        stat = STATS.get(name)
        if stat is None or stat.field not in df.columns:
            continue
        out = out.with_columns(performance_percentiles(df, stat, partition))
    return out
