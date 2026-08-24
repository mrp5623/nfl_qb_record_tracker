"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useTransition } from "react";
import { TIERS, TIER_LABELS, TIER_STYLES } from "@/lib/tiers";

type Props = {
  seasons: number[];
  weeks: number[];
  season: number;
  view: string;
  week: number | null;
  mode: "record" | "performance";
};

export default function Controls({ seasons, weeks, season, view, week, mode }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  // Every control writes to the URL rather than to local state, so a given table
  // is a link. Sharing "Mahomes' 2026 through week 4" should not require
  // describing which dropdowns to touch.
  const setParam = useCallback(
    (updates: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(updates)) {
        if (v === null) next.delete(k);
        else next.set(k, v);
      }
      startTransition(() => router.push(`/?${next.toString()}`, { scroll: false }));
    },
    [params, router],
  );

  const isWeekly = view.startsWith("week");

  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
      <Field label="Season">
        <select
          value={season}
          onChange={(e) => setParam({ season: e.target.value, week: null })}
          className={selectClass}
        >
          {seasons.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </Field>

      <Field label="View">
        <select
          value={view}
          onChange={(e) => setParam({ view: e.target.value, week: null })}
          className={selectClass}
        >
          <option value="season_REG">Season — Regular</option>
          <option value="season_POST">Season — Postseason</option>
          <option value="week_REG">Weekly — Regular</option>
          <option value="week_POST">Weekly — Postseason</option>
        </select>
      </Field>

      {isWeekly && weeks.length > 0 ? (
        <Field label="Week">
          <select
            value={week ?? weeks[0]}
            onChange={(e) => setParam({ week: e.target.value })}
            className={selectClass}
          >
            {weeks.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      <Field label="Grading">
        <div className="flex overflow-hidden rounded-md border border-[var(--border)]">
          {(["record", "performance"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setParam({ mode: m })}
              className={`px-3 py-1.5 text-sm capitalize transition-colors ${
                mode === m
                  ? "bg-neutral-800 text-white dark:bg-neutral-200 dark:text-neutral-900"
                  : "hover:bg-neutral-100 dark:hover:bg-neutral-800"
              }`}
              title={
                m === "record"
                  ? "Fixed thresholds from every season since 1999. Counting stats are prorated to games played, so mid-season this reads as on-pace."
                  : "Percentile within this season or week only."
              }
            >
              {m}
            </button>
          ))}
        </div>
      </Field>

      <div className="ml-auto flex items-center gap-2 text-xs">
        {mode === "record" ? (
          TIERS.map((t) => (
            <span
              key={t}
              className={`rounded px-1.5 py-0.5 ${TIER_STYLES[t]}`}
              title={TIER_LABELS[t]}
            >
              {TIER_LABELS[t]}
            </span>
          ))
        ) : (
          <span className="flex items-center gap-2 text-neutral-500">
            <span>0th</span>
            <span
              className="h-3 w-32 rounded"
              style={{
                background:
                  "linear-gradient(to right, hsl(0 72% 90%), hsl(65 72% 84%), hsl(130 72% 78%))",
              }}
            />
            <span>100th</span>
          </span>
        )}
      </div>

      {pending ? (
        <span className="text-xs text-neutral-400">loading…</span>
      ) : null}
    </div>
  );
}

const selectClass =
  "rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 text-sm";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="font-[family-name:var(--font-display)] text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        {label}
      </span>
      {children}
    </label>
  );
}
