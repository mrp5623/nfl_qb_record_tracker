"""Database writes.

The only module besides `sources.py` that touches the outside world.

Every write is an "upsert": insert the row, or update it if it already exists.
That makes reruns safe -- running ingest twice leaves the database in exactly the
state one run would have (parent spec section 9.2), which is what lets later
phases backfill columns by simply running the pipeline again.

Usage:
    from ingest import sources, load

    with load.get_connection() as conn:
        load.upsert_teams(conn, sources.fetch_teams())
        load.upsert_players(conn, sources.fetch_players())
"""

import os
from datetime import datetime

import polars as pl
import psycopg
from dotenv import load_dotenv

# Columns we read out of the source frame, in the order the SQL below expects.
# Keeping these next to the SQL makes a mismatch obvious.
PLAYER_SOURCE_COLUMNS = [
    "gsis_id",
    "pfr_id",
    "espn_id",
    "display_name",
    "position",
    "birth_date",
    "rookie_season",
]

TEAM_SOURCE_COLUMNS = [
    "team_abbr",
    "team_name",
    "team_color",
    "team_color2",
]

# %s is a placeholder. psycopg substitutes the values safely -- never build SQL
# by string formatting, which breaks on quotes in names and allows injection.
#
# "excluded" is a special table Postgres provides inside ON CONFLICT: it holds
# the row we *tried* to insert. So "set display_name = excluded.display_name"
# means "overwrite the stored name with the incoming one".
UPSERT_PLAYER_SQL = """
insert into player (
    player_id, pfr_id, espn_id, display_name, position, birth_date, rookie_year
)
values (%s, %s, %s, %s, %s, %s, %s)
on conflict (player_id) do update set
    pfr_id       = excluded.pfr_id,
    espn_id      = excluded.espn_id,
    display_name = excluded.display_name,
    position     = excluded.position,
    birth_date   = excluded.birth_date,
    rookie_year  = excluded.rookie_year
"""

UPSERT_TEAM_SQL = """
insert into team (team_abbr, team_name, primary_color, secondary_color)
values (%s, %s, %s, %s)
on conflict (team_abbr) do update set
    team_name       = excluded.team_name,
    primary_color   = excluded.primary_color,
    secondary_color = excluded.secondary_color
"""

# ingest_log is append-only history, so it is a plain insert with no conflict
# handling. The id column is bigserial, so the database assigns it.
INSERT_INGEST_LOG_SQL = """
insert into ingest_log (
    job, season, rows_written, status, error, started_at, completed_at
)
values (%s, %s, %s, %s, %s, %s, %s)
"""


def get_connection() -> psycopg.Connection:
    """Open a connection using DATABASE_URL from .env.

    Use it as a context manager so the transaction is committed on success and
    rolled back if an exception escapes:

        with get_connection() as conn:
            ...
    """
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Check that .env exists and load_dotenv() found it."
        )
    return psycopg.connect(url)


def _rows_from(df: pl.DataFrame, columns: list[str]) -> list[tuple]:
    """Turn selected DataFrame columns into the list of tuples psycopg wants.

    `.select(columns)` also fixes the column order, so position 1 in every tuple
    matches the first %s in the SQL.
    """
    return df.select(columns).rows()


def upsert_players(conn: psycopg.Connection, df: pl.DataFrame) -> int:
    """Insert or update every player. Returns the number of rows written.

    Loads all players, not just quarterbacks -- `player_season` has a foreign key
    to this table, and a QB whose listed position changed would otherwise fail
    that constraint. 25k rows is cheap.
    """
    rows = _rows_from(df, PLAYER_SOURCE_COLUMNS)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_PLAYER_SQL, rows)
    return len(rows)


def upsert_teams(conn: psycopg.Connection, df: pl.DataFrame) -> int:
    """Insert or update every team. Returns the number of rows written."""
    rows = _rows_from(df, TEAM_SOURCE_COLUMNS)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_TEAM_SQL, rows)
    return len(rows)


