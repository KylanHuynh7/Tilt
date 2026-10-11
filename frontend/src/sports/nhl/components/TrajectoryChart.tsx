import { useMemo } from "react";
import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RatingsHistoryResponse } from "../api";
import { colorFor } from "../teamColors";

type Props = { data: RatingsHistoryResponse };

// Renders "{TEAM} 👑" at the last data point of the cup-winner's line.
// Recharts' LabelList iterates every (index, value); we return null for
// every point except the final one, using a closure over `lastIndex`.
function makeCrownContent(lastIndex: number, teamCode: string, teamColor: string) {
  return (props: any) => {
    if (props?.index !== lastIndex) return null;
    if (props?.value == null) return null;
    const x = Number(props.x);
    const y = Number(props.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return (
      <g style={{ pointerEvents: "none" }}>
        <text
          x={x + 8}
          y={y + 4}
          fontSize={12}
          fontWeight={700}
          fill={teamColor}
          style={{ filter: "drop-shadow(0 1px 1px rgba(255,255,255,0.6))" }}
        >
          {teamCode}{" "}
          <tspan fontSize={14}>👑</tspan>
        </text>
      </g>
    );
  };
}

// Custom tooltip renderer that flags the cup winner with a 👑 next to their
// abbreviation. Falls back to default styling otherwise.
function makeTooltipContent(cupWinnerFranchise: string | null) {
  return ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    const sorted = [...payload].sort(
      (a: any, b: any) => (b.value ?? 0) - (a.value ?? 0),
    );
    return (
      <div className="chart-tooltip">
        <div className="chart-tooltip-label">{label}</div>
        {sorted.map((row: any) => {
          const isChamp = row.dataKey === cupWinnerFranchise;
          return (
            <div key={row.dataKey} className="chart-tooltip-row">
              <span className="chart-tooltip-name" style={{ color: row.color }}>
                {row.name}
                {isChamp && <span className="chart-tooltip-crown"> 👑</span>}
              </span>
              <span className="chart-tooltip-value">{row.value?.toFixed?.(2)}</span>
            </div>
          );
        })}
      </div>
    );
  };
}

export function TrajectoryChart({ data }: Props) {
  const { rows, teams, yDomain } = useMemo(() => {
    const byDate = new Map<string, Record<string, number | null>>();
    let minR = Infinity;
    let maxR = -Infinity;
    for (const t of data.teams) {
      for (const p of t.points) {
        const row = byDate.get(p.date) ?? {};
        row[t.franchise_id] = p.rating;
        byDate.set(p.date, row);
        if (p.rating < minR) minR = p.rating;
        if (p.rating > maxR) maxR = p.rating;
      }
    }
    const sortedDates = [...byDate.keys()].sort();
    const lastSeen: Record<string, number> = {};
    const rows = sortedDates.map((date) => {
      const observed = byDate.get(date)!;
      for (const team of data.teams) {
        if (observed[team.franchise_id] != null) {
          lastSeen[team.franchise_id] = observed[team.franchise_id]!;
        }
      }
      const row: Record<string, number | string> = { date };
      for (const team of data.teams) {
        if (lastSeen[team.franchise_id] != null) {
          row[team.franchise_id] = lastSeen[team.franchise_id];
        }
      }
      return row;
    });
    // Round y-axis bounds to nearest 25 with 25-point padding so the chart
    // breathes and the 1500 reference line is always inside the frame.
    const lo = Math.min(1475, Math.floor((minR - 25) / 25) * 25);
    const hi = Math.max(1525, Math.ceil((maxR + 25) / 25) * 25);
    return {
      rows,
      teams: data.teams.map((t) => ({ id: t.franchise_id, code: t.team })),
      yDomain: [lo, hi] as [number, number],
    };
  }, [data]);

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
          <XAxis dataKey="date" stroke="var(--text-dim)" fontSize={11} minTickGap={32} />
          <YAxis
            domain={yDomain}
            stroke="var(--text-dim)"
            fontSize={11}
            width={48}
          />
          <ReferenceLine y={1500} stroke="var(--text-faint)" strokeDasharray="2 4" />
          <Tooltip
            content={makeTooltipContent(data.cup_winner_franchise)}
            wrapperStyle={{ outline: "none" }}
          />
          {teams.map((team) => {
            const isChampion = data.cup_winner_franchise === team.id;
            return (
              <Line
                key={team.id}
                type="monotone"
                dataKey={team.id}
                name={team.code ?? team.id}
                stroke={team.code ? colorFor(team.code) : "#888"}
                strokeOpacity={isChampion ? 1.0 : 0.75}
                strokeWidth={isChampion ? 2.25 : 1.5}
                dot={false}
                isAnimationActive={false}
              >
                {isChampion && (
                  <LabelList
                    dataKey={team.id}
                    content={makeCrownContent(
                      rows.length - 1,
                      team.code ?? "?",
                      team.code ? colorFor(team.code) : "#333",
                    )}
                  />
                )}
              </Line>
            );
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
