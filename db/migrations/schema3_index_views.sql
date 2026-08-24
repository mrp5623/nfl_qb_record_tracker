-- Lightweight index views for the app's dropdowns.
--
-- PostgREST caps every response at 1000 rows by default. Selecting `season`
-- from all 2,485 player_season rows to derive a season list therefore returned
-- only the most recent 1000 -- which is 2015 through 2025 -- and the app's
-- season dropdown silently lost fifteen years. Nothing raised: a truncated list
-- is a valid list.
--
-- Raising the limit would have fixed the symptom while leaving the app fetching
-- thousands of rows to build a 27-item dropdown, and would break again the first
-- time the tables grow. These views return one row per distinct value instead,
-- so the answer is small no matter how large the fact tables get.
--
-- `security_invoker = on` matters. Without it a view runs with its OWNER's
-- rights and quietly bypasses the row-level security on the tables underneath,
-- which would make these views a hole in the policies added by schema2_rls.sql.
-- With it, the caller's permissions apply and the existing "public read"
-- policies govern the view exactly as they govern the tables.

create or replace view public.season_index with (security_invoker = on) as
select distinct season, season_type
from player_season;

create or replace view public.week_index with (security_invoker = on) as
select distinct season, season_type, week
from player_week;

grant select on public.season_index to anon, authenticated;
grant select on public.week_index to anon, authenticated;
