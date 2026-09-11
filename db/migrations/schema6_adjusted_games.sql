-- Adjusted games played, and record tiers graded against it.
--
-- adjusted_games_played = games_played * snap_pct / 100: the number of full
-- games' worth of offensive snaps a quarterback was actually on the field for.
--
-- adjusted_record_tiers are graded against the SAME thresholds_v2025.json as
-- record_tiers; only the proration divisor changes. Null wherever snap counts
-- are unavailable (before 2013, or not yet published for a recent game).

alter table player_season add column adjusted_games_played numeric;
alter table player_season add column adjusted_record_tiers jsonb not null default '{}';
