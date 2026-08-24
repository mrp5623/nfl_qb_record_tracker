import { createClient } from "@supabase/supabase-js";

// Read-only client, used from server components only.
//
// The publishable key is designed to be public -- it is what ships to browsers
// in a normal Supabase app. What actually protects the data is row-level
// security: db/migrations/schema2_rls.sql enables RLS on every table and grants
// SELECT only. There is no INSERT/UPDATE/DELETE policy, so writes through this
// key are refused by the database rather than by our own code.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!url || !key) {
  throw new Error(
    "Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY. " +
      "Copy web/.env.example to web/.env.local and fill it in.",
  );
}

export const supabase = createClient(url, key, {
  auth: { persistSession: false },
});

/** One row of either player_season or player_week, plus the joined player name. */
export type StatRow = {
  player_id: string;
  season: number;
  season_type: "REG" | "POST";
  week?: number;
  team_abbr: string | null;
  opponent_abbr?: string | null;
  result?: string | null;
  games_played?: number;
  wins?: number | null;
  losses?: number | null;
  ties?: number | null;
  is_qualified: boolean;
  is_final: boolean;
  sentinels: Record<string, string>;
  record_tiers: Record<string, string>;
  season_percentiles?: Record<string, number>;
  week_percentiles?: Record<string, number>;
  player: { display_name: string } | null;
} & Record<string, unknown>;
