import { useEffect, useState } from "react";
import { getJson } from "../http";

/** Season / playoff odds table (methodology §14–§15 of each sport). The backend
 *  describes its own columns, so one component serves every sport. */
type Column = { key: string; label: string; kind: "pct" | "num" | "text" | "series" };
type Row = Record<string, any> & { team: string; group: string };
export type OddsResponse = {
  sport: string; season: number; supported?: boolean; n_simulations?: number; games_left?: number;
  columns: Column[]; rows: Row[]; note: string; title_label?: string;
};

const fmtPct = (v: number) => (v >= 0.995 ? ">99%" : v > 0 && v < 0.005 ? "<1%" : `${Math.round(v * 100)}%`);

export function SeasonOdds({ sport, colorFor }: { sport: string; colorFor?: (team: string, row: Row) => string }) {
  const [data, setData] = useState<OddsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [group, setGroup] = useState<string>("All");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    getJson<OddsResponse>(`/${sport}/season/odds`).then(setData).catch((e) => setErr(String(e?.message ?? e)));
  }, [sport]);

  if (err) return <div className="error">Couldn't load season odds: {err}</div>;
  if (!data) return <div className="loading">Simulating the rest of the season…</div>;
  if (data.supported === false) return <div className="empty">{data.note}</div>;

  const groups = ["All", ...Array.from(new Set(data.rows.map((r) => r.group))).sort()];
  const rows = data.rows.filter((r) => group === "All" || r.group === group);
  const shown = showAll ? rows : rows.slice(0, 25);
  const pctCols = data.columns.filter((c) => c.kind === "pct");
  const heat = (v: number) => `color-mix(in srgb, var(--accent) ${Math.round(6 + v * 50)}%, transparent)`;

  return (
    <div className="odds">
      {groups.length > 2 && (
        <div className="odds-groups" role="tablist">
          {groups.map((g) => (
            <button key={g} className={`chip ${g === group ? "active" : ""}`} onClick={() => setGroup(g)}>{g}</button>
          ))}
        </div>
      )}
      <div className="odds-scroll">
        <table className="metrics odds-table">
          <thead>
            <tr>
              <th>Team</th>
              {data.columns.map((c) => <th key={c.key}>{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.team_id ?? r.team}>
                <td className="odds-team">
                  <span className="odds-dot" style={{ background: colorFor ? colorFor(r.team, r) : "#888" }} />
                  {r.team} <small>{r.group}</small>
                </td>
                {data.columns.map((c) => {
                  const v = r[c.key];
                  if (c.kind === "pct") return <td key={c.key} className="odds-pct" style={{ background: heat(v) }}>{fmtPct(v)}</td>;
                  if (c.kind === "series") return <td key={c.key}>{r.series_wins}–{r.series_losses}</td>;
                  return <td key={c.key}>{c.kind === "num" ? Number(v).toFixed(1) : v}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 25 && (
        <button className="chip" onClick={() => setShowAll(!showAll)}>{showAll ? "Show top 25" : `Show all ${rows.length}`}</button>
      )}
      <div className="disclaimer ok">
        {data.note} A projection from the frozen model, not a tested forecast: these odds have no calibration record.
        {data.games_left != null && ` ${data.games_left} games left to simulate.`}
        {pctCols.length > 0 && " Sorted by " + (data.title_label || "rating") + " odds."}
      </div>
    </div>
  );
}
