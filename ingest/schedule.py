"""Columns derived from the game schedule.

`stats_player` has no `games_started`, no win/loss record, and no displayable
result string, so all three are built here from `games.csv` (see plan, "Missing
sources").

Two shapes come out of this module:

* `game_team_rows` -- one row per (game, team). Every quarterback who appeared in
  a game joins to this to get his opponent and result, starter or not.
* `qb_game_results` -- the same rows narrowed to the *starting* quarterback, which
  is what `games_started` and the win-loss record are built from.

The schedule's starter is corrected against the box score by `correct_starters`
before the record is built -- see it for why the raw value cannot be trusted.
"""

import polars as pl

# Postseason weeks continue the regular-season count and shift by era: the 2020
# Super Bowl is week 21, the 2025 one is week 22, because the regular season grew
# from 17 weeks to 18. game_type does not shift, so rounds come from it instead.
# Matches the 1-4 round selector in spec 10.1.
POSTSEASON_ROUNDS: dict[str, int] = {"WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def _one_side(games: pl.DataFrame, side: str) -> pl.DataFrame:
    """Reshape games into one row per team, from `side`'s point of view."""
    other = "away" if side == "home" else "home"
    return games.select(
        pl.col("game_id"),
        pl.col("season"),
        pl.col("game_type"),
        pl.col("week").alias("schedule_week"),
        pl.col(f"{side}_team").alias("team_abbr"),
        pl.col(f"{other}_team").alias("opponent_abbr"),
        pl.col(f"{side}_score").alias("points_for"),
        pl.col(f"{other}_score").alias("points_against"),
        pl.col(f"{side}_qb_id").alias("starter_player_id"),
        pl.lit(side == "home").alias("is_home"),
    )


def game_team_rows(games: pl.DataFrame) -> pl.DataFrame:
    """One row per (game, team) for every game that has been played."""
    # Unplayed games (future seasons) carry null scores and null QB ids.
    played = games.filter(pl.col("home_score").is_not_null())
    both_sides = pl.concat([_one_side(played, "home"), _one_side(played, "away")])

    outcome = (
        pl.when(pl.col("points_for") > pl.col("points_against")).then(pl.lit("W"))
        .when(pl.col("points_for") < pl.col("points_against")).then(pl.lit("L"))
        .otherwise(pl.lit("T"))
    )
    season_type = (
        pl.when(pl.col("game_type") == "REG").then(pl.lit("REG"))
        .otherwise(pl.lit("POST"))
    )
    week = (
        pl.when(pl.col("game_type") == "REG").then(pl.col("schedule_week"))
        .otherwise(
            pl.col("game_type").replace_strict(
                POSTSEASON_ROUNDS, default=None, return_dtype=pl.Int32
            )
        )
    )
    # 'vs' for a home game, '@' for away -- spec 5 wants 'W 19-16 @ CHI'.
    location = pl.when(pl.col("is_home")).then(pl.lit("vs")).otherwise(pl.lit("@"))

    return (
        both_sides
        .with_columns(
            outcome.alias("outcome"),
            season_type.alias("season_type"),
            week.cast(pl.Int32).alias("week"),
        )
        .with_columns(
            pl.format(
                "{} {}-{} {} {}",
                pl.col("outcome"),
                pl.col("points_for"),
                pl.col("points_against"),
                location,
                pl.col("opponent_abbr"),
            ).alias("result")
        )
        .select(
            "game_id", "season", "season_type", "week", "team_abbr",
            "opponent_abbr", "outcome", "result", "starter_player_id",
        )
    )


def correct_starters(game_teams: pl.DataFrame, appearances: pl.DataFrame) -> pl.DataFrame:
    """Replace a listed starter who did not play in the game.

    nflverse's schedule names each team's starter (`home_qb_id`/`away_qb_id`),
    and for a small number of games it names a quarterback with no stats at all
    for that game: 86 team-games since 1999, 33 of them in 2024. The listing is
    stale in both directions -- Marcus Mariota credited with five 2024 starts
    Jayden Daniels played, Tim Boyle credited with a game Tua Tagovailoa played.
    In 2025 it gave Tyrod Taylor four Jets games that Justin Fields and Brady Cook
    played every snap of, turning his true 1-3 into 2-6.

    The listed starter is KEPT whenever he played at all, however briefly. A
    starter who leaves early is still the starter, and the box score cannot tell
    that apart from a mislabel: Aaron Rodgers took four snaps in 2023 week 1
    before tearing his Achilles, Teddy Bridgewater one in 2022 week 5. Checking
    every "listed starter played, someone else played more" case shows these
    are overwhelmingly real, so only the unambiguous case is corrected.

    When the listed starter did not play, the start goes to whoever played the
    most: offensive snaps where recorded (2013 on), otherwise pass attempts plus
    carries. player_id breaks exact ties so reruns always pick the same player.

    `appearances` is one row per quarterback per game, with player_id, season,
    season_type, week, team_abbr, offensive_snaps, attempts, rushing_attempts.
    """
    key = ["season", "season_type", "week", "team_abbr"]
    played = appearances.select(
        "player_id", *key, "offensive_snaps", "attempts", "rushing_attempts"
    )

    lead = played.group_by(key).agg(
        pl.col("player_id")
        .sort_by(
            [
                pl.col("offensive_snaps").fill_null(-1),
                pl.col("attempts").fill_null(0) + pl.col("rushing_attempts").fill_null(0),
                pl.col("player_id"),
            ],
            descending=[True, True, False],
        )
        .first()
        .alias("_lead")
    )

    listed_played = (
        played.select(pl.col("player_id").alias("starter_player_id"), *key)
        .unique()
        .with_columns(pl.lit(True).alias("_played"))
    )

    return (
        game_teams.join(lead, on=key, how="left")
        .join(listed_played, on=["starter_player_id", *key], how="left")
        .with_columns(
            pl.when(pl.col("_played").fill_null(False))
            .then(pl.col("starter_player_id"))
            .otherwise(pl.coalesce(pl.col("_lead"), pl.col("starter_player_id")))
            .alias("starter_player_id")
        )
        .drop("_lead", "_played")
    )


def qb_game_results(game_teams: pl.DataFrame) -> pl.DataFrame:
    """One row per starting quarterback per played game.

    Takes `game_team_rows` output -- ideally after `correct_starters` -- rather
    than the raw schedule, so the starter it narrows to has been checked against
    the box score.

    Only starters appear, which is what makes the row count equal
    `games_started` and matches the convention that a quarterback's win-loss
    record is his record as a starter.
    """
    return (
        game_teams
        .filter(pl.col("starter_player_id").is_not_null())
        .select(
            pl.col("starter_player_id").alias("player_id"),
            "season", "season_type", "week", "team_abbr", "opponent_abbr",
            "outcome", "result",
        )
    )


def season_records(game_results: pl.DataFrame) -> pl.DataFrame:
    """Aggregate per-game rows into a season win-loss record per quarterback.

    `games_started` is how many rows a quarterback has, because
    `qb_game_results` only emits starters.
    """
    return game_results.group_by(["player_id", "season", "season_type"]).agg(
        (pl.col("outcome") == "W").sum().alias("wins"),
        (pl.col("outcome") == "L").sum().alias("losses"),
        (pl.col("outcome") == "T").sum().alias("ties"),
        pl.len().alias("games_started"),
    )