def write_ingest_log(
    conn: psycopg.Connection,
    job: str,
    season: int | None,
    rows_written: int | None,
    status: str,
    error: str | None,
    started_at: datetime,
    completed_at: datetime | None,
) -> None:
    """Record one ingest run. `status` must be 'success' or 'failed'."""
    with conn.cursor() as cur:
        cur.execute(
            INSERT_INGEST_LOG_SQL,
            (job, season, rows_written, status, error, started_at, completed_at),
        )


# ---------------------------------------------------------------------------
# Task 8: raw season and week rows
# ---------------------------------------------------------------------------

# nflverse column -> our schema column. The left side is what the plan's
# "Verified source facts" table found; the parent spec guessed several wrong.
STAT_COLUMN_MAP: dict[str, str] = {
    "completions": "completions",
    "attempts": "attempts",
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "passing_interceptions": "interceptions",
    "sacks_suffered": "sacks",
    "sack_yards_lost": "sack_yards",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "carries": "rushing_attempts",
    "fumbles_total": "fumbles",
}

SEASON_COLUMNS = [
    "player_id", "season", "season_type", "team_abbr",
    "games_played", "games_started", "wins", "losses", "ties",
    *STAT_COLUMN_MAP.values(),
    "is_final", "is_qualified",
]

WEEK_COLUMNS = [
    "player_id", "season", "season_type", "week",
    "team_abbr", "opponent_abbr", "result",
    *STAT_COLUMN_MAP.values(),
    "is_final", "is_qualified",
]

QUALIFYING_ATTEMPTS_PER_GAME = 10


def _renamed_stats(df: pl.DataFrame) -> pl.DataFrame:
    """Apply the nflverse -> schema column renaming."""
    return df.rename(STAT_COLUMN_MAP)


def final_seasons(schedules: pl.DataFrame) -> set[int]:
    """Seasons whose games have all been played.

    A season is final once nothing is left unplayed, which includes its
    postseason (parent spec section 9.2). Unplayed games carry a null score.
    """
    unfinished = (
        schedules.filter(pl.col("home_score").is_null())["season"].unique().to_list()
    )
    every = schedules["season"].unique().to_list()
    return {s for s in every if s not in unfinished}


def build_season_rows(
    stats: pl.DataFrame, records: pl.DataFrame, final: set[int]
) -> pl.DataFrame:
    """Assemble player_season rows. Derived stats stay empty until Phase 2."""
    return (
        _renamed_stats(stats)
        .rename({"recent_team": "team_abbr", "games": "games_played"})
        # Left join: a quarterback with stats but no start still gets a row,
        # with a null record rather than being dropped.
        .join(records, on=["player_id", "season", "season_type"], how="left")
        .with_columns(
            pl.col("wins").fill_null(0),
            pl.col("losses").fill_null(0),
            pl.col("ties").fill_null(0),
            pl.col("games_started").fill_null(0),
            pl.col("season").is_in(list(final)).alias("is_final"),
            (
                pl.col("attempts")
                >= QUALIFYING_ATTEMPTS_PER_GAME * pl.col("games_played")
            ).alias("is_qualified"),
        )
        .select(SEASON_COLUMNS)
    )


