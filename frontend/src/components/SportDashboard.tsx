import { useEffect, useState, type ReactNode } from "react";
import type {
  CalibrationResponse,
  MetricBlock,
  RatingsHistoryResponse,
  SeasonRow,
  SeasonsResponse,
  TodayResponse,
} from "../types";
import { TrajectoryChart } from "./TrajectoryChart";
import { TodaysGames } from "./TodaysGames";
import { CalibrationPanel } from "./CalibrationPanel";
import { SeasonOdds } from "./SeasonOdds";

// Shared dashboard for sports whose API follows the NBA/NFL contract
// (methodology §6 breakdowns + flags ride along on the calibration payload).

type Breakdown = { n: number; model?: MetricBlock };
export type SportCalibration = CalibrationResponse & {
  verdict: Record<string, "PASS" | "FAIL">;
  flags: Record<string, boolean | number | null>;
  breakdowns: Record<string, any>;
};

export type SportConfig = {
  league: string;                     // display label ("NBA", "FBS")
  sport?: string;                     // route id when it differs from the label ("cfb")
  subhead: ReactNode;
  todayLabel: string;                 // "Today's games" / "This week"
  periodLabel: (p: number) => string;
  emptyNote?: string;
  oddsLabel?: string;                 // tab name ("Season odds", "Playoff odds", "Projected records")
  footnote: string;
  championLabel: (team: string, seasonLabel: string) => string;
  breakdownRows: [string, (b: SportCalibration["breakdowns"]) => Breakdown | undefined][];
  flagNotes: (cal: SportCalibration) => string[];
  api: {
    seasons: () => Promise<SeasonsResponse>;
    history: (season: number) => Promise<RatingsHistoryResponse>;
    today: () => Promise<TodayResponse>;
    calibration: () => Promise<SportCalibration>;
  };
};

type Tab = "trajectories" | "today" | "odds" | "calibration";

// Payloads carry per-team colors; this is only the fallback.
const fallbackColor = () => "#888888";

function paramsLabel(fp: CalibrationResponse["frozen_params"]): string {
  return `K=${fp.k_regular}/${fp.k_playoff}, carry=${fp.carry}, home=${fp.home_bump}, MOV ${fp.mov ? "on" : "off"}`;
}

