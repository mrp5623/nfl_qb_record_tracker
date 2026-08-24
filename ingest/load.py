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

import json
import os
from pathlib import Path
from datetime import datetime

import polars as pl
import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Json

from ingest import derive, grade
from ingest.registry import STATS

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
    rows = df.select(columns).rows()
    if "sentinels" not in columns:
        return rows
    at = columns.index("sentinels")
    wrapped = []
    for r in rows:
        r = list(r)
        r[at] = Json(json.loads(r[at]) if isinstance(r[at], str) else (r[at] or {}))
        wrapped.append(tuple(r))
    return wrapped


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

DERIVED_COLUMNS_FWD = [
    "completion_pct", "yards_per_completion", "yards_per_attempt", "td_pct",
    "int_pct", "td_int_ratio", "sack_pct", "rush_yards_per_att",
    "passer_rating", "any_a", "total_tds", "total_yards", "snap_pct",
]
EXTERNAL_COLUMNS_FWD = ["qbr", "offensive_snaps", "team_offensive_snaps"]

SEASON_COLUMNS = [
    "player_id", "season", "season_type", "team_abbr",
    "games_played", "games_started", "wins", "losses", "ties",
    *STAT_COLUMN_MAP.values(),
    *EXTERNAL_COLUMNS_FWD, *DERIVED_COLUMNS_FWD, "sentinels",
    "record_tiers", "season_percentiles",
    "is_final", "is_qualified",
]

WEEK_COLUMNS = [
    "player_id", "season", "season_type", "week",
    "team_abbr", "opponent_abbr", "result",
    *STAT_COLUMN_MAP.values(),
    *EXTERNAL_COLUMNS_FWD, *DERIVED_COLUMNS_FWD, "sentinels",
    "record_tiers", "week_percentiles",
    "is_final", "is_qualified",
]

# The grading columns are added after the frame is built (see add_grade_columns),
# so the build step selects everything except them and the upsert selects the lot.
SEASON_GRADE_COLUMNS = ["record_tiers", "season_percentiles"]
WEEK_GRADE_COLUMNS = ["record_tiers", "week_percentiles"]
SEASON_BUILD_COLUMNS = [c for c in SEASON_COLUMNS if c not in SEASON_GRADE_COLUMNS]
WEEK_BUILD_COLUMNS = [c for c in WEEK_COLUMNS if c not in WEEK_GRADE_COLUMNS]

QUALIFYING_ATTEMPTS_PER_GAME = 10


def _renamed_stats(df: pl.DataFrame) -> pl.DataFrame:
    """Apply the nflverse -> schema column renaming, and fix the sack-yard sign.

    nflverse stores `sack_yards_lost` as a negative number (-15 for fifteen yards
    lost). We store it positive, because the column is graded lower-is-better:
    left negative, a bigger loss would sort as a better result. It also lets ANY/A
    subtract it the way the formula in parent spec section 6.1 is written.
    """
    return df.rename(STAT_COLUMN_MAP).with_columns(
        pl.col("sack_yards").abs()
    )


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
    stats: pl.DataFrame, records: pl.DataFrame, final: set[int],
    qbr: pl.DataFrame, snaps: pl.DataFrame,
) -> pl.DataFrame:
    """Assemble player_season rows, fully derived."""
    joined = (
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
        .join(qbr, on=["player_id", "season", "season_type"], how="left")
        .join(snaps, on=["player_id", "season", "season_type"], how="left")
    )
    return add_derived_columns(joined).select(SEASON_BUILD_COLUMNS)


