import { useEffect, useState } from "react";
import { fetchScorers, type ScorersResponse } from "../api";

/** "Likeliest scorers tonight" — top P(goal) across today's NHL slate
 *  (methodology/NHL_PLAYERS.md §7). Hidden when the model is unavailable. */
export function TopScorers({ colorFor }: { colorFor: (code: string) => string }) {
  const [data, setData] = useState<ScorersResponse | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const load = () =>
      fetchScorers()
        .then((d) => {
          if (!alive) return;
          setData(d);
          if (d.available && !d.ready) timer = window.setTimeout(load, 15000); // state still building
        })
        .catch(() => alive && setData(null));
    load();
    return () => { alive = false; if (timer) window.clearTimeout(timer); };
  }, []);

  if (!data || !data.available) return null;
  return (
    <section className="panel">
      <div className="panel-title"><h2>Likeliest scorers tonight</h2><span className="meta">chance of at least one goal</span></div>
      {!data.ready && <div className="loading">Warming up the skater model…</div>}
      {data.ready && data.players.length === 0 && <div className="empty">No NHL games today.</div>}
      {data.ready && data.players.length > 0 && (
        <ol className="scorer-list">
          {data.players.map((p) => (
            <li key={p.player_id} className="scorer-row">
              <span className="scorer-name">
                {p.name} <small style={{ color: colorFor(p.team) }}>{p.team}</small>
                <small> {p.is_home ? "vs" : "@"} {p.opponent}</small>
              </span>
              <span className="proj-cell"><i style={{ width: `${Math.max(2, Math.round(p.p_goal * 36))}px`, background: colorFor(p.team) }} />{Math.round(p.p_goal * 100)}%</span>
              <span className="scorer-pt">{Math.round(p.p_point * 100)}% pt</span>
            </li>
          ))}
        </ol>
      )}
      <div className="disclaimer ok">
        From the pre-registered skater model, which passed its one-time test on 2023-24 → 2025-26.{" "}
        {data.note}
      </div>
    </section>
  );
}
