import { supabase, type StatRow } from "@/lib/supabase";
import { statsForView } from "@/lib/tiers";
import Controls from "./Controls";
import StatTable from "./StatTable";

export const revalidate = 3600;

const VIEWS = ["season_REG", "season_POST", "week_REG", "week_POST"] as const;

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const view = pickView(params.view);
  const granularity = view.startsWith("season") ? "season" : "week";
  const seasonType = view.endsWith("REG") ? "REG" : "POST";
  const mode = params.mode === "performance" ? "performance" : "record";
  const table = granularity === "season" ? "player_season" : "player_week";

  const seasons = await loadSeasons();
  const season = Number(params.season) || seasons[0];

  // Weeks are read from the data rather than assumed (D4). A 1999 regular season
  // has 17 weeks, a 2021+ one has 18, and the postseason numbers its rounds
  // separately -- hardcoding any of that would silently drop games.
  const weeks =
    granularity === "week" ? await loadWeeks(seasonType, season) : [];
  const week = granularity === "week" ? Number(params.week) || weeks[0] : null;

  let query = supabase
    .from(table)
    .select("*, player!inner(display_name)")
    .eq("season", season)
    .eq("season_type", seasonType);
  if (week !== null) query = query.eq("week", week);

  const { data, error } = await query;
  if (error) throw new Error(`Supabase query failed: ${error.message}`);
  const rows = (data ?? []) as unknown as StatRow[];

  const stats = statsForView(view);
  const isFinal = rows.length > 0 && rows.every((r) => r.is_final);

  return (
    <main className="mx-auto flex w-full max-w-[1800px] flex-col gap-5 px-4 py-6">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
          QB Records
        </h1>
        <p className="text-sm text-neutral-500">
          {rows.length} quarterback{rows.length === 1 ? "" : "s"} ·{" "}
          {season}
          {week !== null ? ` week ${week}` : ""} ·{" "}
          {seasonType === "REG" ? "regular season" : "postseason"}
          {rows.length > 0 && !isFinal ? (
            <span className="ml-2 rounded bg-amber-200 px-1.5 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-500/25 dark:text-amber-200">
              in progress — record tiers read as on-pace
            </span>
          ) : null}
        </p>
      </header>

      <Controls
        seasons={seasons}
        weeks={weeks}
        season={season}
        view={view}
        week={week}
        mode={mode}
      />

      <StatTable
        rows={rows}
        stats={stats}
        mode={mode}
        granularity={granularity}
      />

      <footer className="text-xs leading-relaxed text-neutral-500">
        <p>
          Data from nflverse, 1999 onward. Greyed names fall below the qualifying
          threshold of 10 attempts per game — they are graded, but they do not
          define the scale.
        </p>
        <p className="mt-1">
          <span className="italic">∞</span> perfect (no interceptions) ·{" "}
          <span className="italic">—</span> incalculable (divide by zero) ·{" "}
          <span>·</span> not recorded that season (QBR from 2006, snap% from
          2013)
        </p>
      </footer>
    </main>
  );
}

function pickView(raw: string | string[] | undefined): (typeof VIEWS)[number] {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return VIEWS.includes(value as (typeof VIEWS)[number])
    ? (value as (typeof VIEWS)[number])
    : "season_REG";
}

async function loadSeasons(): Promise<number[]> {
  const { data, error } = await supabase
    .from("player_season")
    .select("season")
    .order("season", { ascending: false });
  if (error) throw new Error(`Could not load seasons: ${error.message}`);
  return [...new Set((data ?? []).map((r) => r.season as number))];
}

async function loadWeeks(seasonType: string, season: number): Promise<number[]> {
  const { data, error } = await supabase
    .from("player_week")
    .select("week")
    .eq("season", season)
    .eq("season_type", seasonType)
    .order("week", { ascending: true });
  if (error) throw new Error(`Could not load weeks: ${error.message}`);
  return [...new Set((data ?? []).map((r) => r.week as number))];
}
