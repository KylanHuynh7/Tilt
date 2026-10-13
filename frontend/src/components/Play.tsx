import { useEffect, useMemo, useState } from "react";
import { getJson } from "../http";

/** Play page: beat the model (picks saved in this browser), matchup machine, rewatch.
 *  Backend: app/play.py. Nothing here is a new model or a tested forecast. */

type SlateGame = { sport: string; game_id: string; date: string | null; state: string; home: string; away: string;
  home_color?: string | null; away_color?: string | null; home_win_prob: number; home_score?: number | null;
  away_score?: number | null; watch_score?: number | null; watch_strong?: boolean };
type Slate = { games: SlateGame[]; watch_day: string | null; watch_tonight: SlateGame | null; watch_by_sport: Record<string, SlateGame> };
type Pick = { sport: string; game_id: string; date: string | null; home: string; away: string; pick: "home" | "away";
  p_home: number; result?: { home_won: boolean | null } };
type Team = { code: string; name: string; color: string | null };
type Rewatch = { date: string | null; note: string; games: (SlateGame & { winner: string; loser: string; p_winner: number;
  swing: number; lead_changes: number; winner_low: number; spark: number[]; top_swing?: { text: string; label: string } | null })[] };

const NAMES: Record<string, string> = { nhl: "NHL", nba: "NBA", nfl: "NFL", mlb: "MLB", cfb: "CFB" };
const pct = (v: number) => `${Math.round(v * 100)}%`;
const KEY = "tilt-picks-v1";

function loadPicks(): Record<string, Pick> {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
}
function savePicks(p: Record<string, Pick>) {
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* private mode: picks last for this visit only */ }
}

// ---- Beat the model -----------------------------------------------------------------------

