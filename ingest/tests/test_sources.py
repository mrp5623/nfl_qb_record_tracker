import pytest

from ingest.sources import (
    REQUIRED_COLUMNS,
    verify_columns,
    fetch_player_stats,
    MissingColumnsError,
    fetch_schedules

)
def test_verify_columns_full():
    df = fetch_player_stats(2025, "week")
    verify_columns(df, "player_stats_week") 

@pytest.mark.parametrize("col", sorted(REQUIRED_COLUMNS["player_stats_week"]))
def test_verify_columns_dropped(col):
    df = fetch_player_stats(2025, "week")
    with pytest.raises(MissingColumnsError, match=col):
        verify_columns(df.drop(col), "player_stats_week") 

@pytest.mark.parametrize("season", [1999, 2002, 2010, 2016, 2020, 2025])
def test_sources_agree_on_team_abbreviations(season):
    ps = fetch_player_stats(season, "reg")
    sch = fetch_schedules(season)
    ps_teams = {t for t in ps["recent_team"].to_list() if t}
    sch_teams = {t for t in sch["home_team"].to_list() if t} | {t for t in sch["away_team"].to_list() if t}
    assert ps_teams == sch_teams
