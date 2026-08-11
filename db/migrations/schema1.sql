create table player (
  player_id        text primary key,
  pfr_id           text,
  espn_id          text,
  display_name     text not null,
  position         text,
  birth_date       date,
  rookie_year      int
);

create index on player (display_name);

create table team (
  team_abbr        text primary key,
  team_name        text,
  primary_color    text,
  secondary_color  text
);

create table player_season (
  player_id            text references player,
  season               int not null,
  season_type          text not null check (season_type in ('REG','POST')),
  team_abbr            text,
  games_played         int not null,
  games_started        int,
  wins                 int,
  losses               int,
  ties                 int,

  completions          int,
  attempts             int,
  passing_yards        int,
  passing_tds          int,
  interceptions        int,
  sacks                int,
  sack_yards           int,
  rushing_yards        int,
  rushing_tds          int,
  rushing_attempts     int,
  fumbles              int,

  qbr                  numeric,
  offensive_snaps      int,
  team_offensive_snaps int,

  completion_pct       numeric,
  yards_per_completion numeric,
  yards_per_attempt    numeric,
  td_pct               numeric,
  int_pct              numeric,
  td_int_ratio         numeric,
  sack_pct             numeric,
  rush_yards_per_att   numeric,
  passer_rating        numeric,
  any_a                numeric,
  total_tds            int,
  total_yards          int,
  snap_pct             numeric,

  sentinels            jsonb not null default '{}',
  record_tiers         jsonb not null default '{}',
  season_percentiles   jsonb not null default '{}',

  is_final             boolean not null default false,
  is_qualified         boolean not null default false,
  data_source          text not null default 'nflverse',
  updated_at           timestamptz not null default now(),
  primary key (player_id, season, season_type)
);

create index on player_season (season, season_type);

create table player_week (
  player_id            text references player,
  season               int not null,
  season_type          text not null check (season_type in ('REG','POST')),
  week                 int not null,
  team_abbr            text,
  opponent_abbr        text,
  result               text,

  completions          int,
  attempts             int,
  passing_yards        int,
  passing_tds          int,
  interceptions        int,
  sacks                int,
  sack_yards           int,
  rushing_yards        int,
  rushing_tds          int,
  rushing_attempts     int,
  fumbles              int,

  qbr                  numeric,
  offensive_snaps      int,
  team_offensive_snaps int,

  completion_pct       numeric,
  yards_per_completion numeric,
  yards_per_attempt    numeric,
  td_pct               numeric,
  int_pct              numeric,
  td_int_ratio         numeric,
  sack_pct             numeric,
  rush_yards_per_att   numeric,
  passer_rating        numeric,
  any_a                numeric,
  total_tds            int,
  total_yards          int,
  snap_pct             numeric,

  sentinels            jsonb not null default '{}',
  record_tiers         jsonb not null default '{}',
  week_percentiles     jsonb not null default '{}',

  is_final             boolean not null default false,
  is_qualified         boolean not null default false,
  data_source          text not null default 'nflverse',
  updated_at           timestamptz not null default now(),
  primary key (player_id, season, season_type, week)
);

create index on player_week (season, season_type, week);

create table ingest_log (
  id           bigserial primary key,
  job          text not null,
  season       int,
  rows_written int,
  status       text not null check (status in ('success','failed')),
  error        text,
  started_at   timestamptz not null,
  completed_at timestamptz
);
