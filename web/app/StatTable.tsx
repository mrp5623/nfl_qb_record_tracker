"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  SENTINEL_STYLES,
  SENTINEL_TEXT,
  TIER_STYLES,
  type Mode,
  type Stat,
  type Tier,
  formatValue,
  percentileStyle,
} from "@/lib/tiers";
import type { StatRow } from "@/lib/supabase";

type Props = {
  rows: StatRow[];
  stats: Stat[];
  mode: Mode;
  granularity: "season" | "week";
  /**
   * Stats whose provider has not caught up with the box score yet, mapped to
   * the explanation shown on hover. Computed server-side from data_freshness.
   */
  pending?: Record<string, string>;
};

/**
 * The graded table.
 *
 * A client component purely so sorting is instant. A season is at most ~90 rows,
 * so the whole view is already in memory and a round trip to re-sort would be
 * slower and worse. The data itself is fetched on the server.
 */
export default function StatTable({ rows, stats, mode, granularity, pending = {} }: Props) {
  const [sortKey, setSortKey] = useState<string>("passing_yards");
  const [asc, setAsc] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // The header is `sticky top-0`, but sticky positions against the nearest
  // scroll container, and the horizontal scroll wrapper is one. Without a
  // height limit that wrapper never scrolls vertically, so the header just
  // scrolled away with the page. Capping the wrapper at the viewport space
  // below the controls makes it scroll in both directions: the header stays
  // put while rows scroll, and the controls and the horizontal scrollbar stay
  // on screen. The offset is measured because the controls wrap to more lines
  // on narrow screens.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      el.style.setProperty("--table-top", `${Math.round(top)}px`);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(document.body);
    return () => observer.disconnect();
  }, [rows.length]);

  const percentileKey =
    granularity === "season" ? "season_percentiles" : "week_percentiles";

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      if (sortKey === "player") {
        const an = a.player?.display_name ?? "";
        const bn = b.player?.display_name ?? "";
        return asc ? an.localeCompare(bn) : bn.localeCompare(an);
      }
      const av = a[sortKey];
      const bv = b[sortKey];
      // Nulls always sink, regardless of direction. A sentinel cell is an
      // absence, not a low score, and floating it to the top on an ascending
      // sort would bury the rows you actually asked to see.
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      const diff = Number(av) - Number(bv);
      return asc ? diff : -diff;
    });
    return copy;
  }, [rows, sortKey, asc]);

  function toggleSort(key: string) {
    if (key === sortKey) {
      setAsc(!asc);
    } else {
      setSortKey(key);
      setAsc(false);
    }
  }

  if (rows.length === 0) {
    return (
      <p className="py-16 text-center text-neutral-500">
        No rows for this selection.
      </p>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="overflow-auto overscroll-x-contain rounded-lg border border-neutral-200 dark:border-neutral-800"
      // A floor keeps phones, where the controls take most of the screen, from
      // shrinking the table to a few rows.
      style={{ maxHeight: "max(24rem, calc(100dvh - var(--table-top, 10rem) - 1rem))" }}
    >
      <table className="w-full border-collapse text-sm tabular-nums">
        {/* z-20 so the sticky Player cells in the body (z-10, later in the
            DOM) slide under the header rather than over it. */}
        <thead className="sticky top-0 z-20 bg-neutral-100 dark:bg-neutral-900">
          <tr>
            <Th
              onClick={() => toggleSort("player")}
              active={sortKey === "player"}
              asc={asc}
              className="sticky left-0 z-30 bg-neutral-100 text-left dark:bg-neutral-900"
            >
              Player
            </Th>
            <Th className="text-left">Tm</Th>
            {granularity === "season" ? (
              <>
                <Th onClick={() => toggleSort("games_played")} active={sortKey === "games_played"} asc={asc}>
                  G
                </Th>
                <Th
                  onClick={() => toggleSort("adjusted_games_played")}
                  active={sortKey === "adjusted_games_played"}
                  asc={asc}
                  title="Adjusted games played: games played × snap %. How many full games' worth of offensive snaps he was on the field for. Needs snap counts, which start in 2013."
                >
                  Adj G
                </Th>
                <Th className="text-left">Rec</Th>
              </>
            ) : (
              <>
                <Th className="text-left">Opp</Th>
                <Th className="text-left">Result</Th>
              </>
            )}
            {stats.map((s) => (
              <Th
                key={s.field}
                onClick={() => toggleSort(s.field)}
                active={sortKey === s.field}
                asc={asc}
                title={pending[s.field] ?? `${s.field} — ${s.direction.replace(/_/g, " ")}`}
              >
                {s.display}
                {pending[s.field] ? (
                  <span className="text-amber-600 dark:text-amber-400">*</span>
                ) : null}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const key = `${row.player_id}-${row.season}-${row.week ?? "s"}`;
            const percentiles =
              (row[percentileKey] as Record<string, number> | undefined) ?? {};
            return (
              <tr
                key={key}
                className="border-t border-neutral-200 dark:border-neutral-800"
              >
                <td
                  className={`sticky left-0 z-10 whitespace-nowrap bg-white px-3 py-1.5 font-medium dark:bg-neutral-950 ${
                    row.is_qualified ? "" : "text-neutral-400 dark:text-neutral-500"
                  }`}
                  title={row.is_qualified ? undefined : "Below the qualifying threshold (10 attempts per game)"}
                >
                  {row.player?.display_name ?? row.player_id}
                </td>
                <td className="px-2 py-1.5 text-neutral-500">{row.team_abbr}</td>
                {granularity === "season" ? (
                  <>
                    <td className="px-2 py-1.5 text-center text-neutral-500">
                      {row.games_played}
                    </td>
                    <td className="px-2 py-1.5 text-center text-neutral-500">
                      {row.adjusted_games_played == null ? (
                        <span className={SENTINEL_STYLES["Not Recorded"]} title="Not Recorded">
                          {SENTINEL_TEXT["Not Recorded"]}
                        </span>
                      ) : (
                        Number(row.adjusted_games_played).toFixed(1)
                      )}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-neutral-500">
                      {row.wins}-{row.losses}
                      {row.ties ? `-${row.ties}` : ""}
                    </td>
                  </>
                ) : (
                  <>
                    <td className="px-2 py-1.5 text-neutral-500">
                      {row.opponent_abbr}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-neutral-500">
                      {row.result}
                    </td>
                  </>
                )}
                {stats.map((s) => (
                  <Cell
                    key={s.field}
                    stat={s}
                    value={row[s.field]}
                    sentinel={row.sentinels?.[s.field]}
                    tier={
                      (mode === "adjusted" ? row.adjusted_record_tiers : row.record_tiers)?.[
                        s.field
                      ] as Tier | undefined
                    }
                    percentile={percentiles[s.field]}
                    mode={mode}
                  />
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  onClick,
  active,
  asc,
  className = "",
  title,
}: {
  children?: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  asc?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <th
      onClick={onClick}
      title={title}
      // The divider is an inset shadow rather than a border: collapsed table
      // borders belong to the table, not the cell, and stay behind when the
      // header sticks.
      className={`px-2 py-2 text-xs font-semibold uppercase tracking-wide text-neutral-600 shadow-[inset_0_-1px_0_var(--border)] dark:text-neutral-400 ${
        onClick ? "cursor-pointer select-none hover:text-neutral-900 dark:hover:text-neutral-100" : ""
      } ${active ? "text-neutral-900 underline decoration-2 underline-offset-4 dark:text-neutral-100" : ""} ${className}`}
    >
      {children}
      {active ? <span className="ml-0.5">{asc ? "▲" : "▼"}</span> : null}
    </th>
  );
}

function Cell({
  stat,
  value,
  sentinel,
  tier,
  percentile,
  mode,
}: {
  stat: Stat;
  value: unknown;
  sentinel?: string;
  tier?: Tier;
  percentile?: number;
  mode: Mode;
}) {
  // A sentinel wins over both modes. The cell has no number to grade, and the
  // reason it is empty is more informative than any colour would be (8.1).
  if (sentinel) {
    return (
      <td
        className={`px-2 py-1.5 text-center ${SENTINEL_STYLES[sentinel] ?? ""}`}
        title={sentinel}
      >
        {SENTINEL_TEXT[sentinel] ?? "—"}
      </td>
    );
  }

  const text = formatValue(value, stat.kind);
  if (text === "") return <td className="px-2 py-1.5" />;

  if (mode === "performance") {
    if (percentile === undefined) {
      return <td className="px-2 py-1.5 text-center">{text}</td>;
    }
    return (
      <td
        className="pct-cell px-2 py-1.5 text-center"
        style={percentileStyle(percentile)}
        title={`${Math.round(percentile * 100)}th percentile this ${
          stat.field ? "period" : ""
        }`}
      >
        {text}
      </td>
    );
  }

  return (
    <td
      className={`px-2 py-1.5 text-center ${tier ? TIER_STYLES[tier] : ""}`}
      title={tier}
    >
      {text}
    </td>
  );
}
