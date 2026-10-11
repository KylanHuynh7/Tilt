import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getJson } from "../http";
import { navigate } from "../router";
import type { DetailSide, FormGame, GameDetailResponse, RosterPlayer } from "../types";
import { PlayerAvatar, PlayerCard } from "./PlayerCard";

type Props = {
  sport: string;
  gameId: string;
  colorFor: (code: string) => string;   // fallback when the payload has no color (NHL)
  periodLabel: (p: number) => string;
};

const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;
const signed = (x: number, d = 0) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;

function FormStrip({ form }: { form: FormGame[] }) {
  if (!form.length) return <div className="empty">No recent games.</div>;
  return (
    <div className="form-strip">
      {form.map((g, i) => (
        <span
          key={i}
          className={`form-chip ${g.result}`}
          title={`${g.date} ${g.at_home ? "vs" : "@"} ${g.opponent} ${g.for}–${g.against}`}
        >
          {g.result}
        </span>
      ))}
    </div>
  );
}

function RosterList({ side, color, onPick }: { side: DetailSide; color: string; onPick: (p: RosterPlayer) => void }) {
  if (!side.roster.loaded) return <div className="empty">Roster unavailable right now.</div>;
  const r = side.roster;
  const gtd = r.available.flatMap((g) => g.players).filter((p) => p.status).length;
  const nAvail = r.available.reduce((n, g) => n + g.players.length, 0);
  return (
    <div className="roster" style={{ "--team": color } as React.CSSProperties}>
      <div className="roster-head">
        <span className="roster-team">{side.code}</span>
        <span className="meta">
          {nAvail} available{gtd ? ` · ${gtd} game-time decision${gtd > 1 ? "s" : ""}` : ""}
        </span>
      </div>

      <div className="roster-section-title">Available</div>
      {r.available.map((g) => (
        <div key={g.group} className="roster-group">
          {r.available.length > 1 && <div className="roster-group-name">{prettyGroup(g.group)}</div>}
          <ul>
            {g.players.map((p: RosterPlayer, i) => (
              <li key={i} className={p.status ? "flagged" : ""}>
                <PlayerAvatar p={p} color={color} />
                <PlayerName p={p} onPick={onPick} />
                <span className="pos">{p.position}</span>
                {p.status && <span className="status-chip">{p.status}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}

      <div className="roster-section-title out">Ruled out {r.ruled_out.length ? `(${r.ruled_out.length})` : ""}</div>
      {r.ruled_out.length ? (
        <ul className="ruled-out">
          {r.ruled_out.map((p, i) => (
            <li key={i}>
              <PlayerAvatar p={p} color={color} />
              <PlayerName p={p} onPick={onPick} />
              <span className="pos">{p.position}</span>
              <span className="out-chip">{p.reason}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty">Nobody ruled out.</div>
      )}
    </div>
  );
}

function PlayerName({ p, onPick }: { p: RosterPlayer; onPick: (p: RosterPlayer) => void }) {
  if (!p.id) return <span className="pname">{p.name}</span>;
  return (
    <button className="pname pname-btn" onClick={() => onPick(p)} title={`${p.name}: season & career stats`}>
      {p.name}
    </button>
  );
}

function prettyGroup(g: string): string {
  const map: Record<string, string> = {
    offense: "Offense", defense: "Defense", specialTeam: "Special teams",
    injuredReserveOrOut: "Injured reserve / out", suspended: "Suspended", practiceSquad: "Practice squad",
  };
  return map[g] ?? g;
}

export function GameDetail({ sport, gameId, colorFor, periodLabel }: Props) {
  const [d, setD] = useState<GameDetailResponse | null>(null);
  const [picked, setPicked] = useState<{ p: RosterPlayer; team: string; color: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = false;
    const load = () =>
      getJson<GameDetailResponse>(`/${sport}/games/${gameId}/detail`)
        .then((r) => {
          setD(r);
          live = r.game.state === "LIVE" || !!r.game.live_state;
        })
        .catch((e: Error) => setErr(e.message));
    load();
    const id = setInterval(() => live && load(), 60_000);
    return () => clearInterval(id);
  }, [sport, gameId]);

  const trendRows = useMemo(() => {
    if (!d) return [];
    const byDate = new Map<string, { date: string; home?: number; away?: number }>();
    for (const [key, side] of [["home", d.home], ["away", d.away]] as const) {
      for (const p of side.trend.points) {
        const row = byDate.get(p.date) ?? { date: p.date };
        row[key] = p.rating;
        byDate.set(p.date, row);
      }
    }
    const rows = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
    let h: number | undefined, a: number | undefined;
    return rows.map((r) => {
      h = r.home ?? h;
      a = r.away ?? a;
      return { date: r.date, home: h, away: a };
    });
  }, [d]);

  const back = (
    <button className="back-btn" onClick={() => navigate(`/${sport}`)}>
      ← All games
    </button>
  );

  if (err) return <>{back}<div className="error">Couldn't load this game: {err}</div></>;
  if (!d) return <>{back}<div className="loading">Loading game analysis…</div></>;

  const g = d.game;
  const homeColor = d.home.color ?? colorFor(d.home.code);
  const awayColor = d.away.color ?? colorFor(d.away.code);
  const vars = { "--home": homeColor, "--away": awayColor } as React.CSSProperties;
  const p = d.probability;
  const liveP = g.live_wp?.home_win_prob;
  const shownHome = liveP ?? p.home_win_prob;
  const fav = shownHome >= 0.5 ? d.home : d.away;
  const favP = Math.max(shownHome, 1 - shownHome);
  const gapProb = p.p_home_without_home_edge - 0.5;
  const state = g.live_state ? `${periodLabel(g.live_state.period)} · ${Math.floor(g.live_state.time_remaining_s / 60)}:${String(g.live_state.time_remaining_s % 60).padStart(2, "0")}` : g.state === "FINAL" || g.state === "OFF" ? "Final" : "Pre-game";
  const score = g.live_state ? [g.live_state.away_score, g.live_state.home_score] : g.home_score != null && g.state !== "PRE" && g.state !== "FUT" ? [g.away_score, g.home_score] : null;
  const cc = d.calibration_context;

  return (
    <div className="detail" style={vars}>
      {back}

      {/* Matchup hero */}
      <section className="detail-hero">
        <div className="hero-team away">
          <span className="hero-badge" style={{ background: awayColor }}>{d.away.code}</span>
          <div>
            <div className="hero-code">{d.away.code}</div>
            <div className="hero-name">{d.away.name}</div>
            <div className="hero-rating">Elo {g.away_rating.toFixed(0)}</div>
          </div>
        </div>
        <div className="hero-mid">
          <span className={`hero-state ${g.live_state ? "live" : ""}`}>{state}</span>
          {score ? (
            <div className="hero-score">{score[0]}<span>—</span>{score[1]}</div>
          ) : (
            <div className="hero-at">@</div>
          )}
          {p.neutral && <span className="hero-neutral">Neutral site</span>}
        </div>
        <div className="hero-team home">
          <div>
            <div className="hero-code">{d.home.code}</div>
            <div className="hero-name">{d.home.name}</div>
            <div className="hero-rating">Elo {g.home_rating.toFixed(0)}</div>
          </div>
          <span className="hero-badge" style={{ background: homeColor }}>{d.home.code}</span>
        </div>
      </section>

      {/* Probability */}
      <section className="panel prob-panel">
        <div className="prob-headline">
          <span className="prob-big">{pct(favP, 0)}</span>
          <span className="prob-text">
            {fav.code} to win{liveP != null ? " — live" : ""}
            <small>{liveP != null ? `pre-game was ${pct(p.home_win_prob)} ${d.home.code}` : d.model.name}</small>
          </span>
        </div>
        <div className="big-bar">
          <div className="away" style={{ width: pct(1 - shownHome) }}><span>{pct(1 - shownHome)}</span></div>
          <div className="home" style={{ width: pct(shownHome) }}><span>{pct(shownHome)}</span></div>
        </div>
        <div className="why-grid">
          <div className="why-card">
            <div className="why-label">Rating gap</div>
            <div className="why-value">{signed(Math.abs(p.rating_gap))} Elo</div>
            <div className="why-note">
              {p.rating_gap === 0 ? "Evenly rated." : `${p.rating_gap > 0 ? d.home.code : d.away.code} is rated higher — worth ${pct(Math.abs(gapProb))} on its own.`}
            </div>
          </div>
          <div className="why-card">
            <div className="why-label">Home edge</div>
            <div className="why-value">{p.neutral ? "None" : `${signed(p.home_edge_elo)} Elo`}</div>
            <div className="why-note">
              {p.neutral ? "Neutral site: no home bump applied." : `Adds ${pct(p.home_edge_prob_points)} for ${d.home.code}.`}
            </div>
          </div>
          <div className="why-card">
            <div className="why-label">Track record</div>
            <div className="why-value">{cc ? pct(cc.home_win_rate, 0) : "—"}</div>
            <div className="why-note">
              {cc
                ? `When the model gave home teams ${pct(cc.lo, 0)}–${pct(cc.hi, 0)} in its held-out test, they won ${pct(cc.home_win_rate, 0)} of ${cc.n} games.`
                : "Too few comparable test games to say."}
            </div>
          </div>
        </div>
        <div className="meta">
          Model: {d.model.name} · home bump {d.model.home_bump} · K {d.model.k_regular}
          {d.model.mov ? " · margin-of-victory on" : ""} · live: {d.model.live}
          {cc ? ` · track record from ${cc.source}` : ""}
        </div>
      </section>

      {/* Live WP chart */}
      {d.live_history.length >= 2 && (
        <section className="panel">
          <div className="panel-title"><h2>Live win probability</h2><span className="meta">{d.home.code} perspective · since the server started watching</span></div>
          <div className="detail-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={d.live_history.map((h, i) => ({ i, wp: h.home_wp, label: `${periodLabel(h.period)} ${Math.floor(h.time_remaining_s / 60)}:${String(h.time_remaining_s % 60).padStart(2, "0")} · ${h.away_score}–${h.home_score}` }))}>
                <defs>
                  <linearGradient id="wpfill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={homeColor} stopOpacity={0.55} />
                    <stop offset="100%" stopColor={awayColor} stopOpacity={0.35} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
                <XAxis dataKey="label" hide />
                <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} stroke="var(--text-dim)" fontSize={11} width={44} />
                <ReferenceLine y={0.5} stroke="var(--text-faint)" strokeDasharray="2 4" />
                <Tooltip formatter={(v: number) => [pct(v), `${d.home.code} win`]} labelFormatter={(l) => l} contentStyle={{ background: "var(--panel)", border: "1px solid var(--edge-strong)", borderRadius: 10 }} />
                <Area type="stepAfter" dataKey="wp" stroke={homeColor} strokeWidth={2} fill="url(#wpfill)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      <div className="detail-grid">
        {/* Season trend */}
        <section className="panel">
          <div className="panel-title"><h2>Rating trend</h2><span className="meta">{d.home.trend.season} season</span></div>
          {trendRows.length >= 2 ? (
            <div className="detail-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendRows}>
                  <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
                  <XAxis dataKey="date" stroke="var(--text-dim)" fontSize={10} minTickGap={40} />
                  <YAxis domain={["auto", "auto"]} stroke="var(--text-dim)" fontSize={11} width={44} />
                  <ReferenceLine y={1500} stroke="var(--text-faint)" strokeDasharray="2 4" />
                  <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--edge-strong)", borderRadius: 10 }} />
                  <Line dataKey="away" name={d.away.code} stroke={awayColor} strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls />
                  <Line dataKey="home" name={d.home.code} stroke={homeColor} strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="empty">No games yet this season.</div>
          )}
        </section>

        {/* Form + head to head */}
        <section className="panel">
          <div className="panel-title"><h2>Recent form</h2><span className="meta">last 10, newest first</span></div>
          <div className="form-row"><span className="form-team" style={{ color: awayColor }}>{d.away.code}</span><FormStrip form={d.away.form} /></div>
          <div className="form-row"><span className="form-team" style={{ color: homeColor }}>{d.home.code}</span><FormStrip form={d.home.form} /></div>
          <h3 className="cal-h h2h-title">Head to head</h3>
          {d.head_to_head.length ? (
            <ul className="h2h">
              {d.head_to_head.map((m, i) => (
                <li key={i}>
                  <span className="meta">{m.date}</span>
                  <span>{m.away} <b>{m.away_score}</b> — <b>{m.home_score}</b> {m.home}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty">No recent meetings.</div>
          )}
        </section>
      </div>

      {/* Rosters */}
      <section className="panel">
        <div className="panel-title"><h2>Players &amp; availability</h2><span className="meta">rosters + injury report from ESPN</span></div>
        <div className="roster-grid">
          <RosterList side={d.away} color={awayColor} onPick={(p) => setPicked({ p, team: d.away.code, color: awayColor })} />
          <RosterList side={d.home} color={homeColor} onPick={(p) => setPicked({ p, team: d.home.code, color: homeColor })} />
        </div>
        <div className="disclaimer ok">
          Starting lineups aren't published before the game, so this lists everyone available
          rather than starters vs bench. Tilt's models are team-level: they don't see who plays
          and don't project player stats — that would be a separate, pre-registered model.
          Click a player for season and career stats. Photos and stats: ESPN.
        </div>
      </section>

      {picked && (
        <PlayerCard sport={sport} player={picked.p} team={picked.team} color={picked.color} onClose={() => setPicked(null)} />
      )}
    </div>
  );
}
