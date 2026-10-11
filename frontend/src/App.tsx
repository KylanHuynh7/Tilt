import { useEffect, useState } from "react";
import { NhlDashboard } from "./sports/nhl/NhlDashboard";
import { NbaDashboard } from "./sports/nba/NbaDashboard";

type SportId = "nhl" | "nba" | "nfl" | "mlb";
type Sport = {
  id: SportId;
  name: string;
  status: "live" | "in_development" | "planned";
  version?: string; // model version tag shown in the header when live
};

// Mirrors GET /sports. Kept client-side so the switcher renders even when the
// backend is asleep or on an older build.
const SPORTS: Sport[] = [
  { id: "nhl", name: "NHL", status: "live", version: "v2" },
  { id: "nba", name: "NBA", status: "live", version: "v1.1" },
  { id: "nfl", name: "NFL", status: "planned" },
  { id: "mlb", name: "MLB", status: "planned" },
];

const STATUS_LABEL: Record<Sport["status"], string> = {
  live: "Live",
  in_development: "In development",
  planned: "Planned",
};

// Path-based routing: /nhl, /nba, … ("/" is NHL). vercel.json rewrites every
// path to index.html, so deep links work without a router library.
function sportFromPath(): SportId {
  const seg = window.location.pathname.split("/")[1]?.toLowerCase();
  return SPORTS.some((s) => s.id === seg) ? (seg as SportId) : "nhl";
}

export default function App() {
  const [sportId, setSportId] = useState<SportId>(sportFromPath);
  const sport = SPORTS.find((s) => s.id === sportId)!;

  useEffect(() => {
    const onPop = () => setSportId(sportFromPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Per-sport accent color is driven from CSS via this attribute.
  useEffect(() => {
    document.documentElement.dataset.sport = sportId;
    document.title = `Tilt — ${sport.name}`;
  }, [sportId, sport.name]);

  const go = (id: SportId) => {
    if (id === sportId) return;
    window.history.pushState(null, "", `/${id}`);
    setSportId(id);
  };

  return (
    <div className="app">
      <div className="header">
        <h1>Tilt — {sport.name}</h1>
        {sport.version && <span className="tag">{sport.version}</span>}
      </div>

      <nav className="sport-nav" aria-label="Sport">
        {SPORTS.map((s) => (
          <button
            key={s.id}
            className={`sport-pill ${s.id === sportId ? "active" : ""}`}
            aria-current={s.id === sportId ? "page" : undefined}
            onClick={() => go(s.id)}
          >
            {s.name}
            {s.status !== "live" && <span className="sport-status">{STATUS_LABEL[s.status]}</span>}
          </button>
        ))}
      </nav>

      {sportId === "nhl" ? (
        <NhlDashboard />
      ) : sportId === "nba" ? (
        <NbaDashboard />
      ) : (
        <section className="panel">
          <div className="panel-title">
            <h2>{sport.name} — {STATUS_LABEL[sport.status].toLowerCase()}</h2>
          </div>
          <div className="empty">
            {sport.status === "in_development"
              ? `The ${sport.name} model's methodology is being written and reviewed before any model code, the same way the NHL model was. Probabilities appear here once it's frozen and evaluated.`
              : `${sport.name} is on the roadmap. Each sport gets its own pre-registered methodology before it ships.`}
          </div>
        </section>
      )}
    </div>
  );
}
