"""Columns derived from the game schedule.

`stats_player` has no `games_started`, no win/loss record, and no displayable
result string, so all three are built here from `games.csv` (see plan, "Missing
sources").

Two shapes come out of this module:

* `game_team_rows` -- one row per (game, team). Every quarterback who appeared in
  a game joins to this to get his opponent and result, starter or not.
* `qb_game_results` -- the same rows narrowed to the *starting* quarterback, which
  is what `games_started` and the win-loss record are built from.
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


def qb_game_results(games: pl.DataFrame) -> pl.DataFrame:
    """One row per starting quarterback per played game.

    Only starters appear, which is what makes the row count equal
    `games_started` and matches the convention that a quarterback's win-loss
    record is his record as a starter.
    """
    return (
        game_team_rows(games)
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
