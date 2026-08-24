"""Derived statistics and sentinels -- pure functions, no I/O.

Every formula here is from parent spec section 6.1.

Two conventions apply throughout:

* **A zero denominator returns `None`, never a substitute number.** The reason
  the value is missing is recorded separately as a sentinel (Task 13) so the
  numeric column stays numeric (parent spec section 13).
* **Full precision is returned; rounding happens at display.** Storing 86.5
  instead of 86.50793... would compound error through any later arithmetic, and
  the schema's numeric columns hold the precision for free.

Negative values are legitimate and must survive: a quarterback can finish with
negative rushing yards, which makes `rush_yards_per_att` negative too.
"""

from enum import StrEnum


def _safe_divide(numerator: float, denominator: float) -> float | None:
    """Divide, or return None when the denominator is zero or missing."""
    if not denominator:
        return None
    return numerator / denominator


def completion_pct(completions: int, attempts: int) -> float | None:
    return _safe_divide(completions * 100, attempts)


def yards_per_completion(passing_yards: int, completions: int) -> float | None:
    return _safe_divide(passing_yards, completions)


def yards_per_attempt(passing_yards: int, attempts: int) -> float | None:
    return _safe_divide(passing_yards, attempts)


def td_pct(passing_tds: int, attempts: int) -> float | None:
    return _safe_divide(passing_tds * 100, attempts)


def int_pct(interceptions: int, attempts: int) -> float | None:
    return _safe_divide(interceptions * 100, attempts)


def td_int_ratio(passing_tds: int, interceptions: int) -> float | None:
    """None when a quarterback threw no interceptions.

    That case is not an error -- it is the `Perfect` sentinel (Task 13), which is
    an achievement rather than a gap.
    """
    return _safe_divide(passing_tds, interceptions)


def sack_pct(sacks: int, attempts: int) -> float | None:
    """Sacks as a share of dropbacks, so the denominator is sacks + attempts."""
    return _safe_divide(sacks * 100, sacks + attempts)


def rush_yards_per_att(rushing_yards: int, rushing_attempts: int) -> float | None:
    return _safe_divide(rushing_yards, rushing_attempts)


def _clamp(value: float, low: float = 0.0, high: float = 2.375) -> float:
    return max(low, min(high, value))


def passer_rating(
    completions: int, attempts: int, passing_yards: int,
    passing_tds: int, interceptions: int,
) -> float | None:
    """NFL passer rating. Maximum 158.3 (158.333... before rounding).

    Four components, each clamped to [0, 2.375]. The clamps are what cap the
    scale: a quarterback who is 20/25 for 350 and 4 TDs maxes all four at once.
    """
    if not attempts:
        return None
    a = _clamp((completions / attempts - 0.3) * 5)
    b = _clamp((passing_yards / attempts - 3) * 0.25)
    c = _clamp((passing_tds / attempts) * 20)
    d = _clamp(2.375 - (interceptions / attempts * 25))
    return (a + b + c + d) / 6 * 100


def any_a(
    passing_yards: int, passing_tds: int, interceptions: int,
    sack_yards: int, attempts: int, sacks: int,
) -> float | None:
    """Adjusted net yards per attempt.

    `sack_yards` arrives positive from nflverse (`sack_yards_lost`), so it is
    subtracted rather than added.
    """
    numerator = passing_yards + 20 * passing_tds - 45 * interceptions - sack_yards
    return _safe_divide(numerator, attempts + sacks)


def total_tds(passing_tds: int, rushing_tds: int) -> int:
    return passing_tds + rushing_tds


def total_yards(passing_yards: int, rushing_yards: int) -> int:
    """Rushing yards can be negative, so this is not always a sum of positives."""
    return passing_yards + rushing_yards


def snap_pct(offensive_snaps: int, team_offensive_snaps: int) -> float | None:
    return _safe_divide(offensive_snaps * 100, team_offensive_snaps)


# ---------------------------------------------------------------------------
# Task 13: sentinels (parent spec section 6.2)
# ---------------------------------------------------------------------------


class Sentinel(StrEnum):
    """Why a numeric cell is empty.

    The numeric column stays NULL and the reason is stored alongside it in the
    `sentinels` JSONB, so numbers never share a column with text (parent spec
    section 13).

    `NOT_RECORDED` is not an error and must stay visually distinct from
    `INCALCULABLE` (parent spec section 6.2). The sheet also referenced a
    `Subpar` sentinel but never produced one; it is deliberately absent here.
    """

    PERFECT = "Perfect"
    INCALCULABLE = "Incalculable"
    NOT_RECORDED = "Not Recorded"


# stat -> the denominator that makes it incalculable when zero.
_RATE_DENOMINATORS: dict[str, tuple[str, ...]] = {
    "completion_pct": ("attempts",),
    "yards_per_completion": ("completions",),
    "yards_per_attempt": ("attempts",),
    "td_pct": ("attempts",),
    "int_pct": ("attempts",),
    "passer_rating": ("attempts",),
    "sack_pct": ("sacks", "attempts"),
    "rush_yards_per_att": ("rushing_attempts",),
    "any_a": ("attempts", "sacks"),
    "snap_pct": ("team_offensive_snaps",),
}

# Stats that did not exist for the whole 1999+ range (parent spec section 6.3).
#
# snap_pct is gated at 2013, not the 2012 the spec states: nflverse publishes a
# snap_counts_2012 asset but it is empty (verified 2026-08-11), so 2012 has no
# snap data at all. Gating at 2012 would label those rows Incalculable -- "we
# could not compute it" -- when the honest answer is that it was never recorded.
# Revisit if nflverse ever backfills 2012.
_ERA_GATES: dict[str, int] = {"qbr": 2006, "snap_pct": 2013}


def sentinels_for_row(row: dict, season: int) -> dict[str, str]:
    """Return {stat: sentinel} for every cell that has no number.

    Stats not mentioned in the result have an ordinary numeric value.
    """
    found: dict[str, str] = {}

    # Era gates come first: a stat that did not exist cannot be incalculable,
    # it simply was not recorded.
    for stat, first_season in _ERA_GATES.items():
        if season < first_season:
            found[stat] = Sentinel.NOT_RECORDED.value

    for stat, denominators in _RATE_DENOMINATORS.items():
        if stat in found:
            continue
        total = sum(row.get(d) or 0 for d in denominators)
        if total == 0:
            found[stat] = Sentinel.INCALCULABLE.value

    # td_int_ratio divides by interceptions, so zero interceptions is not a gap
    # but an achievement -- unless he never threw a pass, in which case there is
    # nothing to be perfect about.
    if not row.get("attempts"):
        found["td_int_ratio"] = Sentinel.INCALCULABLE.value
    elif not row.get("interceptions"):
        found["td_int_ratio"] = Sentinel.PERFECT.value

    return found
