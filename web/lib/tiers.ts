import statsJson from "./stats.generated.json";

/**
 * Stat definitions, exported from ingest/registry.py.
 *
 * Regenerate with `python -m ingest.registry` after editing the registry. D6
 * makes Python authoritative; this file only mirrors it.
 */
export type Stat = {
  field: string;
  display: string;
  kind: "counting" | "rate";
  direction: "higher_is_better" | "lower_is_better";
  prorate: "games" | "none";
  era_from: number;
  views: string[];
};

export const STATS = statsJson as Stat[];

export function statsForView(view: string): Stat[] {
  return STATS.filter((s) => s.views.includes(view));
}

export const TIERS = [
  "record",
  "elite",
  "good",
  "average",
  "below",
  "poor",
  "worst",
] as const;
export type Tier = (typeof TIERS)[number];

/**
 * Tier colours.
 *
 * Stored data names tiers semantically, never by colour (D2), so the entire
 * palette lives here and changing it costs nothing -- as opposed to the legacy
 * sheet, where the colour *was* the data.
 *
 * `record` gets amber rather than a deeper green. In the legacy sheet record and
 * elite were both dark green, which meant the single most interesting cell on
 * the page was indistinguishable from a merely great one. Separating them is the
 * main visual reason D2 was worth doing.
 */
export const TIER_STYLES: Record<Tier, string> = {
  record:
    "bg-amber-300 text-amber-950 font-semibold ring-1 ring-inset ring-amber-500 dark:bg-amber-400/90 dark:text-amber-950",
  elite: "bg-emerald-600 text-white dark:bg-emerald-600 dark:text-white",
  good: "bg-emerald-300 text-emerald-950 dark:bg-emerald-700/60 dark:text-emerald-50",
  average: "bg-yellow-200 text-yellow-950 dark:bg-yellow-600/40 dark:text-yellow-50",
  below: "bg-orange-200 text-orange-950 dark:bg-orange-700/40 dark:text-orange-50",
  poor: "bg-red-300 text-red-950 dark:bg-red-800/50 dark:text-red-50",
  worst: "bg-red-500 text-white dark:bg-red-900/80 dark:text-red-50",
};

export const TIER_LABELS: Record<Tier, string> = {
  record: "Record",
  elite: "Elite",
  good: "Good",
  average: "Average",
  below: "Below avg",
  poor: "Poor",
  worst: "Worst",
};

/**
 * Sentinel styles (parent spec 6.2).
 *
 * Three different reasons a cell has no number, and they must stay visually
 * distinct. `Perfect` is an achievement -- zero interceptions -- so it reads as
 * a highlight, not a gap. `Incalculable` is a real division by zero.
 * `Not Recorded` means the league was not tracking the stat that season, which
 * is the league's absence rather than the player's.
 */
export const SENTINEL_STYLES: Record<string, string> = {
  Perfect:
    "bg-sky-200 text-sky-900 italic dark:bg-sky-500/30 dark:text-sky-100",
  Incalculable:
    "text-neutral-400 italic dark:text-neutral-500",
  "Not Recorded":
    "text-neutral-300 dark:text-neutral-600",
};

export const SENTINEL_TEXT: Record<string, string> = {
  Perfect: "∞",
  Incalculable: "—",
  "Not Recorded": "·",
};

/**
 * Performance-mode colour: a continuous ramp rather than seven buckets.
 *
 * Deliberately different in character from record mode. A percentile is a
 * position on a smooth scale, and rendering it as discrete tiers would imply
 * boundaries that do not exist -- and would make the two modes look identical
 * when they are answering completely different questions.
 */
export function percentileStyle(p: number): React.CSSProperties {
  const hue = Math.round(p * 130); // 0 = red, 130 = green
  return {
    // Consumed by .pct-cell in globals.css, which picks one per colour scheme.
    ["--pct-light" as string]: `hsl(${hue} 72% ${90 - p * 12}%)`,
    ["--pct-dark" as string]: `hsl(${hue} 42% ${20 + p * 14}%)`,
  };
}

export function formatValue(value: unknown, kind: Stat["kind"]): string {
  if (value === null || value === undefined) return "";
  const n = typeof value === "string" ? Number(value) : (value as number);
  if (Number.isNaN(n)) return String(value);
  if (kind === "counting") return String(Math.round(n));
  return n.toFixed(1);
}
