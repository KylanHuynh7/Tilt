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
import type { RatingsHistoryResponse } from "../types";

type Props = {
  data: RatingsHistoryResponse;
  // Fallback color lookup by team code; a per-team `color` in the payload wins.
  colorFor: (code: string) => string;
};

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

type TeamLine = { id: string; code: string | null; color: string };

// Custom tooltip renderer that flags the cup winner with a 👑 next to their
// abbreviation. The hover layer carries no team lines, so values are read
// from the hovered row rather than from the tooltip payload.
function makeTooltipContent(
  cupWinnerFranchise: string | null,
  teams: TeamLine[],
  rowByDate: Map<string, Record<string, number | string>>,
) {
  return ({ active, label }: any) => {
    const row = active ? rowByDate.get(label) : undefined;
    if (!row) return null;
    const sorted = teams
      .filter((t) => typeof row[t.id] === "number")
      .sort((a, b) => (row[b.id] as number) - (row[a.id] as number));
    return (
      <div className="chart-tooltip">
        <div className="chart-tooltip-label">{label}</div>
        {sorted.map((t) => (
          <div key={t.id} className="chart-tooltip-row">
            <span className="chart-tooltip-name" style={{ color: t.color }}>
              {t.code ?? t.id}
              {t.id === cupWinnerFranchise && <span className="chart-tooltip-crown"> 👑</span>}
            </span>
            <span className="chart-tooltip-value">{(row[t.id] as number).toFixed(2)}</span>
          </div>
        ))}
      </div>
    );
  };
}

const MARGIN = { top: 8, right: 64, bottom: 8, left: 0 };

export function TrajectoryChart({ data, colorFor }: Props) {
  const { rows, rowByDate, teams, yDomain } = useMemo(() => {
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
      rowByDate: new Map(rows.map((r) => [r.date as string, r])),
      teams: data.teams.map((t) => ({
        id: t.franchise_id,
        code: t.team,
        color: t.color ?? (t.team ? colorFor(t.team) : "#888"),
      })),
      yDomain: [lo, hi] as [number, number],
    };
  }, [data, colorFor]);

  const tooltip = useMemo(
    () => makeTooltipContent(data.cup_winner_franchise, teams, rowByDate),
    [data.cup_winner_franchise, teams, rowByDate],
  );

  // Hovering re-renders a chart and everything in it. The 30-odd team lines
  // sit in a static chart that ignores the pointer; a matching transparent
  // chart on top owns the cursor and tooltip, so a hover redraws only that.
  return (
    <div className="chart-wrap chart-stack">
      <div className="chart-layer" style={{ pointerEvents: "none" }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={MARGIN}>
            <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
            <XAxis dataKey="date" stroke="var(--text-dim)" fontSize={11} minTickGap={32} />
            <YAxis
              domain={yDomain}
              stroke="var(--text-dim)"
              fontSize={11}
              width={48}
            />
            <ReferenceLine y={1500} stroke="var(--text-faint)" strokeDasharray="2 4" />
            {teams.map((team) => {
              const isChampion = data.cup_winner_franchise === team.id;
              return (
                <Line
                  key={team.id}
                  type="monotone"
                  dataKey={team.id}
                  name={team.code ?? team.id}
                  stroke={team.color}
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
                        team.color,
                      )}
                    />
                  )}
                </Line>
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-layer">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={MARGIN}>
            <XAxis dataKey="date" tick={false} axisLine={false} tickLine={false} />
            <YAxis domain={yDomain} width={48} tick={false} axisLine={false} tickLine={false} />
            <Tooltip content={tooltip} wrapperStyle={{ outline: "none" }} />
            {/* One invisible line so the tooltip has a payload to activate on. */}
            <Line dataKey={() => yDomain[0]} stroke="none" dot={false} activeDot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
