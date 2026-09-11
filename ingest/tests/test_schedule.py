"""Starter correction tests.

A wrong win-loss record never looks wrong. 2-6 and 1-3 are both perfectly
ordinary lines for a backup quarterback, so the only way to know which one the
pipeline produces is to assert it.
"""

import polars as pl

from ingest.schedule import correct_starters, qb_game_results, season_records

KEY = ["season", "season_type", "week", "team_abbr"]


def game_teams(rows):
    """(week, team, listed starter, outcome)"""
    return pl.DataFrame(
        [
            (f"2025_{w:02d}_{team}", 2025, "REG", w, team, "OPP", out, f"{out} 1-0", starter)
            for w, team, starter, out in rows
        ],
        schema=[
            "game_id", "season", "season_type", "week", "team_abbr",
            "opponent_abbr", "outcome", "result", "starter_player_id",
        ],
        orient="row",
    )


def appearances(rows):
    """(week, team, player, offensive_snaps, attempts, rushing_attempts)"""
    return pl.DataFrame(
        [(p, 2025, "REG", w, team, snaps, att, ratt) for w, team, p, snaps, att, ratt in rows],
        schema=[
            "player_id", "season", "season_type", "week", "team_abbr",
            "offensive_snaps", "attempts", "rushing_attempts",
        ],
        orient="row",
        infer_schema_length=None,
    )


def starter(df, week):
    return df.filter(pl.col("week") == week)["starter_player_id"].item()


def test_listed_starter_who_did_not_play_is_replaced():
    """Tyrod Taylor, 2025 week 10: listed, but Justin Fields took all 49 snaps."""
    fixed = correct_starters(
        game_teams([(10, "NYJ", "TAYLOR", "W")]),
        appearances([(10, "NYJ", "FIELDS", 49, 11, 4)]),
    )
    assert starter(fixed, 10) == "FIELDS"


def test_starter_who_left_early_is_kept():
    """Aaron Rodgers, 2023 week 1: four snaps, then a torn Achilles.

    He is the starter. The backup played far more, which is exactly the case a
    "whoever played most" rule would get wrong.
    """
    fixed = correct_starters(
        game_teams([(1, "NYJ", "RODGERS", "W")]),
        appearances([(1, "NYJ", "RODGERS", 4, 1, 0), (1, "NYJ", "WILSON", 50, 21, 2)]),
    )
    assert starter(fixed, 1) == "RODGERS"


def test_without_snap_counts_the_most_involved_quarterback_is_used():
    """Before 2013 there are no snap counts, so attempts plus carries decide."""
    fixed = correct_starters(
        game_teams([(5, "SEA", "LISTED", "L")]),
        appearances([
            (5, "SEA", "BACKUP", None, 3, 1),
            (5, "SEA", "ACTUAL", None, 31, 2),
        ]),
    )
    assert starter(fixed, 5) == "ACTUAL"


def test_exact_tie_is_broken_the_same_way_every_run():
    """A non-deterministic pick would break the loader's idempotency."""
    teams = game_teams([(3, "LV", "LISTED", "W")])
    apps = appearances([(3, "LV", "ZED", 30, 10, 0), (3, "LV", "AMY", 30, 10, 0)])
    assert {starter(correct_starters(teams, apps), 3) for _ in range(20)} == {"AMY"}


def test_corrected_record_matches_tyrod_taylor_2025():
    """The 2-6 that started this: four phantom starts removed, 1-3 remains."""
    teams = game_teams([
        (3, "NYJ", "TAYLOR", "L"), (10, "NYJ", "TAYLOR", "W"), (11, "NYJ", "TAYLOR", "L"),
        (12, "NYJ", "TAYLOR", "L"), (13, "NYJ", "TAYLOR", "W"), (14, "NYJ", "TAYLOR", "L"),
        (16, "NYJ", "TAYLOR", "L"), (17, "NYJ", "TAYLOR", "L"),
    ])
    apps = appearances([
        (3, "NYJ", "TAYLOR", 69, 36, 3),
        (10, "NYJ", "FIELDS", 49, 11, 4),
        (11, "NYJ", "FIELDS", 57, 26, 5),
        (12, "NYJ", "TAYLOR", 59, 28, 2),
        (13, "NYJ", "TAYLOR", 66, 33, 4),
        (14, "NYJ", "TAYLOR", 6, 4, 0), (14, "NYJ", "COOK", 52, 20, 1),
        (16, "NYJ", "COOK", 66, 35, 2),
        (17, "NYJ", "COOK", 62, 33, 1),
    ])
    records = season_records(qb_game_results(correct_starters(teams, apps)))
    line = lambda p: records.filter(pl.col("player_id") == p).select(
        "wins", "losses", "games_started").row(0)

    assert line("TAYLOR") == (1, 3, 4)
    assert line("FIELDS") == (1, 1, 2)
    assert line("COOK") == (0, 2, 2)
