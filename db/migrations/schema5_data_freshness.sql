-- Per-week record of which games are still waiting on snap counts or QBR.
--
-- The box score, snap counts and QBR are published by three different nflverse
-- releases on three different schedules: stats first, ESPN weekly QBR within
-- hours, Pro-Football-Reference snap counts around noon ET the day after a
-- game. The web app marks the QBR and SNAP% headers while they are behind.
--
-- Written by the ingest, which has all three sources in memory. Coverage is
-- judged per GAME -- providers publish a whole game at once, whereas one blank
-- cell can be permanent (ESPN withholds QBR below its threshold). A game counts
-- as covered if any player in it has the value.
--
-- The kickoff of the most recent still-missing game is stored rather than a
-- pending/not-pending boolean, and the app compares it to the clock. A few games
-- never get QBR at all (eight in 2013, some 2015-2019 playoff games), so
-- "pending until it arrives" would flag those forever; only a miss from a game
-- that kicked off in the last few days counts. Checking at view time also lets
-- the flag age out when no load runs, which after the season ends is always.

create table data_freshness (
    season                        int  not null,
    season_type                   text not null check (season_type in ('REG', 'POST')),
    week                          int  not null,
    games                         int  not null,
    games_missing_snaps           int  not null,
    games_missing_qbr             int  not null,
    latest_missing_snaps_kickoff  timestamptz,
    latest_missing_qbr_kickoff    timestamptz,
    updated_at                    timestamptz not null default now(),
    primary key (season, season_type, week)
);

alter table data_freshness enable row level security;
create policy "public read" on data_freshness for select using (true);