function BeatTheModel() {
  const [slate, setSlate] = useState<Slate | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [picks, setPicks] = useState<Record<string, Pick>>(loadPicks);

  useEffect(() => { getJson<Slate>("/play/slate").then(setSlate).catch((e) => setErr(String(e?.message ?? e))); }, []);

  // Grade picks whose games have finished (results come from the live league APIs).
  useEffect(() => {
    const open = Object.entries(picks).filter(([, p]) => !p.result).map(([k]) => k);
    if (!open.length) return;
    getJson<Record<string, { home_won: boolean | null }>>(`/play/results?games=${encodeURIComponent(open.slice(0, 60).join(","))}`)
      .then((res) => {
        if (!Object.keys(res).length) return;
        setPicks((cur) => {
          const next = { ...cur };
          for (const [k, r] of Object.entries(res)) if (next[k]) next[k] = { ...next[k], result: { home_won: r.home_won } };
          savePicks(next);
          return next;
        });
      }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slate]);

  const choose = (g: SlateGame, side: "home" | "away") => {
    const k = `${g.sport}:${g.game_id}`;
    if (picks[k]) return;                      // picks lock once made (no peeking at the model first)
    setPicks((cur) => {
      const next = { ...cur, [k]: { sport: g.sport, game_id: g.game_id, date: g.date, home: g.home, away: g.away, pick: side, p_home: g.home_win_prob } };
      savePicks(next);
      return next;
    });
  };

  const graded = Object.values(picks).filter((p) => p.result && p.result.home_won !== null);
  const you = graded.filter((p) => (p.pick === "home") === p.result!.home_won).length;
  const model = graded.filter((p) => (p.p_home >= 0.5) === p.result!.home_won).length;
  const disagree = graded.filter((p) => (p.pick === "home") !== (p.p_home >= 0.5));
  const youDis = disagree.filter((p) => (p.pick === "home") === p.result!.home_won).length;
  const streak = useMemo(() => {
    const seq = [...graded].sort((a, b) => String(b.date).localeCompare(String(a.date)));
    let n = 0;
    for (const p of seq) { if ((p.pick === "home") === p.result!.home_won) n++; else break; }
    return n;
  }, [graded]);
  const pending = Object.values(picks).filter((p) => !p.result).length;

  if (err) return <div className="error">Couldn't load today's games: {err}</div>;
  if (!slate) return <div className="loading">Loading today's games…</div>;
  const open = slate.games.filter((g) => g.state === "PRE").sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const w = slate.watch_tonight;

  return (
    <>
      {w && (
        <section className="panel play-watch">
          <div className="panel-title"><h2>Watch tonight</h2><span className="meta">{NAMES[w.sport]} · {w.date}</span></div>
          <div className="play-watch-body">
            <b>{w.away} @ {w.home}</b>
            <span>{w.watch_strong ? "Two above-average teams, and close to a coin flip" : "The closest call of the day"}: the model has {w.home} at {pct(w.home_win_prob)}.</span>
          </div>
          {Object.keys(slate.watch_by_sport).length > 1 && (
            <div className="play-watch-more">Best of each sport: {Object.values(slate.watch_by_sport).filter((g) => g !== w)
              .map((g) => `${NAMES[g.sport]} ${g.away} @ ${g.home}`).join(" · ")}</div>
          )}
        </section>
      )}

      <section className="panel">
        <div className="panel-title"><h2>Beat the model</h2><span className="meta">your picks · saved in this browser</span></div>
        <div className="play-score">
          <div><b>{you}–{graded.length - you}</b><small>you</small></div>
          <div><b>{model}–{graded.length - model}</b><small>the model, same games</small></div>
          <div><b>{youDis}–{disagree.length - youDis}</b><small>when you went against it</small></div>
          <div><b>{streak}</b><small>current streak{pending ? ` · ${pending} pending` : ""}</small></div>
        </div>
        {open.length === 0 ? <div className="empty">No games left to pick right now. Check back tomorrow.</div> : (
          <div className="play-picks">
            {open.slice(0, 40).map((g) => {
              const k = `${g.sport}:${g.game_id}`;
              const p = picks[k];
              const fav = g.home_win_prob >= 0.5 ? "home" : "away";
              return (
                <div key={k} className="play-pick">
                  <small>{NAMES[g.sport]} · {g.date}</small>
                  {(["away", "home"] as const).map((side) => (
                    <button key={side} className={`chip ${p?.pick === side ? "active" : ""}`} disabled={!!p} onClick={() => choose(g, side)}>
                      {side === "away" ? g.away : `@ ${g.home}`}
                      {p && <span className="play-model">{pct(side === "home" ? g.home_win_prob : 1 - g.home_win_prob)}{fav === side ? " ★" : ""}</span>}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        )}
        <div className="disclaimer ok">
          Pick first: picks lock, then the model's numbers (★ = its favourite) appear. Results are graded when games
          finish. Your picks stay in this browser only: no account, nothing sent to a server.
          {graded.length > 0 && <> <button className="linkish" onClick={() => { savePicks({}); setPicks({}); }}>Reset my record</button></>}
        </div>
      </section>
    </>
  );
}

// ---- Matchup machine -----------------------------------------------------------------------

const PRESETS: { label: string; sport: string; home: string; away: string; hs: number; as: number }[] = [
  { label: "1984-85 Oilers vs 2022-23 Golden Knights", sport: "nhl", home: "EDM", away: "VGK", hs: 19841985, as: 20222023 },
  { label: "2007 Patriots vs 2013 Seahawks", sport: "nfl", home: "NE", away: "SEA", hs: 2007, as: 2013 },
  { label: "2015-16 Warriors vs 2007-08 Celtics", sport: "nba", home: "GS", away: "BOS", hs: 20152016, as: 20072008 },
];

function MatchupMachine() {
  const [sport, setSport] = useState("nfl");
  const [teams, setTeams] = useState<Team[]>([]);
  const [seasons, setSeasons] = useState<{ id: number; label: string }[]>([]);
  const [home, setHome] = useState(""); const [away, setAway] = useState("");
  const [hs, setHs] = useState<number | "">(""); const [as_, setAs] = useState<number | "">("");
  const [neutral, setNeutral] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getJson<{ teams: Team[]; seasons: { id: number; label: string }[] }>(`/play/teams?sport=${sport}`).then((d) => {
      setTeams(d.teams); setSeasons(d.seasons);
      if (!d.teams.find((t) => t.code === home)) { setHome(d.teams[0]?.code ?? ""); setAway(d.teams[1]?.code ?? ""); }
    }).catch((e) => setErr(String(e?.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sport]);

  useEffect(() => {
    if (!home || !away || home === away && hs === as_) { setRes(null); return; }
    const q = new URLSearchParams({ sport, home, away, neutral: String(neutral) });
    if (hs) q.set("home_season", String(hs)); if (as_) q.set("away_season", String(as_));
    setErr(null);
    getJson(`/play/matchup?${q}`).then(setRes).catch((e) => { setRes(null); setErr(String(e?.message ?? e)); });
  }, [sport, home, away, hs, as_, neutral]);

  const preset = (p: typeof PRESETS[number]) => { setSport(p.sport); setHome(p.home); setAway(p.away); setHs(p.hs); setAs(p.as); setNeutral(true); };
  const color = (code: string) => teams.find((t) => t.code === code)?.color || "var(--accent)";
  const side = (label: string, team: string, setTeam: (v: string) => void, season: number | "", setSeason: (v: number | "") => void) => (
    <div className="mm-side">
      <small>{label}</small>
      <select value={team} onChange={(e) => setTeam(e.target.value)}>{teams.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}</select>
      <select value={season} onChange={(e) => setSeason(e.target.value ? Number(e.target.value) : "")}>
        <option value="">Now</option>{seasons.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
      </select>
    </div>
  );

  return (
    <section className="panel">
      <div className="panel-title"><h2>Matchup machine</h2><span className="meta">any two teams · any season</span></div>
      <div className="odds-groups">{Object.keys(NAMES).map((s) => (
        <button key={s} className={`chip ${s === sport ? "active" : ""}`} onClick={() => { setSport(s); setHs(""); setAs(""); }}>{NAMES[s]}</button>))}
      </div>
      <div className="mm-grid">
        {side("Away", away, setAway, as_, setAs)}
        <span className="mm-at">@</span>
        {side("Home", home, setHome, hs, setHs)}
      </div>
      <label className="mm-neutral"><input type="checkbox" checked={neutral} onChange={(e) => setNeutral(e.target.checked)} /> Neutral site</label>
      {err && <div className="error">{err.includes("404") ? "One of those teams has no rating for that season." : err}</div>}
      {res && (
        <div className="mm-result">
          <div className="prob-bar">
            <div className="away" style={{ width: `${(1 - res.home_win_prob) * 100}%`, background: color(away) }} />
            <div className="home" style={{ width: `${res.home_win_prob * 100}%`, background: color(home) }} />
          </div>
          <div className="mm-nums"><span><b>{pct(1 - res.home_win_prob)}</b> {away}</span><span>{home} <b>{pct(res.home_win_prob)}</b></span></div>
          <div className="disclaimer ok">{res.note} Ratings: {away} {res.away_rating}, {home} {res.home_rating}.</div>
        </div>
      )}
      <div className="mm-presets"><small>Try:</small>{PRESETS.map((p) => <button key={p.label} className="chip" onClick={() => preset(p)}>{p.label}</button>)}</div>
    </section>
  );
}

// ---- Rewatch --------------------------------------------------------------------------------

function Spark({ v, color }: { v: number[]; color: string }) {
  const pts = v.map((y, i) => `${(i / Math.max(v.length - 1, 1)) * 100},${(1 - y) * 30}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="rw-spark" aria-hidden>
      <line x1="0" y1="15" x2="100" y2="15" stroke="currentColor" strokeOpacity=".2" strokeDasharray="2 3" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function RewatchList() {
  const [d, setD] = useState<Rewatch | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getJson<Rewatch>("/play/rewatch").then(setD).catch((e) => setErr(String(e?.message ?? e))); }, []);
  if (err) return <div className="error">Couldn't load: {err}</div>;
  if (!d) return <div className="loading">Replaying last night's games…</div>;
  return (
    <section className="panel">
      <div className="panel-title"><h2>Rewatch</h2><span className="meta">the wildest games · {d.date}</span></div>
      {d.games.length === 0 ? <div className="empty">No finished games in the last two days.</div> : (
        <ol className="rw-list">
          {d.games.map((g, i) => (
            <li key={`${g.sport}:${g.game_id}`} className={i === 0 ? "rw-top" : ""}>
              <div className="rw-head">
                <span className="rw-rank">{i === 0 ? "Game of the night" : `#${i + 1}`}</span>
                <span><b>{g.winner}</b> beat {g.loser} <small>{NAMES[g.sport]}</small></span>
              </div>
              <Spark v={g.spark} color="var(--accent)" />
              <div className="rw-axis"><span>start</span><span>{g.winner}'s chance of winning</span><span>final</span></div>
              <div className="rw-facts">
                <span>Favourite flipped <b>{g.lead_changes}×</b></span>
                <span>{g.winner}'s lowest point: <b>{pct(g.winner_low)}</b></span>
                <span>Pre-game: <b>{pct(g.p_winner)}</b></span>
              </div>
              {g.top_swing && <div className="rw-swing">Biggest swing ({g.top_swing.label}): {g.top_swing.text}</div>}
            </li>
          ))}
        </ol>
      )}
      <div className="disclaimer ok">{d.note}</div>
    </section>
  );
}

export function Play() {
  const [tab, setTab] = useState<"picks" | "matchup" | "rewatch">("picks");
  return (
    <>
      <div className="subhead">Pick against the model, pit any two teams against each other, or find last night's wildest game.</div>
      <nav className="tabs" role="tablist">
        {([["picks", "Beat the model"], ["matchup", "Matchup machine"], ["rewatch", "Rewatch"]] as const).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>
      {tab === "picks" && <BeatTheModel />}
      {tab === "matchup" && <MatchupMachine />}
      {tab === "rewatch" && <RewatchList />}
    </>
  );
}
