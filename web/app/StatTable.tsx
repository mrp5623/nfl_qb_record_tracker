"use client";

import { useMemo, useState } from "react";
import {
  SENTINEL_STYLES,
  SENTINEL_TEXT,
  TIER_STYLES,
  type Stat,
  type Tier,
  formatValue,
  percentileStyle,
} from "@/lib/tiers";
import type { StatRow } from "@/lib/supabase";

type Props = {
  rows: StatRow[];
  stats: Stat[];
  mode: "record" | "performance";
  granularity: "season" | "week";
};

/**
 * The graded table.
 *
 * A client component purely so sorting is instant. A season is at most ~90 rows,
 * so the whole view is already in memory and a round trip to re-sort would be
 * slower and worse. The data itself is fetched on the server.
 */
export default function StatTable({ rows, stats, mode, granularity }: Props) {
  const [sortKey, setSortKey] = useState<string>("passing_yards");
  const [asc, setAsc] = useState(false);

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
    <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
      <table className="w-full border-collapse text-sm tabular-nums">
        <thead className="sticky top-0 z-10 bg-neutral-100 dark:bg-neutral-900">
          <tr>
            <Th
              onClick={() => toggleSort("player")}
              active={sortKey === "player"}
              asc={asc}
              className="sticky left-0 z-20 bg-neutral-100 text-left dark:bg-neutral-900"
            >
              Player
            </Th>
            <Th className="text-left">Tm</Th>
            {granularity === "season" ? (
              <>
                <Th onClick={() => toggleSort("games_played")} active={sortKey === "games_played"} asc={asc}>
                  G
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
                title={`${s.field} — ${s.direction.replace(/_/g, " ")}`}
              >
                {s.display}
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
                    tier={row.record_tiers?.[s.field] as Tier | undefined}
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
      className={`px-2 py-2 text-xs font-semibold uppercase tracking-wide text-neutral-600 dark:text-neutral-400 ${
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
  mode: "record" | "performance";
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
