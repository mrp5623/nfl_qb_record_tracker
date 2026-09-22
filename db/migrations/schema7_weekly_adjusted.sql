-- Adjusted record tiers for single games: counting-stat thresholds scaled by the
-- share of offensive snaps played (see ingest/grade.py per_snap_view).
alter table player_week add column adjusted_record_tiers jsonb not null default '{}';
