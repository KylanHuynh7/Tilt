import { useEffect, useRef, useState } from "react";
import { getJson } from "../http";
import type { PlayerStatsResponse, RosterPlayer } from "../types";

// Headshot with an initials fallback (missing photo, blocked CDN, …).
export function PlayerAvatar({ p, color, size = 30 }: { p: RosterPlayer; color: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const initials = p.name.split(" ").map((w) => w[0]).filter(Boolean).slice(0, 2).join("");
  const style = { width: size, height: size, "--team": color } as React.CSSProperties;
  if (p.headshot && !broken) {
    return <img className="avatar" style={style} src={p.headshot} alt="" loading="lazy" onError={() => setBroken(true)} />;
  }
  return <span className="avatar initials" style={style} aria-hidden="true">{initials}</span>;
}

type Props = { sport: string; player: RosterPlayer; team: string; color: string; onClose: () => void };

export function PlayerCard({ sport, player, team, color, onClose }: Props) {
  const [data, setData] = useState<PlayerStatsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cat, setCat] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    getJson<PlayerStatsResponse>(`/${sport}/players/${player.id}`).then(setData).catch((e: Error) => setErr(e.message));
  }, [sport, player.id]);

  // Latest onClose via a ref, so parent re-renders (live polling) don't
  // re-run this effect and steal focus.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, []);

  const c = data?.categories[cat];
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="player-card"
        role="dialog"
        aria-modal="true"
        aria-label={`${player.name} stats`}
        style={{ "--team": color } as React.CSSProperties}
        onClick={(e) => e.stopPropagation()}
      >
        <button ref={closeRef} className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        <header className="pc-head">
          <PlayerAvatar p={player} color={color} size={88} />
          <div>
            <div className="pc-name">{player.name}</div>
            <div className="pc-meta">
              {team} · {player.position ?? "—"}{player.jersey ? ` · #${player.jersey}` : ""}
            </div>
            {player.status && <span className="status-chip">{player.status}</span>}
          </div>
        </header>

        {err && <div className="error">Couldn't load stats: {err}</div>}
        {!data && !err && <div className="loading">Loading career stats…</div>}
        {data && !data.categories.length && <div className="empty">No stats on record yet.</div>}

        {data && data.categories.length > 0 && c && (
          <>
            {data.categories.length > 1 && (
              <div className="pc-tabs" role="tablist">
                {data.categories.map((x, i) => (
                  <button key={x.name + i} role="tab" aria-selected={i === cat}
                    className={`pc-tab ${i === cat ? "active" : ""}`} onClick={() => setCat(i)}>
                    {x.display_name}
                  </button>
                ))}
              </div>
            )}
            <div className="pc-table-wrap">
              <table className="metrics pc-table">
                <thead>
                  <tr>
                    <th>Season</th>
                    <th>Team</th>
                    {c.labels.map((l, i) => (
                      <th key={i} className="num" title={c.descriptions[i] ?? l}>{l}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {c.seasons.map((s, i) => (
                    <tr key={i} className={i === 0 ? "current" : ""}>
                      <td>{s.season}{i === 0 && <span className="pc-now">latest</span>}</td>
                      <td className="dim">{s.team ?? ""}</td>
                      {s.stats.map((v, j) => <td key={j} className="num">{v}</td>)}
                    </tr>
                  ))}
                  {c.career.length > 0 && (
                    <tr className="career">
                      <td>Career</td>
                      <td></td>
                      {c.career.map((v, j) => <td key={j} className="num">{v}</td>)}
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
        <div className="pc-foot">Stats and photo: ESPN. Facts only, not a Tilt projection.</div>
      </div>
    </div>
  );
}