function Breakdowns({ cal, cfg }: { cal: SportCalibration; cfg: SportConfig }) {
  const ece = cal.section_6_targets.ece_max;
  const notes = cfg.flagNotes(cal);
  return (
    <div className="cal cal-breakdowns">
      <h3 className="cal-h">Pre-registered breakdowns (same one-shot pass)</h3>
      <table className="metrics">
        <thead>
          <tr>
            <th></th>
            <th className="num">log-loss</th>
            <th className="num">Brier</th>
            <th className="num">ECE</th>
            <th className="num dim">n</th>
          </tr>
        </thead>
        <tbody>
          {cfg.breakdownRows.map(([label, pick]) => {
            const b = pick(cal.breakdowns);
            if (!b?.model) return null;
            return (
              <tr key={label}>
                <td>{label}</td>
                <td className="num">{b.model.log_loss.toFixed(5)}</td>
                <td className="num">{b.model.brier.toFixed(5)}</td>
                <td className={`num ${b.model.ece < ece ? "" : "warn"}`}>{b.model.ece.toFixed(4)}</td>
                <td className="num dim">{b.n}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {notes.map((n) => (
        <div key={n} className="disclaimer">{n}</div>
      ))}
    </div>
  );
}

export function SportDashboard({ cfg }: { cfg: SportConfig }) {
  const [tab, setTab] = useState<Tab>("trajectories");
  const [seasons, setSeasons] = useState<SeasonRow[] | null>(null);
  const [season, setSeason] = useState<number | null>(null);
  const [history, setHistory] = useState<RatingsHistoryResponse | null>(null);
  const [today, setToday] = useState<TodayResponse | null>(null);
  const [cal, setCal] = useState<SportCalibration | null>(null);
  const [err, setErr] = useState<Record<string, string>>({});
  const fail = (k: string) => (e: Error) => setErr((prev) => ({ ...prev, [k]: e.message }));

  useEffect(() => {
    cfg.api.seasons()
      .then((r) => {
        setSeasons(r.seasons);
        if (r.seasons.length) setSeason(r.seasons[0].season_id);
      })
      .catch(fail("seasons"));
  }, []);

  useEffect(() => {
    if (season == null) return;
    setHistory(null);
    cfg.api.history(season).then(setHistory).catch(fail("history"));
  }, [season]);

  // Today's games: load once, then poll every 60 s while any game is live.
  useEffect(() => {
    let live = false;
    const tick = () =>
      cfg.api.today()
        .then((r) => {
          setToday(r);
          live = r.matchups.some((m) => m.state === "LIVE");
        })
        .catch(fail("today"));
    tick();
    const id = setInterval(() => live && tick(), 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (tab !== "calibration" || cal) return;
    cfg.api.calibration().then(setCal).catch(fail("calibration"));
  }, [tab, cal]);

  const tabButton = (id: Tab, label: string, badge?: number) => (
    <button
      role="tab"
      aria-selected={tab === id}
      className={`tab ${tab === id ? "active" : ""}`}
      onClick={() => setTab(id)}
    >
      {label}
      {!!badge && <span className="badge">{badge}</span>}
    </button>
  );

  return (
    <>
      <div className="subhead">{cfg.subhead}</div>

      <nav className="tabs" role="tablist">
        {tabButton("trajectories", "Trajectories")}
        {tabButton("today", cfg.todayLabel, today?.matchups.length)}
        {tabButton("odds", cfg.oddsLabel ?? "Season odds")}
        {tabButton("calibration", "Calibration")}
      </nav>

      {tab === "trajectories" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title">
            <h2>Rating trajectories</h2>
            {seasons && season != null && (
              <select className="select" value={season} onChange={(e) => setSeason(Number(e.target.value))}>
                {seasons.map((s) => (
                  <option key={s.season_id} value={s.season_id}>{s.label}</option>
                ))}
              </select>
            )}
          </div>
          {err.seasons && <div className="error">Couldn't load seasons: {err.seasons}</div>}
          {err.history && <div className="error">Couldn't load trajectories: {err.history}</div>}
          {!history && !err.history && <div className="loading">Loading…</div>}
          {history && <TrajectoryChart data={history} colorFor={fallbackColor} />}
          {history?.cup_winner && (
            <div className="champion-note">👑 {cfg.championLabel(history.cup_winner, history.label)}</div>
          )}
        </section>
      )}

      {tab === "today" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title">
            <h2>{cfg.todayLabel}</h2>
            <span className="meta">{today?.date ?? ""}</span>
          </div>
          {err.today && <div className="error">Couldn't load today's games: {err.today}</div>}
          {!today && !err.today && <div className="loading">Loading…</div>}
          {today && (
            <TodaysGames
              data={today}
              league={cfg.league}
              sport={cfg.sport ?? cfg.league.toLowerCase()}
              colorFor={fallbackColor}
              periodLabel={cfg.periodLabel}
              emptyNote={cfg.emptyNote}
              footnote={cfg.footnote}
            />
          )}
        </section>
      )}

      {tab === "odds" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title"><h2>{cfg.oddsLabel ?? "Season odds"}</h2><span className="meta">Monte Carlo · frozen ratings</span></div>
          <SeasonOdds sport={cfg.sport ?? cfg.league.toLowerCase()} colorFor={(_t, r) => r.color ?? "#888"} />
        </section>
      )}

      {tab === "calibration" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title">
            <h2>Calibration</h2>
            <span className="meta">held-out test set</span>
          </div>
          {err.calibration && <div className="error">Couldn't load calibration: {err.calibration}</div>}
          {!cal && !err.calibration && <div className="loading">Loading…</div>}
          {cal && (
            <>
              <CalibrationPanel
                data={cal}
                paramsLabel={paramsLabel(cal.frozen_params)}
              />
              <Breakdowns cal={cal} cfg={cfg} />
            </>
          )}
        </section>
      )}
    </>
  );
}