def build_week_rows(
    stats: pl.DataFrame, game_teams: pl.DataFrame, final: set[int],
    qbr: pl.DataFrame, snaps: pl.DataFrame,
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

    joined = (
        joined.with_columns(
            pl.col("season").is_in(list(final)).alias("is_final"),
            (pl.col("attempts") >= QUALIFYING_ATTEMPTS_PER_GAME).alias("is_qualified"),
        )
        .join(qbr, on=["player_id", "season", "season_type", "week"], how="left")
        .join(snaps, on=["player_id", "season", "season_type", "week"], how="left")
    )
    return add_derived_columns(joined).select(WEEK_BUILD_COLUMNS)


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


# ---------------------------------------------------------------------------
# Task 24: grading backfill
# ---------------------------------------------------------------------------


def add_grade_columns(
    df: pl.DataFrame, thresholds: dict, granularity: str
) -> pl.DataFrame:
    """Add `record_tiers` and the percentile column to a built frame.

    Grading happens here, inside the normal build, rather than as a separate
    UPDATE pass over the table. That is what makes it idempotent for free: the
    tiers ride along in the same upsert as the numbers they describe, so there is
    no window in which a row's stats and its grades disagree, and a rerun
    recomputes both from the same inputs.

    REG and POST are graded separately even though they share a table. They are
    different views with different thresholds -- a 300-yard playoff game is not
    measured against a 17-game regular season -- and grading them together would
    quietly apply the regular-season ladder to both.
    """
    pct_column = "season_percentiles" if granularity == "season" else "week_percentiles"
    partition = ["season", "season_type"]
    if granularity == "week":
        partition.append("week")

    graded: list[pl.DataFrame] = []
    for season_type in ("REG", "POST"):
        part = df.filter(pl.col("season_type") == season_type)
        if part.height == 0:
            continue
        view = thresholds["views"][f"{granularity}_{season_type}"]

        percentiles = {
            name: grade.performance_percentiles(part, STATS[name], partition)
            for name in view["stats"]
            if name in STATS and STATS[name].field in part.columns
        }

        tiers_json: list[str] = []
        pct_json: list[str] = []
        for i, row in enumerate(part.iter_rows(named=True)):
            raw = row.get("sentinels") or "{}"
            sentinels = json.loads(raw) if isinstance(raw, str) else raw
            tiers_json.append(json.dumps(grade.grade_row(row, view, sentinels)))
            # A sentinel cell gets neither a tier nor a percentile (parent 8.1).
            pct_json.append(
                json.dumps(
                    {
                        name: series[i]
                        for name, series in percentiles.items()
                        if name not in sentinels and series[i] is not None
                    }
                )
            )

        graded.append(
            part.with_columns(
                pl.Series("record_tiers", tiers_json),
                pl.Series(pct_column, pct_json),
            )
        )

    return pl.concat(graded, how="diagonal_relaxed")


# ---------------------------------------------------------------------------
# Task 14: ESPN QBR
# ---------------------------------------------------------------------------

# QBR labels its seasons "Regular" / "Playoffs", not "REG" / "POST". Joining on
# the raw value matches nothing and silently produces an all-null column.
QBR_SEASON_TYPES = {"Regular": "REG", "Playoffs": "POST"}

# ESPN files two 2009 rows under week_text "Pro Bowl" at game_week 4, the Super
# Bowl slot -- and 2009 has no row actually labelled "Super Bowl". The two players
# are Peyton Manning and Drew Brees, who started Super Bowl XLIV and, being Super
# Bowl participants, did not play that year's Pro Bowl. It is a mislabel.
#
# Rather than special-casing the label, nothing is filtered on it: QBR is joined
# onto player_week rows that already exist, so a value can only attach to a game
# the quarterback actually played. A genuine Pro Bowl row would find no matching
# row and be dropped by the join.


def _espn_to_gsis(players: pl.DataFrame) -> pl.DataFrame:
    """Map ESPN player ids onto gsis ids.

    Both columns are strings, so no casting is needed -- worth re-checking if
    either source changes, because a dtype mismatch would match zero rows
    without raising.
    """
    return (
        players.filter(pl.col("espn_id").is_not_null())
        .select(
            pl.col("espn_id").alias("qbr_player_id"),
            pl.col("gsis_id").alias("player_id"),
        )
        .unique(subset=["qbr_player_id"])
    )


def qbr_season_lookup(qbr: pl.DataFrame, players: pl.DataFrame) -> pl.DataFrame:
    """QBR keyed by (player_id, season, season_type), regular and postseason.

    Parent spec section 10.3 drops QBR from postseason views, but its stated
    reason is that the original sheet omitted it -- and that omission was because
    the data could not be found, not because it was unwanted. ESPN does publish
    it, so it is included here (design doc D8, revised 2026-08-11).

    season_type is carried so regular and postseason values cannot cross.
    """
    return (
        qbr.filter(pl.col("season_type").is_in(list(QBR_SEASON_TYPES)))
        .select(
            pl.col("player_id").alias("qbr_player_id"),
            "season",
            pl.col("season_type").replace_strict(QBR_SEASON_TYPES).alias("season_type"),
            pl.col("qbr_total").alias("qbr"),
        )
        .join(_espn_to_gsis(players), on="qbr_player_id", how="inner")
        .select("player_id", "season", "season_type", "qbr")
        .unique(subset=["player_id", "season", "season_type"])
    )


def qbr_week_lookup(qbr: pl.DataFrame, players: pl.DataFrame) -> pl.DataFrame:
    """QBR keyed by (player_id, season, season_type, week).

    Playoff `game_week` is already 1-4 and lines up with the round numbering used
    everywhere else in the pipeline, so no conversion is needed.
    """
    return (
        qbr.filter(pl.col("season_type").is_in(list(QBR_SEASON_TYPES)))
        .select(
            pl.col("player_id").alias("qbr_player_id"),
            "season",
            pl.col("season_type").replace_strict(QBR_SEASON_TYPES).alias("season_type"),
            pl.col("game_week").alias("week"),
            pl.col("qbr_total").alias("qbr"),
        )
        .join(_espn_to_gsis(players), on="qbr_player_id", how="inner")
        .select("player_id", "season", "season_type", "week", "qbr")
        .unique(subset=["player_id", "season", "season_type", "week"])
    )


# ---------------------------------------------------------------------------
# Task 15: snap counts
# ---------------------------------------------------------------------------


def _pfr_to_gsis(players: pl.DataFrame) -> pl.DataFrame:
    """Map Pro-Football-Reference ids onto gsis ids."""
    return (
        players.filter(pl.col("pfr_id").is_not_null())
        .select(
            pl.col("pfr_id").alias("pfr_player_id"),
            pl.col("gsis_id").alias("player_id"),
        )
        .unique(subset=["pfr_player_id"])
    )


def snap_rows(
    snaps: pl.DataFrame, players: pl.DataFrame, game_teams: pl.DataFrame
) -> pl.DataFrame:
    """Offensive snaps per player-game, with the team total for that game.

    team_offensive_snaps is not a column in the source. Parent spec section 6.1
    assumes one, and the obvious reconstruction -- offense_snaps / offense_pct --
    is unreliable: offense_pct is rounded to two decimals, so dividing a small
    snap count by it disagrees between players on the same team (only 6 of 570
    game-teams agreed in 2025).

    Taking the maximum offensive snaps in a game-team is reliable instead: some
    player logs 100 percent of snaps in 567 of 570 game-teams, and the value
    matches the implied total within two snaps everywhere.
    """
    offense = snaps.filter(pl.col("offense_snaps") > 0)

    team_totals = (
        offense.group_by(["game_id", "team"])
        .agg(pl.col("offense_snaps").max().alias("team_offensive_snaps"))
        .rename({"team": "team_abbr"})
    )

    return (
        offense.select(
            "game_id",
            pl.col("team").alias("team_abbr"),
            "pfr_player_id",
            pl.col("offense_snaps").alias("offensive_snaps"),
        )
        .join(team_totals, on=["game_id", "team_abbr"])
        .join(_pfr_to_gsis(players), on="pfr_player_id", how="inner")
        .join(
            game_teams.select("game_id", "team_abbr", "season", "season_type", "week"),
            on=["game_id", "team_abbr"],
            how="inner",
        )
        .select(
            "player_id", "season", "season_type", "week",
            "offensive_snaps", "team_offensive_snaps",
        )
    )


def snap_season_totals(snap_rows_df: pl.DataFrame) -> pl.DataFrame:
    """Season snap totals per quarterback.

    Sums both sides so snap_pct can be recomputed from the totals. Averaging the
    weekly percentages would weight a 5-snap relief appearance the same as a
    70-snap start.
    """
    return snap_rows_df.group_by(["player_id", "season", "season_type"]).agg(
        pl.col("offensive_snaps").sum(),
        pl.col("team_offensive_snaps").sum(),
    )


# ---------------------------------------------------------------------------
# Task 16: derived columns and sentinels
# ---------------------------------------------------------------------------


def add_derived_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Compute every derived stat and sentinel, row by row.

    Deliberately calls the functions in derive.py rather than restating the
    formulas as Polars expressions. A second implementation would be a second
    thing to keep correct, and the tested one would stop being the one that runs.
    20k rows of Python is fast enough that speed is not worth that trade.
    """
    out: list[dict] = []
    for row in df.iter_rows(named=True):
        r = dict(row)
        cmp_ = r.get("completions") or 0
        att = r.get("attempts") or 0
        yds = r.get("passing_yards") or 0
        ptd = r.get("passing_tds") or 0
        ints = r.get("interceptions") or 0
        sks = r.get("sacks") or 0
        sky = r.get("sack_yards") or 0
        ryd = r.get("rushing_yards") or 0
        rtd = r.get("rushing_tds") or 0
        ratt = r.get("rushing_attempts") or 0
        snaps = r.get("offensive_snaps") or 0
        team_snaps = r.get("team_offensive_snaps") or 0

        r["completion_pct"] = derive.completion_pct(cmp_, att)
        r["yards_per_completion"] = derive.yards_per_completion(yds, cmp_)
        r["yards_per_attempt"] = derive.yards_per_attempt(yds, att)
        r["td_pct"] = derive.td_pct(ptd, att)
        r["int_pct"] = derive.int_pct(ints, att)
        r["td_int_ratio"] = derive.td_int_ratio(ptd, ints)
        r["sack_pct"] = derive.sack_pct(sks, att)
        r["rush_yards_per_att"] = derive.rush_yards_per_att(ryd, ratt)
        r["passer_rating"] = derive.passer_rating(cmp_, att, yds, ptd, ints)
        r["any_a"] = derive.any_a(yds, ptd, ints, sky, att, sks)
        r["total_tds"] = derive.total_tds(ptd, rtd)
        r["total_yards"] = derive.total_yards(yds, ryd)
        r["snap_pct"] = derive.snap_pct(snaps, team_snaps)
        r["sentinels"] = json.dumps(derive.sentinels_for_row(r, r["season"]))
        out.append(r)
    return pl.DataFrame(out, infer_schema_length=None)


if __name__ == "__main__":
    from ingest import schedule, sources

    started = datetime.now()
    players = sources.fetch_players()
    schedules = sources.fetch_schedules(True)
    final = final_seasons(schedules)
    game_teams = schedule.game_team_rows(schedules)
    records = schedule.season_records(schedule.qb_game_results(schedules))

    qbr_season = qbr_season_lookup(sources.fetch_qbr("season"), players)
    qbr_week = qbr_week_lookup(sources.fetch_qbr("week"), players)
    snap_game = snap_rows(sources.fetch_snap_counts(True), players, game_teams)
    snap_season = snap_season_totals(snap_game)

    season_stats = pl.concat(
        [sources.fetch_player_stats(True, "reg"), sources.fetch_player_stats(True, "post")],
        how="diagonal_relaxed",
    )
    week_stats = sources.fetch_player_stats(True, "week")

    season_rows = build_season_rows(season_stats, records, final, qbr_season, snap_season)
    week_rows = build_week_rows(week_stats, game_teams, final, qbr_week, snap_game)

    thresholds_doc = json.loads(
        (Path(__file__).parents[1] / "config" / "thresholds_v2025.json").read_text(
            encoding="utf-8"
        )
    )
    season_rows = add_grade_columns(season_rows, thresholds_doc, "season")
    week_rows = add_grade_columns(week_rows, thresholds_doc, "week")

    with get_connection() as conn:
        upsert_teams(conn, sources.fetch_teams())
        upsert_players(conn, players)
        n_season = upsert_player_season(conn, season_rows)
        n_week = upsert_player_week(conn, week_rows)
        write_ingest_log(
            conn, job="full_load", season=None, rows_written=n_season + n_week,
            status="success", error=None, started_at=started,
            completed_at=datetime.now(),
        )
    print(f"season rows: {n_season}, week rows: {n_week}")
