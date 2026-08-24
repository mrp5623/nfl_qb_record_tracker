"""Columns derived from the game schedule.

`stats_player` has no `games_started` and no win/loss record, so both are built
here from `games.csv` (see plan, "Missing sources"). The only source that knows
who started a game is the `home_qb_id` / `away_qb_id` pair on each game row.

Each game produces two rows -- one per team -- so downstream logic is plain
column arithmetic instead of per-game branching.
"""

import polars as pl

# Postseason weeks continue the regular-season count (18-22) and shift by era:
# a 2020 Super Bowl is week 21, a 2025 one is week 22. game_type does not shift,
# so rounds are derived from it. Matches the 1-4 round selector in spec 10.1.
POSTSEASON_ROUNDS: dict[str, int] = {"WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def _one_side(games: pl.DataFrame, side: str) -> pl.DataFrame:
    """Reshape games into one row per team, from `side`'s point of view."""
    other = "away" if side == "home" else "home"
    return games.select(
        pl.col(f"{side}_qb_id").alias("player_id"),
        pl.col("season"),
        pl.col("game_type"),
        pl.col("week").alias("schedule_week"),
        pl.col(f"{side}_team").alias("team_abbr"),
        pl.col(f"{other}_team").alias("opponent_abbr"),
        pl.col(f"{side}_score").alias("points_for"),
        pl.col(f"{other}_score").alias("points_against"),
        pl.lit(side == "home").alias("is_home"),
    )


def qb_game_results(games: pl.DataFrame) -> pl.DataFrame:
    """One row per starting quarterback per played game.

    Only starters appear here: that is what makes the row count equal
    `games_started`, and it matches the convention that a quarterback's win-loss
    record is his record as a starter.
    """
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
            pl.col("game_type").replace_strict(POSTSEASON_ROUNDS, default=None,
                                               return_dtype=pl.Int32)
        )
    )

    # 'vs' for a home game, '@' for an away game -- spec 5 wants 'W 19-16 @ CHI'.
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
            "player_id", "season", "season_type", "week",
            "team_abbr", "opponent_abbr", "outcome", "result",
        )
    )


def season_records(game_results: pl.DataFrame) -> pl.DataFrame:
    """Aggregate per-game rows into a season win-loss record per quarterback.

    `games_started` is simply how many rows a quarterback has, because
    `qb_game_results` only emits starters.
    """
    return game_results.group_by(["player_id", "season", "season_type"]).agg(
        (pl.col("outcome") == "W").sum().alias("wins"),
        (pl.col("outcome") == "L").sum().alias("losses"),
        (pl.col("outcome") == "T").sum().alias("ties"),
        pl.len().alias("games_started"),
    )