def build_week_rows(
    stats: pl.DataFrame, game_teams: pl.DataFrame, final: set[int]
) -> pl.DataFrame:
    """Assemble player_week rows.

    Joins on (game_id, team_abbr) rather than on the starter, so backups get an
    opponent and result too. `week` comes from the schedule side, which carries
    postseason round 1-4 instead of the era-dependent raw week number.
    """
    renamed = _renamed_stats(stats).rename({"team": "team_abbr"})

    # nflverse has a small number of player-weeks with no team recorded (one, as
    # of 2026-08: Steve Bono, 1999 week 9). They cannot be joined to a game side.
    # Removing them explicitly, and reporting the count, keeps an inner join from
    # quietly swallowing rows -- the failure mode parent spec section 13 forbids.
    no_team = renamed.filter(pl.col("team_abbr").is_null())
    if no_team.height:
        names = no_team.select("player_display_name", "season", "week").rows()
        print(f"warning: dropping {no_team.height} week row(s) with no team: {names}")
    renamed = renamed.filter(pl.col("team_abbr").is_not_null())

    joined = (
        renamed
        .drop("week", "season_type", "opponent_team")
        .join(
            game_teams.drop("starter_player_id", "outcome"),
            on=["game_id", "team_abbr"],
            how="inner",
        )
    )

    # Any *other* row loss means a broken join, not a source gap. Fail loudly.
    if joined.height != renamed.height:
        raise ValueError(
            f"week join lost {renamed.height - joined.height} rows unexpectedly; "
            "check team normalization and game_id alignment"
        )

    return joined.with_columns(
        pl.col("season").is_in(list(final)).alias("is_final"),
        (pl.col("attempts") >= QUALIFYING_ATTEMPTS_PER_GAME).alias("is_qualified"),
    ).select(WEEK_COLUMNS)


def _upsert_sql(table: str, columns: list[str], key: list[str]) -> str:
    """Build an INSERT ... ON CONFLICT statement for a wide table.

    Interpolating *column names* here is safe and normal -- they come from our
    own constants, never from data. The values still go through %s placeholders,
    which is the part that must never be built by string formatting.
    """
    placeholders = ", ".join(["%s"] * len(columns))
    column_list = ", ".join(columns)
    updates = ",\n    ".join(f"{c} = excluded.{c}" for c in columns if c not in key)
    conflict_key = ", ".join(key)
    return (
        f"insert into {table} ({column_list})\n"
        f"values ({placeholders})\n"
        f"on conflict ({conflict_key}) do update set\n"
        f"    {updates},\n"
        f"    updated_at = now()"
    )


UPSERT_SEASON_SQL = _upsert_sql(
    "player_season", SEASON_COLUMNS, ["player_id", "season", "season_type"]
)
UPSERT_WEEK_SQL = _upsert_sql(
    "player_week", WEEK_COLUMNS, ["player_id", "season", "season_type", "week"]
)


def upsert_player_season(conn: psycopg.Connection, df: pl.DataFrame) -> int:
    """Insert or update season rows. Returns rows written."""
    rows = _rows_from(df, SEASON_COLUMNS)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SEASON_SQL, rows)
    return len(rows)


def upsert_player_week(conn: psycopg.Connection, df: pl.DataFrame) -> int:
    """Insert or update week rows. Returns rows written."""
    rows = _rows_from(df, WEEK_COLUMNS)
    with conn.cursor() as cur:
        cur.executemany(UPSERT_WEEK_SQL, rows)
    return len(rows)


if __name__ == "__main__":
    from ingest import schedule, sources

    started = datetime.now()
    schedules = sources.fetch_schedules(True)
    final = final_seasons(schedules)
    game_teams = schedule.game_team_rows(schedules)
    records = schedule.season_records(schedule.qb_game_results(schedules))

    season_stats = pl.concat(
        [sources.fetch_player_stats(True, "reg"), sources.fetch_player_stats(True, "post")],
        how="diagonal_relaxed",
    )
    week_stats = sources.fetch_player_stats(True, "week")

    season_rows = build_season_rows(season_stats, records, final)
    week_rows = build_week_rows(week_stats, game_teams, final)

    with get_connection() as conn:
        upsert_teams(conn, sources.fetch_teams())
        upsert_players(conn, sources.fetch_players())
        n_season = upsert_player_season(conn, season_rows)
        n_week = upsert_player_week(conn, week_rows)
        write_ingest_log(
            conn,
            job="raw_load",
            season=None,
            rows_written=n_season + n_week,
            status="success",
            error=None,
            started_at=started,
            completed_at=datetime.now(),
        )
    print(f"season rows: {n_season}, week rows: {n_week}")
