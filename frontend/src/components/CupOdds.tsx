import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CupResponse } from "../api";
import { colorFor } from "../teamColors";

type Props = { data: CupResponse };

export function CupOdds({ data }: Props) {
  const rows = useMemo(() => {
    // Sort desc by Cup probability, then alphabetical for ties (all-0 tail).
    return [...data.teams]
      .sort((a, b) => b.cup_probability - a.cup_probability || a.team.localeCompare(b.team))
      .map((t) => ({
        team: t.team,
        cup_pct: t.cup_probability * 100,
        status: t.status,
        rating: t.rating,
      }));
  }, [data]);

  return (
    <div className="cup-odds">
      <div className="cup-odds-head">
        <span className="cup-odds-title">2025-26 Stanley Cup probability</span>
        <span className="cup-odds-meta">
          {data.n_simulations.toLocaleString()} simulations · run {new Date(data.simulated_at).toLocaleTimeString()}
        </span>
      </div>
      <div className="cup-odds-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 32, left: 8 }}>
            <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="team"
              interval={0}
              angle={-45}
              textAnchor="end"
              height={48}
              tick={{ fontSize: 10, fill: "var(--text-dim)" }}
            />
            <YAxis
              stroke="var(--text-dim)"
              fontSize={11}
              width={42}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            />
            <Tooltip
              cursor={{ fill: "var(--grid)", opacity: 0.4 }}
              contentStyle={{
                background: "var(--panel)",
                border: "1px solid var(--panel-edge)",
                borderRadius: 6,
                fontSize: 12,
              }}
              formatter={(value: number) => [`${value.toFixed(2)}%`, "Cup probability"]}
              labelFormatter={(label: string) => `${label}`}
            />
            <Bar dataKey="cup_pct" radius={[2, 2, 0, 0]}>
              {rows.map((r) => (
                <Cell
                  key={r.team}
                  fill={colorFor(r.team)}
                  fillOpacity={r.cup_pct > 0 ? 1 : 0.18}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="cup-odds-foot">
        Teams not in the playoff field are shown at 0% with reduced opacity.
        {data.in_progress_series.length > 0 && (
          <> Series in progress: {data.in_progress_series.join(", ")}.</>
        )}
      </div>
    </div>
  );
}
