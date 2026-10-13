import { useEffect, useState } from "react";
import { getJson } from "../http";
import { navigate } from "../router";

/** Cross-sport report card (backend core/report_card.py). Season totals are
 *  hidden for seasons that are still a pending one-time test (§10). */
type Game = { sport: string; date: string; home: string; away: string; p_home: number; home_won: boolean | null;
  postseason: boolean; game_id: string; winner: string; loser: string; p_winner: number };
type Summary = { n: number; favorites_won?: number; favorites_lost?: number; brier?: number; log_loss?: number;
  coin_flip_log_loss?: number; confident_n?: number; confident_right?: number; confident_mean_p?: number | null };
type SportBlock = { season: number; error?: string; quarantine_note: string | null;
  last_slate: { date: string | null; games: Game[]; favorites_won: number | null };
  season_upsets: Game[]; season_summary: Summary | null };
type Report = { upset_of_the_night: Game | null; sports: Record<string, SportBlock> };

const NAMES: Record<string, string> = { nhl: "NHL", nba: "NBA", nfl: "NFL", mlb: "MLB", cfb: "College football" };
const pct = (v: number) => `${Math.round(v * 100)}%`;
const seasonLabel = (s?: number) => (!s ? "" : s > 9999 ? `${Math.floor(s / 10000)}-${String(s % 100).padStart(2, "0")}` : String(s));

function GameLine({ g }: { g: Game }) {
  return (
    <button className="rc-game" onClick={() => navigate(`/${g.sport}/game/${g.game_id}`)} title="Open game page">
      <span className={`rc-p ${g.p_winner < 0.35 ? "upset" : g.p_winner < 0.5 ? "mild" : ""}`}>{pct(g.p_winner)}</span>
      <span><b>{g.winner}</b> beat {g.loser}</span>
      <small>{g.date}{g.postseason ? " · postseason" : ""}</small>
    </button>
  );
}

export function ReportCard() {
  const [r, setR] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getJson<Report>("/report").then(setR).catch((e) => setErr(String(e?.message ?? e))); }, []);

  if (err) return <div className="error">Couldn't load the report card: {err}</div>;
  if (!r) return <div className="loading">Grading the models…</div>;
  const u = r.upset_of_the_night;

  return (
    <>
      <div className="subhead">
        How the frozen models did, using the probability each one published <i>before</i> the game. Percentages are the
        model's pre-game chance for the team that won.
      </div>

      {u && (
        <section className="panel rc-hero">
          <div className="panel-title"><h2>Upset of the night</h2><span className="meta">{NAMES[u.sport]} · {u.date}</span></div>
          <div className="rc-hero-body" onClick={() => navigate(`/${u.sport}/game/${u.game_id}`)}>
            <span className="rc-hero-p">{pct(u.p_winner)}</span>
            <span><b>{u.winner}</b> beat {u.loser}. The model gave them a {pct(u.p_winner)} chance.
              {u.p_winner < 0.3 ? " About once in every " + Math.round(1 / u.p_winner) + " tries." : ""}</span>
          </div>
        </section>
      )}

      <div className="rc-grid">
        {Object.entries(r.sports).map(([s, b]) => (
          <section key={s} className="panel rc-sport" data-sport-card={s}>
            <div className="panel-title"><h2>{NAMES[s]}</h2><span className="meta">{seasonLabel(b.season)}</span></div>
            {b.error && <div className="error">Unavailable right now.</div>}
            {!b.error && (
              <>
                <h3 className="cal-h">Last slate {b.last_slate.date ? `· ${b.last_slate.date}` : ""}</h3>
                {b.last_slate.games.length === 0 ? <div className="empty">No completed games yet this season.</div> : (
                  <>
                    {b.last_slate.favorites_won != null && (
                      <p className="rc-line">Favorites went <b>{b.last_slate.favorites_won}–{b.last_slate.games.length - b.last_slate.favorites_won}</b>.</p>
                    )}
                    <div className="rc-games">{b.last_slate.games.slice(0, 4).map((g) => <GameLine key={g.game_id} g={g} />)}</div>
                  </>
                )}

                <h3 className="cal-h">Season so far</h3>
                {b.quarantine_note ? (
                  <p className="rc-line rc-locked">🔒 Season accuracy is hidden: this season is the held-out test. {b.quarantine_note}</p>
                ) : b.season_summary && b.season_summary.n > 0 ? (
                  <div className="rc-stats">
                    <div><b>{b.season_summary.favorites_won}–{b.season_summary.favorites_lost}</b><small>favorites' record</small></div>
                    <div><b>{b.season_summary.log_loss?.toFixed(3)}</b><small>log-loss (coin flip 0.693)</small></div>
                    {b.season_summary.confident_n ? (
                      <div><b>{b.season_summary.confident_right}/{b.season_summary.confident_n}</b>
                        <small>right when ≥65% sure (said {pct(b.season_summary.confident_mean_p ?? 0)}, hit {pct((b.season_summary.confident_right ?? 0) / b.season_summary.confident_n)})</small></div>
                    ) : null}
                  </div>
                ) : <div className="empty">No regular-season games yet.</div>}

                {b.season_upsets.length > 0 && (
                  <>
                    <h3 className="cal-h">Biggest upsets this season</h3>
                    <div className="rc-games">{b.season_upsets.slice(0, 3).map((g) => <GameLine key={g.game_id} g={g} />)}</div>
                  </>
                )}
              </>
            )}
          </section>
        ))}
      </div>
      <div className="disclaimer ok">
        Postseason games never count toward season totals, and seasons that are still a pending one-time test show
        results only. Watching a test set's score all season would break the project's pre-registration rule
        (score each test exactly once).
      </div>
    </>
  );
}
