import { useEffect, useMemo, useState } from "react";
import {
  fetchCalibration,
  fetchCup,
  fetchHistory,
  fetchSeasons,
  fetchToday,
  type CalibrationResponse,
  type CupResponse,
  type RatingsHistoryResponse,
  type SeasonRow,
  type TodayResponse,
} from "./api";
import { TrajectoryChart } from "./components/TrajectoryChart";
import { TodaysGames } from "./components/TodaysGames";
import { CalibrationPanel } from "./components/CalibrationPanel";
import { CupOdds } from "./components/CupOdds";

type Tab = "trajectories" | "today" | "calibration";

export default function App() {
  const [tab, setTab] = useState<Tab>("trajectories");

  const [seasons, setSeasons] = useState<SeasonRow[] | null>(null);
  const [seasonsErr, setSeasonsErr] = useState<string | null>(null);
  const [season, setSeason] = useState<number | null>(null);

  const [history, setHistory] = useState<RatingsHistoryResponse | null>(null);
  const [historyErr, setHistoryErr] = useState<string | null>(null);

  const [today, setToday] = useState<TodayResponse | null>(null);
  const [todayErr, setTodayErr] = useState<string | null>(null);

  const [cal, setCal] = useState<CalibrationResponse | null>(null);
  const [calErr, setCalErr] = useState<string | null>(null);

  const [cup, setCup] = useState<CupResponse | null>(null);
  const [cupErr, setCupErr] = useState<string | null>(null);

  // Load season list once. The default selection is the most-recent season
  // (the API returns sorted desc), which is the current 2025-26.
  useEffect(() => {
    fetchSeasons()
      .then((res) => {
        setSeasons(res.seasons);
        if (res.seasons.length > 0 && season == null) {
          setSeason(res.seasons[0].season_id);
        }
      })
      .catch((e: Error) => setSeasonsErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the selected season's history.
  useEffect(() => {
    if (season == null) return;
    setHistory(null);
    setHistoryErr(null);
    fetchHistory(season)
      .then(setHistory)
      .catch((e: Error) => setHistoryErr(e.message));
  }, [season]);

  // Load today's games once on mount, and poll every 60s while any matchup
  // is in progress (v2.3 §16 live polling).
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      fetchToday()
        .then((res) => {
          if (cancelled) return;
          setToday(res);
        })
        .catch((e: Error) => {
          if (cancelled) return;
          setTodayErr(e.message);
        });
    };
    tick();
    const interval = setInterval(() => {
      // Only poll while there's something live to refresh.
      if (today?.matchups.some((m) => !!m.live_state)) tick();
    }, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // intentionally don't depend on `today` to avoid restarting the interval
    // every time the payload updates; the interval reads `today` from closure
    // via setToday-driven re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // v2.3 §16 hero-chart live refresh: when viewing the in-progress 2025-26
  // season, poll the trajectory every 60s so newly-completed games appear
  // without a manual refresh.
  useEffect(() => {
    if (season !== 20252026) return;
    const interval = setInterval(() => {
      fetchHistory(20252026).then(setHistory).catch(() => {});
    }, 60_000);
    return () => clearInterval(interval);
  }, [season]);

  // Cup odds: load once when first entering the Trajectories tab, then poll
  // every 5 minutes so probabilities track new games without spamming the sim.
  useEffect(() => {
    if (tab !== "trajectories") return;
    if (cup || cupErr) {
      // already loaded once; just keep the periodic refresh going
    } else {
      fetchCup().then(setCup).catch((e: Error) => setCupErr(e.message));
    }
    const interval = setInterval(() => {
      fetchCup().then(setCup).catch(() => {});
    }, 5 * 60_000);
    return () => clearInterval(interval);
  }, [tab, cup, cupErr]);

  // Lazy-load calibration only when the tab is opened.
  useEffect(() => {
    if (tab !== "calibration" || cal || calErr) return;
    fetchCalibration()
      .then(setCal)
      .catch((e: Error) => setCalErr(e.message));
  }, [tab, cal, calErr]);

  const selectedSeasonRow = useMemo(
    () => seasons?.find((s) => s.season_id === season),
    [seasons, season]
  );

  return (
    <div className="app">
      <div className="header">
        <h1>Tilt — NHL Rating System</h1>
        <span className="tag">v1</span>
      </div>
      <div className="subhead">
        Interpretable team ratings with honest calibration reporting. Methodology frozen
        before any code was written — see METHODOLOGY.md.
      </div>

      <nav className="tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "trajectories"}
          className={`tab ${tab === "trajectories" ? "active" : ""}`}
          onClick={() => setTab("trajectories")}
        >
          Trajectories
        </button>
        <button
          role="tab"
          aria-selected={tab === "today"}
          className={`tab ${tab === "today" ? "active" : ""}`}
          onClick={() => setTab("today")}
        >
          Today's games
          {today && today.matchups.length > 0 && (
            <span className="badge">{today.matchups.length}</span>
          )}
        </button>
        <button
          role="tab"
          aria-selected={tab === "calibration"}
          className={`tab ${tab === "calibration" ? "active" : ""}`}
          onClick={() => setTab("calibration")}
        >
          Calibration
        </button>
      </nav>

      {tab === "trajectories" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title">
            <h2>Rating trajectories</h2>
            {seasonsErr && <span className="error">Couldn't load seasons: {seasonsErr}</span>}
            {seasons && season != null && (
              <select
                className="select"
                value={season}
                onChange={(e) => setSeason(parseInt(e.target.value, 10))}
              >
                {seasons.map((s) => (
                  <option key={s.season_id} value={s.season_id}>
                    {s.label}{s.pre_1967 ? " (legacy)" : ""}
                  </option>
                ))}
              </select>
            )}
          </div>

          {selectedSeasonRow?.pre_1967 && (
            <div className="disclaimer banner">
              Pre-1967 legacy season. Data consistency is not guaranteed and this season is
              excluded from all model training and evaluation per §2 / §3 of the methodology.
              Trajectories shown for historical exploration only.
            </div>
          )}

          {historyErr && <div className="error">Couldn't load trajectories: {historyErr}</div>}
          {!history && !historyErr && season != null && <div className="loading">Loading…</div>}
          {history && <TrajectoryChart data={history} />}

          {/* Cup odds panel — only show when viewing the in-progress season */}
          {season === 20252026 && (
            <>
              {cupErr && <div className="error">Couldn't load Cup odds: {cupErr}</div>}
              {!cup && !cupErr && <div className="loading">Loading Cup odds…</div>}
              {cup && <CupOdds data={cup} />}
            </>
          )}
        </section>
      )}

      {tab === "today" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title">
            <h2>Today's games</h2>
            <span className="meta">{today?.date ?? ""}</span>
          </div>
          {todayErr && (
            <div className="error">Couldn't load today's games: {todayErr}</div>
          )}
          {!today && !todayErr && <div className="loading">Loading…</div>}
          {today && <TodaysGames data={today} />}
        </section>
      )}

      {tab === "calibration" && (
        <section className="panel" role="tabpanel">
          <div className="panel-title">
            <h2>Calibration</h2>
            <span className="meta">held-out test set</span>
          </div>
          {calErr && <div className="error">Couldn't load calibration: {calErr}</div>}
          {!cal && !calErr && <div className="loading">Loading…</div>}
          {cal && <CalibrationPanel data={cal} />}
        </section>
      )}
    </div>
  );
}
