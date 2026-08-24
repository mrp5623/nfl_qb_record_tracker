-- Threshold generation reference (parent spec section 7.2).
--
-- ingest/thresholds.py composes these same queries for every stat and view.
-- This file is the readable version: paste any block into the Supabase SQL
-- editor to check what the pipeline is doing. passing_yards / season_REG is the
-- worked example throughout.
--
-- The whole point of section 7.2 is that the record tier and the distribution
-- tiers are computed over DIFFERENT POPULATIONS:
--
--   record tier        all finalized seasons, qualified or not
--   every other tier   finalized AND qualified seasons only
--
-- A record needs no qualifier, since you cannot accumulate an extreme total
-- without playing. The distribution is the opposite: including mop-up duty would
-- define "average" using appearances nobody would call a season.


-- 1. Record tier -----------------------------------------------------------
--
-- max(), for every stat in both directions.
--
-- That is not a typo for a lower-is-better stat. min(interceptions) returns 0,
-- achieved by anyone who threw fifteen passes without being picked -- an absence,
-- not a record. So `record` here means "historically extreme", not "best": the
-- most yards, and the most interceptions. The legacy sheet already worked this
-- way, with INT reading `record: gt 35`.
--
-- max() ignores NULLs, which is what makes era-gated stats work for free: qbr is
-- NULL before 2006, so the 1999-2005 rows drop out without a season filter.

select max(passing_yards) as record_value,
       count(passing_yards) as n
from player_season
where season_type = 'REG'
  and is_final = true;


-- 1b. Record tier for a RATE stat, which needs a games floor ----------------
--
-- A rate over a tiny sample produces a nonsense extreme. Run this three ways and
-- watch the "record" move:
--
--   no filter          100.0  Trent Edwards 2012, who went 1-for-1
--   is_qualified        90.9  Mike Glennon 2016, a handful of appearances
--   games_played >= 14  74.4  Drew Brees 2018   <-- the legacy sheet's number
--
-- passer_rating does the same thing: 158.3 -> 157.9 -> 122.5 (Rodgers 2011,
-- again the legacy value). Counting stats need no such floor in either
-- direction, and week views need none because one game IS the sample.

select max(completion_pct) as record_value,
       count(completion_pct) as n
from player_season
where season_type = 'REG'
  and is_final = true
  and games_played >= 14;


-- 2. Distribution tiers ----------------------------------------------------
--
-- percentile_cont is an ORDERED-SET AGGREGATE, and its syntax is unlike any
-- other aggregate. The fraction goes in the normal argument slot; the column
-- being ranked goes in a separate `within group (order by ...)` clause:
--
--     percentile_cont(0.90) within group (order by passing_yards)
--                     ^^^^                          ^^^^^^^^^^^^^
--                     which percentile              of what
--
-- `_cont` means continuous: it interpolates between the two straddling rows
-- rather than returning an actual row's value. percentile_disc would return a
-- real observed value instead. Continuous is right here because a threshold is
-- a cutoff, not an observation.
--
-- NOTE the value being ranked is a PER-GAME rate scaled to 17, not the season
-- total. D9's 10-attempts-per-game rule qualifies a QB who played two games, so
-- the median qualified season is only 10 games long and raw percentiles would
-- describe half-seasons -- which proration then scales UP by the player's games,
-- grading a 17-game starter against a bar set by half-seasons. Compare:
--
--                    raw p50   per-game p50 x17   legacy hand-picked
--   passing_tds           10                 18                   18
--   completions          169                300                  285
--   passing_yards       1879               3340                 3000
--
-- The ::numeric cast is load-bearing. Both operands are integers, and Postgres
-- integer division would truncate to whole yards per game before the multiply.
--
-- This applies to season_REG only. season_POST's median qualified row is 2 games
-- and 160 of its 347 rows are a single game, so scaling to a 4-game denominator
-- would put "average" past what all but 16 postseasons in history reached.

select percentile_cont(0.90) within group (order by (passing_yards::numeric / games_played) * 17) as p90,
       percentile_cont(0.75) within group (order by (passing_yards::numeric / games_played) * 17) as p75,
       percentile_cont(0.50) within group (order by (passing_yards::numeric / games_played) * 17) as p50,
       percentile_cont(0.25) within group (order by (passing_yards::numeric / games_played) * 17) as p25,
       percentile_cont(0.10) within group (order by (passing_yards::numeric / games_played) * 17) as p10,
       count(passing_yards) as n
from player_season
where season_type = 'REG'
  and is_final = true
  and is_qualified = true
  and games_played > 0;

-- For a lower-is-better stat every cutpoint mirrors, because percentile_cont
-- always measures from the bottom of the ordering: elite is p10, not p90. Get
-- this backwards and the threshold set grades the worst seasons best, with
-- nothing in the JSON looking wrong.


-- 3. VERIFY: the qualifier is actually being applied ------------------------
--
-- `filter (where ...)` restricts one aggregate to a subset of the rows the
-- query already selected, so both populations can be measured side by side in a
-- single pass. It works on ordered-set aggregates too, which is not obvious, and
-- it is how thresholds.py gets record and distribution from one round trip.
--
-- These two medians MUST differ. If they come back identical, is_qualified is
-- not doing anything and every distribution tier is being defined by backups.
-- Expect 1001.5 against 1879.0.

select percentile_cont(0.50) within group (order by passing_yards)
         as median_all,
       percentile_cont(0.50) within group (order by passing_yards)
         filter (where is_qualified) as median_qualified,
       count(*) as n_all,
       count(*) filter (where is_qualified) as n_qualified
from player_season
where season_type = 'REG'
  and is_final = true;


-- 4. VERIFY: the record tier is a season you can name -----------------------
--
-- A record LOWER than a season you know happened means is_final or the
-- qualifier is wrongly filtering the record population.
--
-- Expect Manning 2013 at 5477 -- except nflverse credits Brees 2011 with 5535,
-- a divergence verified upstream at the Phase 1 gate and accepted on
-- 2026-08-11. Six of the other seven counting records match the record books.

select p.display_name, s.season, s.passing_yards
from player_season s
join player p using (player_id)
where s.season_type = 'REG'
  and s.is_final = true
order by s.passing_yards desc nulls last
limit 5;


-- 5. Population report (Task 20) -------------------------------------------
--
-- What D9's 10-attempts-per-game rule actually admits, per season. The headline
-- number: median games_played among qualified regular seasons is 10, and p25 is
-- 5. That is the finding block 2 exists to work around.

select season,
       count(*) as seasons_total,
       count(*) filter (where is_qualified) as seasons_qualified,
       round(100.0 * count(*) filter (where is_qualified) / count(*), 1) as pct,
       percentile_cont(0.50) within group (order by games_played)
         filter (where is_qualified) as median_games_qualified
from player_season
where season_type = 'REG'
  and is_final = true
group by season
order by season;
