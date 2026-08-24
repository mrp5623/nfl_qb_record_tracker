-- Public read access for the web app.
--
-- Supabase exposes every table in the `public` schema over PostgREST. Without
-- row-level security enabled, that exposure is governed by nothing at all, so
-- anyone holding the publishable key could write as well as read. Enabling RLS
-- flips the default to "deny everything", and each policy below opens exactly
-- one door: SELECT, for anyone, on data that is already public NFL statistics.
--
-- No INSERT, UPDATE or DELETE policy exists, so writes over the API are refused
-- for every role the key can reach. The ingest pipeline is unaffected: it
-- connects as the table owner over a direct Postgres connection, and an owner
-- bypasses RLS unless the table is set to FORCE.

alter table player enable row level security;
alter table team enable row level security;
alter table player_season enable row level security;
alter table player_week enable row level security;
alter table ingest_log enable row level security;

create policy "public read" on player        for select using (true);
create policy "public read" on team          for select using (true);
create policy "public read" on player_season for select using (true);
create policy "public read" on player_week   for select using (true);

-- ingest_log gets RLS with no policy at all: locked to the owner. Job history
-- and error strings are operational detail, not part of the product.
