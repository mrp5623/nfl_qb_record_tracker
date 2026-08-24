"""nflverse data acquisition.

The only module besides `load.py` that touches the network. Every fetch verifies
its columns before returning, so a renamed upstream column fails loudly here
rather than silently producing nulls downstream (parent spec section 13).
"""

from pathlib import Path
from typing import Literal

import nflreadpy as nfl
import polars as pl
from nflreadpy.config import update_config
from nflreadpy.downloader import get_downloader

CACHE_DIR = Path(__file__).parents[1] / ".cache"

QBR_SEASON_PATH = "espn_data/qbr_season_level"
QBR_WEEK_PATH = "espn_data/qbr_week_level"

# Sources disagree about franchise abbreviations, and disagree inconsistently:
# player_stats uses modern abbreviations from 2003 onward but historical ones for
# 1999-2002, while schedules and snap_counts stay historical until the actual
# relocation. Normalizing every source onto one set is what makes the Task 7
# schedule join and the Task 15 snap join line up.
#
# Targets are what the majority of sources already use -- note the Rams are "LA",
# not "LAR"; "LAR" exists in load_teams() but appears in no other source.
TEAM_RELOCATIONS: dict[str, str] = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LA",
    "JAC": "JAX",
}

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "player_stats_week": frozenset({
        "player_id", "player_display_name", "position", "season", "week",
        "season_type", "team", "opponent_team", "completions", "attempts",
        "passing_yards", "passing_tds", "passing_interceptions",
        "sacks_suffered", "sack_yards_lost", "carries", "rushing_yards",
        "rushing_tds", "fumbles_total",
    }),
    "player_stats_season": frozenset({
        "player_id", "player_display_name", "position", "season", "season_type",
        "recent_team", "games", "completions", "attempts", "passing_yards",
        "passing_tds", "passing_interceptions", "sacks_suffered",
        "sack_yards_lost", "carries", "rushing_yards", "rushing_tds",
        "fumbles_total",
    }),
    "players": frozenset({
        "gsis_id", "display_name", "position", "birth_date", "rookie_season",
        "pfr_id", "espn_id",
    }),
    "schedules": frozenset({
        "game_id", "season", "game_type", "week", "away_team", "away_score",
        "home_team", "home_score", "away_qb_id", "home_qb_id",
    }),
    "snap_counts": frozenset({
        "pfr_player_id", "season", "game_type", "week", "team",
        "offense_snaps", "offense_pct",
    }),
    "teams": frozenset({"team_abbr", "team_name", "team_color", "team_color2"}),
    "qbr_season": frozenset({
        "season", "season_type", "player_id", "qbr_total", "team_abb",
    }),
    "qbr_week": frozenset({
        "season", "season_type", "game_week", "player_id", "qbr_total",
        "team_abb",
    }),
}


class MissingColumnsError(Exception):
    """Raised when a source is missing a column the pipeline consumes."""


_cache_configured = False


def _ensure_cache_configured() -> None:
    """Point nflreadpy's cache at the project directory, once per process.

    nflreadpy defaults to an in-memory cache, which is discarded between runs.
    Filesystem caching makes reruns and the test suite work offline.
    """
    global _cache_configured
    if _cache_configured:
        return
    CACHE_DIR.mkdir(exist_ok=True)
    update_config(cache_mode="filesystem", cache_dir=CACHE_DIR)
    _cache_configured = True


def verify_columns(df: pl.DataFrame, source: str) -> None:
    """Raise if `df` is missing any column the pipeline reads from `source`.

    Extra columns are fine — nflverse ships ~145 and we consume ~19.
    """
    if source not in REQUIRED_COLUMNS:
        raise KeyError(f"{source!r} has no entry in REQUIRED_COLUMNS")

    missing = REQUIRED_COLUMNS[source] - set(df.columns)
    if missing:
        raise MissingColumnsError(
            f"{source} is missing {sorted(missing)}. "
            f"nflverse may have renamed them; got {sorted(df.columns)}"
        )


def normalize_teams(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """Map relocated franchises onto their current abbreviation.

    nflreadpy has no equivalent of nflreadr's `clean_team_abbrs()`, so the
    mapping is explicit. Unlisted values pass through unchanged.
    """
    return df.with_columns(pl.col(col).replace(TEAM_RELOCATIONS))


def filter_quarterbacks(df: pl.DataFrame) -> pl.DataFrame:
    """Keep QBs by listed position, never by whether they threw a pass.

    A QB with zero attempts in a game is still a valid row (parent spec
    section 4).
    """
    return df.filter(pl.col("position") == "QB")


def fetch_player_stats(
    seasons: list[int] | int | bool,
    summary_level: Literal["week", "reg", "post", "reg+post"] = "week",
) -> pl.DataFrame:
    """QB passing and rushing stats, one row per player-week or player-season."""
    _ensure_cache_configured()
    df = nfl.load_player_stats(seasons=seasons, summary_level=summary_level)

    source = "player_stats_week" if summary_level == "week" else "player_stats_season"
    verify_columns(df, source)

    df = filter_quarterbacks(df)
    team_col = "team" if summary_level == "week" else "recent_team"
    df = normalize_teams(df, team_col)
    if summary_level == "week":
        df = normalize_teams(df, "opponent_team")
    return df


def fetch_players() -> pl.DataFrame:
    """Player identity and the join keys for QBR (espn_id) and snaps (pfr_id)."""
    _ensure_cache_configured()
    df = nfl.load_players()
    verify_columns(df, "players")
    return df


def fetch_teams() -> pl.DataFrame:
    """Team abbreviations, names, and colors. Includes relocated franchises."""
    _ensure_cache_configured()
    df = nfl.load_teams()
    verify_columns(df, "teams")
    return df


def fetch_schedules(seasons: list[int] | int | bool = True) -> pl.DataFrame:
    """Game results. The only source for W-L and games_started."""
    _ensure_cache_configured()
    df = nfl.load_schedules(seasons=seasons)
    verify_columns(df, "schedules")
    df = normalize_teams(df, "home_team")
    df = normalize_teams(df, "away_team")
    return df


def fetch_snap_counts(seasons: list[int] | int | bool) -> pl.DataFrame:
    """Per-game snap counts, 2012+. Season totals require aggregation."""
    _ensure_cache_configured()
    df = nfl.load_snap_counts(seasons=seasons)
    verify_columns(df, "snap_counts")
    return normalize_teams(df, "team")


def fetch_qbr(level: Literal["season", "week"]) -> pl.DataFrame:
    """ESPN QBR, 2006+.

    nflreadpy has no `load_espn_qbr()` — that function is R-only. Going through
    nflreadpy's downloader rather than raw HTTP means QBR is cached like every
    other source. `player_id` here is an ESPN id, not a gsis id.
    """
    _ensure_cache_configured()
    path = QBR_SEASON_PATH if level == "season" else QBR_WEEK_PATH
    df = get_downloader().download("nflverse-data", path)
    verify_columns(df, f"qbr_{level}")
    return normalize_teams(df, "team_abb")
