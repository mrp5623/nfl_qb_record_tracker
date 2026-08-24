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


if __name__ == "__main__":
    from ingest import sources

    started = datetime.now()
    with get_connection() as conn:
        n_teams = upsert_teams(conn, sources.fetch_teams())
        n_players = upsert_players(conn, sources.fetch_players())
        write_ingest_log(
            conn,
            job="seed_players_and_teams",
            season=None,
            rows_written=n_teams + n_players,
            status="success",
            error=None,
            started_at=started,
            completed_at=datetime.now(),
        )
    print(f"teams: {n_teams}, players: {n_players}")
