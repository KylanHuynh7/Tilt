import { useEffect, useState } from "react";
import { NhlDashboard } from "./sports/nhl/NhlDashboard";
import { NbaDashboard } from "./sports/nba/NbaDashboard";
import { NflDashboard } from "./sports/nfl/NflDashboard";
import { GameDetail } from "./components/GameDetail";
import { colorFor as nhlColorFor } from "./sports/nhl/teamColors";
import { navigate, parseRoute } from "./router";

const PERIOD_LABELS: Record<string, (p: number) => string> = {
  nhl: (p) => (p >= 4 ? "OT" : `P${p}`),
  nba: (p) => (p <= 4 ? `Q${p}` : p === 5 ? "OT" : `${p - 4}OT`),
  nfl: (p) => (p <= 4 ? `Q${p}` : "OT"),
};

type SportId = "nhl" | "nba" | "nfl" | "mlb";
type Sport = {
  id: SportId;
  name: string;
  status: "live" | "in_development" | "planned";
  version?: string; // model version tag shown in the header when live
  color: string;    // the sport's identity color (pill + world accent)
};

// Mirrors GET /sports. Kept client-side so the switcher renders even when the
// backend is asleep or on an older build.
const SPORTS: Sport[] = [
  { id: "nhl", name: "NHL", status: "live", version: "v2", color: "var(--c-nhl)" },
  { id: "nba", name: "NBA", status: "live", version: "v1.1", color: "var(--c-nba)" },
  { id: "nfl", name: "NFL", status: "live", version: "v1.1", color: "var(--c-nfl)" },
  { id: "mlb", name: "MLB", status: "planned", color: "var(--c-mlb)" },
];

const STATUS_LABEL: Record<Sport["status"], string> = {
  live: "Live",
  in_development: "In development",
  planned: "Planned",
};

// Minimal line-art glyph per sport, drawn in the pill's color.
function SportGlyph({ id }: { id: SportId }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const };
  switch (id) {
    case "nhl": // puck + stick
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <ellipse cx="9" cy="17" rx="6" ry="2.6" {...common} />
          <path d="M3 17v1.6c0 1.4 2.7 2.6 6 2.6s6-1.2 6-2.6V17" {...common} />
          <path d="M21 3l-6 11h4.5" {...common} />
        </svg>
      );
    case "nba": // basketball
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" {...common} />
          <path d="M3 12h18M12 3v18M5.6 5.6c3.4 3.4 3.4 9.4 0 12.8M18.4 5.6c-3.4 3.4-3.4 9.4 0 12.8" {...common} />
        </svg>
      );
    case "nfl": // football
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4.5 19.5c-1.7-5.6 1-11.8 6.3-14.2 3-1.3 6.1-1.3 8.7-.3 1.7 5.6-1 11.8-6.3 14.2-3 1.3-6.1 1.3-8.7.3z" {...common} />
          <path d="M9 15l6-6M10.5 10.5l1.5 1.5M12 9l1.5 1.5M9 12l1.5 1.5" {...common} />
        </svg>
      );
    case "mlb": // baseball
      return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" {...common} />
          <path d="M7 4.6c2 2.2 2 12.6 0 14.8M17 4.6c-2 2.2-2 12.6 0 14.8" {...common} />
        </svg>
      );
  }
}

export default function App() {
  const ids = SPORTS.map((x) => x.id);
  const [route, setRoute] = useState(() => parseRoute(ids));
  const sportId = route.sport as SportId;
  const sport = SPORTS.find((s) => s.id === sportId)!;

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(ids));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Per-sport accent color is driven from CSS via this attribute.
  useEffect(() => {
    document.documentElement.dataset.sport = sportId;
    document.title = route.gameId ? `Tilt — ${sport.name} game` : `Tilt — ${sport.name}`;
  }, [sportId, sport.name, route.gameId]);

  const go = (id: SportId) => navigate(`/${id}`);

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-line">
            <span className="wordmark">Tilt</span>
            <span className="brand-sport">{sport.name}</span>
          </div>
          <p className="brand-tagline">
            Pre-registered, honestly calibrated win probabilities — one model per sport.
          </p>
        </div>
        {sport.version && <span className="tag">model {sport.version}</span>}
      </header>

      <nav className="sport-nav" aria-label="Sport">
        {SPORTS.map((s) => (
          <button
            key={s.id}
            className={`sport-pill ${s.id === sportId ? "active" : ""}`}
            data-status={s.status}
            style={{ "--pill": s.color } as React.CSSProperties}
            aria-current={s.id === sportId ? "page" : undefined}
            onClick={() => go(s.id)}
          >
            <SportGlyph id={s.id} />
            {s.name}
            {s.status !== "live" && <span className="sport-status">{STATUS_LABEL[s.status]}</span>}
          </button>
        ))}
      </nav>

      {route.gameId && sport.status === "live" ? (
        <GameDetail
          key={`${sportId}-${route.gameId}`}
          sport={sportId}
          gameId={route.gameId}
          colorFor={sportId === "nhl" ? nhlColorFor : () => "#888888"}
          periodLabel={PERIOD_LABELS[sportId] ?? ((p) => `P${p}`)}
        />
      ) : sportId === "nhl" ? (
        <NhlDashboard />
      ) : sportId === "nba" ? (
        <NbaDashboard />
      ) : sportId === "nfl" ? (
        <NflDashboard />
      ) : (
        <section className="panel">
          <div className="panel-title">
            <h2>{sport.name} — {STATUS_LABEL[sport.status].toLowerCase()}</h2>
          </div>
          <div className="empty">
            {sport.status === "in_development"
              ? `The ${sport.name} methodology is approved and the model is being built: ingest, rating engine, validation freeze, then a one-shot test evaluation. Probabilities appear here once it's frozen and evaluated.`
              : `${sport.name} is on the roadmap. Each sport gets its own pre-registered methodology before it ships.`}
          </div>
        </section>
      )}
    </div>
  );
}
