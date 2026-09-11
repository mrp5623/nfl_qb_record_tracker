"""Refresh guard and data freshness tests.

The guard fails silently in the dangerous direction: if it ever reads a stored
value as "unchanged" when something moved, every scheduled run skips, nothing
errors, and the site quietly stops updating mid-season.
"""

import json
from datetime import datetime, timezone

import polars as pl

from ingest.load import WATCHED_RELEASES, changed_releases, data_freshness

CURRENT = {
    "stats_player": "2026-09-11 10:03:41 EDT",
    "snap_counts": "2026-09-11 12:10:07 EDT",
    "espn_data": "2026-09-11 09:07:13 EDT",
}


def test_nothing_changed_skips():
    assert changed_releases(json.dumps(CURRENT, sort_keys=True), CURRENT) == []


def test_only_the_release_that_moved_is_reported():
    before = {**CURRENT, "snap_counts": "2026-09-11 06:55:02 EDT"}
    assert changed_releases(json.dumps(before), CURRENT) == ["snap_counts"]


def test_no_previous_run_loads_everything():
    assert changed_releases(None, CURRENT) == list(WATCHED_RELEASES)


def test_legacy_bare_timestamp_loads_everything():
    """Runs before this guard stored one stats_player string, not an object.

    Even when that string equals today's stats_player build, snap counts and QBR
    were never tracked, so treating it as up to date would skip real updates.
    """
    legacy = CURRENT["stats_player"]
    assert changed_releases(legacy, CURRENT) == list(WATCHED_RELEASES)


def test_json_that_is_not_an_object_loads_everything():
    """A stored value that parses but is not a mapping must not read as unchanged."""
    assert changed_releases("5", CURRENT) == list(WATCHED_RELEASES)
    assert changed_releases('["stats_player"]', CURRENT) == list(WATCHED_RELEASES)


# ---------------------------------------------------------------------------
# data_freshness
# ---------------------------------------------------------------------------

def _freshness_inputs():
    # (game_id, week, team, offensive_snaps, qbr)
    players = [
        # NE @ SEA: both published. One SEA backup has neither, which must not
        # make the game read as missing.
        ("2026_01_NE_SEA", 1, "NE", 71, 57.9),
        ("2026_01_NE_SEA", 1, "SEA", 45, 79.6),
        ("2026_01_NE_SEA", 1, "SEA", 5, None),
        # SF @ LA: QBR is out (SF has it), snap counts are not.
        ("2026_01_SF_LA", 1, "SF", None, 81.5),
        ("2026_01_SF_LA", 1, "LA", None, None),
        # CHI @ CAR: nothing published yet.
        ("2026_01_CHI_CAR", 1, "CHI", None, None),
        ("2026_01_CHI_CAR", 1, "CAR", None, None),
        # A fully caught-up week.
        ("2026_02_BUF_MIA", 2, "BUF", 64, 70.1),
        ("2026_02_BUF_MIA", 2, "MIA", 60, 44.0),
    ]
    week_rows = pl.DataFrame(
        [(2026, "REG", w, t, s, q) for _, w, t, s, q in players],
        schema=["season", "season_type", "week", "team_abbr", "offensive_snaps", "qbr"],
        orient="row",
    )
    game_teams = pl.DataFrame(
        sorted({(g, 2026, "REG", w, t) for g, w, t, _, _ in players}),
        schema=["game_id", "season", "season_type", "week", "team_abbr"],
        orient="row",
    )
    schedules = pl.DataFrame(
        [
            ("2026_01_NE_SEA", "2026-09-09", "20:20"),
            ("2026_01_SF_LA", "2026-09-10", "20:35"),
            ("2026_01_CHI_CAR", "2026-09-13", "13:00"),
            ("2026_02_BUF_MIA", "2026-09-20", "13:00"),
        ],
        schema=["game_id", "gameday", "gametime"],
        orient="row",
    )
    return week_rows, game_teams, schedules


def _week(df, week):
    return df.filter(pl.col("week") == week).row(0, named=True)


def test_game_counts_as_covered_if_any_player_has_the_value():
    """A backup with no snaps or QBR must not mark a published game as missing."""
    wk1 = _week(data_freshness(*_freshness_inputs()), 1)
    assert wk1["games"] == 3
    assert wk1["games_missing_snaps"] == 2   # SF @ LA, CHI @ CAR
    assert wk1["games_missing_qbr"] == 1     # CHI @ CAR only


def test_latest_missing_kickoff_is_the_most_recent_missing_game_in_utc():
    """Sunday's 1:00 PM EDT game is later than Thursday's, and is 17:00 UTC."""
    wk1 = _week(data_freshness(*_freshness_inputs()), 1)
    sunday = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
    assert wk1["latest_missing_snaps_kickoff"] == sunday
    assert wk1["latest_missing_qbr_kickoff"] == sunday


def test_caught_up_week_has_no_missing_kickoff():
    wk2 = _week(data_freshness(*_freshness_inputs()), 2)
    assert wk2["games_missing_snaps"] == 0
    assert wk2["games_missing_qbr"] == 0
    assert wk2["latest_missing_snaps_kickoff"] is None
    assert wk2["latest_missing_qbr_kickoff"] is None


# ---------------------------------------------------------------------------
# unswap_teams
# ---------------------------------------------------------------------------


def _weeks(rows):
    """(player, week, team, opponent_team)"""
    return pl.DataFrame(
        [(p, f"{p}", 2001, "REG", w, t, o) for p, w, t, o in rows],
        schema=["player_id", "player_display_name", "season", "season_type", "week", "team", "opponent_team"],
        orient="row",
    )


def test_opponent_recorded_as_team_is_swapped_back():
    """Mark Brunell, 2001: JAX all season, but week 1 listed as PIT vs JAX."""
    from ingest.load import unswap_teams
    fixed = unswap_teams(_weeks([
        ("BRUNELL", 1, "PIT", "JAX"),
        ("BRUNELL", 2, "JAX", "TEN"),
        ("BRUNELL", 3, "JAX", "CLE"),
    ]))
    wk1 = fixed.filter(pl.col("week") == 1).row(0, named=True)
    assert (wk1["team"], wk1["opponent_team"]) == ("JAX", "PIT")


def test_real_trade_is_left_alone():
    """A contiguous stint with a new team is a trade, not a swap."""
    from ingest.load import unswap_teams
    rows = [
        ("FLACCO", 1, "CLE", "CIN"), ("FLACCO", 2, "CLE", "BAL"), ("FLACCO", 3, "CLE", "GB"),
        ("FLACCO", 7, "CIN", "PIT"), ("FLACCO", 8, "CIN", "NYJ"),
    ]
    fixed = unswap_teams(_weeks(rows))
    assert fixed.select("week", "team", "opponent_team").sort("week").rows() == [
        (w, t, o) for _, w, t, o in rows
    ]
