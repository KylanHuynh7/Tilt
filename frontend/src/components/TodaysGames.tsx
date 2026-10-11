import type { Matchup, TodayResponse } from "../types";
import { navigate } from "../router";

type Props = {
  data: TodayResponse;
  league: string;
  sport: string;                          // route segment, e.g. "nba"                         // "NHL", "NBA", … for the empty state
  colorFor: (code: string) => string;     // fallback when the payload has no color
  periodLabel: (period: number) => string;
  footnote: string;                       // model/disclaimer line under the cards
  emptyNote?: string;
};

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function clockLabel(seconds: number): string {
  const mm = Math.floor(seconds / 60).toString().padStart(2, "0");
  const ss = (seconds % 60).toString().padStart(2, "0");
  return `${mm}:${ss}`;
}

function TeamBadge({ team, color }: { team: string; color: string }) {
  return (
    <div className="team-badge" style={{ backgroundColor: color }}>
      {team}
    </div>
  );
}

function GameCard({ m, sport, colorFor, periodLabel }: {
  m: Matchup;
  sport: string;
  colorFor: Props["colorFor"];
  periodLabel: Props["periodLabel"];
}) {
  const awayPct = m.away_win_prob * 100;
  const homePct = m.home_win_prob * 100;
  const isLive = !!m.live_state;
  const isFinal = !isLive && m.home_score != null && ["OFF", "FINAL"].includes(m.state);
  const awayColor = m.away_color ?? colorFor(m.away);
  const homeColor = m.home_color ?? colorFor(m.home);
  // Card, edge stripe, and probability bars are painted in the teams' colors.
  const teamVars = { "--away": awayColor, "--home": homeColor } as React.CSSProperties;
  return (
    <div
      className={`game clickable ${isLive ? "live" : ""}`}
      style={teamVars}
      role="link"
      tabIndex={0}
      aria-label={`${m.away} at ${m.home}: open game analysis`}
      onClick={() => navigate(`/${sport}/game/${m.game_id}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(`/${sport}/game/${m.game_id}`);
        }
      }}
    >
      <div className="team">
        <TeamBadge team={m.away} color={awayColor} />
        <span className="abbr">{m.away}</span>
        <span className="rating">{m.away_rating.toFixed(0)}</span>
      </div>
      <div className="divider">
        {isLive && (
          <span className="live-meta">
            {m.live_state!.label ?? `${periodLabel(m.live_state!.period)} · ${clockLabel(m.live_state!.time_remaining_s)}`}
          </span>
        )}
        {isFinal && <span className="final-tag">Final</span>}
        {!isLive && !isFinal && <span>@</span>}
      </div>
      <div className="team right">
        <TeamBadge team={m.home} color={homeColor} />
        <span className="abbr">{m.home}</span>
        <span className="rating">{m.home_rating.toFixed(0)}</span>
      </div>

      {isFinal && (
        <div className="live-score final">
          <span>{m.away_score}</span>
          <span className="dash">—</span>
          <span>{m.home_score}</span>
        </div>
      )}

      {isLive && (
        <div className="live-score">
          <span>{m.live_state!.away_score}</span>
          <span className="dash">—</span>
          <span>{m.live_state!.home_score}</span>
        </div>
      )}

      <div className="prob-bar pregame">
        <div className="away" style={{ width: `${awayPct}%` }} />
        <div className="home" style={{ width: `${homePct}%` }} />
      </div>
      <div className="prob-meta">
        <span>pre-game</span>
        <span>{pct(m.away_win_prob)}</span>
        <span>{pct(m.home_win_prob)}</span>
      </div>

      {m.live_wp && (
        <>
          <div className="prob-bar live">
            <div
              className="away"
              style={{ width: `${(1 - m.live_wp.home_win_prob) * 100}%` }}
            />
            <div
              className="home"
              style={{ width: `${m.live_wp.home_win_prob * 100}%` }}
            />
          </div>
          <div className="prob-meta">
            <span>
              live
              {m.live_wp.smoothed && <span className="smoothed-tag"> (n={m.live_wp.n_samples}, smoothed)</span>}
            </span>
            <span>{pct(1 - m.live_wp.home_win_prob)}</span>
            <span>{pct(m.live_wp.home_win_prob)}</span>
          </div>
        </>
      )}
      <span className="card-cta">Game analysis →</span>
    </div>
  );
}

export function TodaysGames({ data, league, sport, colorFor, periodLabel, footnote, emptyNote }: Props) {
  if (data.matchups.length === 0) {
    return (
      <div className="empty">
        No {league} games scheduled for {data.date}.{emptyNote ? ` ${emptyNote}` : ""}
      </div>
    );
  }
  return (
    <>
      <div className="games-grid">
        {data.matchups.map((m) => (
          <GameCard key={m.game_id} m={m} sport={sport} colorFor={colorFor} periodLabel={periodLabel} />
        ))}
      </div>
      {!data.frozen_params && (
        <div className="disclaimer">
          Pre-release: probabilities use the in-development rating engine, not the
          frozen-parameter model that the methodology requires for live games. Calibration
          is not yet evaluated.
        </div>
      )}
      {data.frozen_params && <div className="disclaimer ok">{footnote}</div>}
    </>
  );
}
