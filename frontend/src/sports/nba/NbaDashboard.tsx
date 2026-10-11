import { useEffect, useState } from "react";
import {
  fetchNbaCalibration,
  fetchNbaHistory,
  fetchNbaSeasons,
  fetchNbaToday,
  type NbaCalibrationResponse,
} from "./api";
import type { RatingsHistoryResponse, SeasonRow, TodayResponse } from "../../types";
import { TrajectoryChart } from "../../components/TrajectoryChart";
import { TodaysGames } from "../../components/TodaysGames";
import { CalibrationPanel } from "../../components/CalibrationPanel";

type Tab = "trajectories" | "today" | "calibration";

// Payloads carry per-team colors; this is only the fallback.
const fallbackColor = () => "#888888";
// ESPN period numbers: 1-4 quarters, 5 = OT, 6 = 2OT, …
const nbaPeriod = (p: number) => (p <= 4 ? `Q${p}` : p === 5 ? "OT" : `${p - 4}OT`);

const BREAKDOWN_ROWS: [string, (b: NbaCalibrationResponse["breakdowns"]) => { n: number; model?: { log_loss: number; brier: number; ece: number } }][] = [
  ["2024-25", (b) => b.per_season["20242025"]],
  ["2025-26", (b) => b.per_season["20252026"]],
  ["Regular season", (b) => b.regular_season],
  ["Play-in + playoffs", (b) => b.postseason_play_in_and_playoffs],
  ["Early season", (b) => b.segments.early],
  ["Mid season", (b) => b.segments.mid],
  ["Late season", (b) => b.segments.late],
  ["Neutral site", (b) => b.neutral_site],
];

function Breakdowns({ cal }: { cal: NbaCalibrationResponse }) {
  const ece = cal.section_6_targets.ece_max;
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
          {BREAKDOWN_ROWS.map(([label, pick]) => {
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
      {cal.flags.late_segment_ece_over_2x_mid && (
        <div className="disclaimer">
          §8 flag: late-season ECE is {cal.flags.late_over_mid_ece_ratio?.toFixed(2)}× mid-season.
          The model is <em>under</em>confident late (favorites win more often than predicted),
          the opposite of the pre-registered rest effect and consistent with tanking. Neutral-site
          figures rest on very few games.
        </div>
      )}
    </div>
  );
}

export function NbaDashboard() {
  const [tab, setTab] = useState<Tab>("trajectories");
  const [seasons, setSeasons] = useState<SeasonRow[] | null>(null);
  const [season, setSeason] = useState<number | null>(null);
  const [history, setHistory] = useState<RatingsHistoryResponse | null>(null);
  const [today, setToday] = useState<TodayResponse | null>(null);
  const [cal, setCal] = useState<NbaCalibrationResponse | null>(null);
  const [err, setErr] = useState<Record<string, string>>({});
  const fail = (k: string) => (e: Error) => setErr((prev) => ({ ...prev, [k]: e.message }));

  useEffect(() => {
    fetchNbaSeasons()
      .then((r) => {
        setSeasons(r.seasons);
        if (r.seasons.length) setSeason(r.seasons[0].season_id);
      })
      .catch(fail("seasons"));
  }, []);

  useEffect(() => {
    if (season == null) return;
    setHistory(null);
    fetchNbaHistory(season).then(setHistory).catch(fail("history"));
  }, [season]);

  // Today's games: load once, then poll every 60 s while any game is live.
  useEffect(() => {
    let live = false;
    const tick = () =>
      fetchNbaToday()
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
    fetchNbaCalibration().then(setCal).catch(fail("calibration"));
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
      <div className="subhead">
        Elo ratings with home-court and margin-of-victory adjustments, frozen on 2018-19 → 2023-24
        and evaluated once on 2024-25 + 2025-26. See methodology/NBA.md.
      </div>

      <nav className="tabs" role="tablist">
        {tabButton("trajectories", "Trajectories")}
        {tabButton("today", "Today's games", today?.matchups.length)}
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
            <div className="meta">👑&nbsp;{history.cup_winner} won the {history.label} NBA Finals.</div>
          )}
        </section>
      )}

      {tab === "today" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title">
            <h2>Today's games</h2>
            <span className="meta">{today?.date ?? ""}</span>
          </div>
          {err.today && <div className="error">Couldn't load today's games: {err.today}</div>}
          {!today && !err.today && <div className="loading">Loading…</div>}
          {today && (
            <TodaysGames
              data={today}
              league="NBA"
              colorFor={fallbackColor}
              periodLabel={nbaPeriod}
              emptyNote="Preseason and exhibition games aren't modeled."
              footnote="Pre-game probabilities from the frozen NBA v1 model; live probabilities from the v1.1 in-game model (score margin, time left, and pre-game edge), refreshed every 60 s."
            />
          )}
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
                paramsLabel={`K=${cal.frozen_params.k_regular}/${cal.frozen_params.k_playoff}, carry=${cal.frozen_params.carry}, home=${cal.frozen_params.home_bump}, MOV ${cal.frozen_params.mov ? "on" : "off"}`}
              />
              <Breakdowns cal={cal} />
            </>
          )}
        </section>
      )}
    </>
  );
}
