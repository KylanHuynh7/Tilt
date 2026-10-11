import type { Matchup, TodayResponse } from "../api";
import { colorFor } from "../teamColors";

type Props = { data: TodayResponse };

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function periodLabel(period: number): string {
  if (period === 4) return "OT";
  return `P${period}`;
}

function clockLabel(seconds: number): string {
  const mm = Math.floor(seconds / 60).toString().padStart(2, "0");
  const ss = (seconds % 60).toString().padStart(2, "0");
  return `${mm}:${ss}`;
}

function TeamBadge({ team }: { team: string }) {
  return (
    <div className="team-badge" style={{ backgroundColor: colorFor(team) }}>
      {team}
    </div>
  );
}

function GameCard({ m }: { m: Matchup }) {
  const awayPct = m.away_win_prob * 100;
  const homePct = m.home_win_prob * 100;
  const isLive = !!m.live_state;
  return (
    <div className={`game ${isLive ? "live" : ""}`}>
      <div className="team">
        <TeamBadge team={m.away} />
        <span className="abbr">{m.away}</span>
        <span className="rating">{m.away_rating.toFixed(0)}</span>
      </div>
      <div className="divider">
        {isLive && (
          <span className="live-meta">
            {periodLabel(m.live_state!.period)} · {clockLabel(m.live_state!.time_remaining_s)}
          </span>
        )}
        {!isLive && <span>@</span>}
      </div>
      <div className="team right">
        <TeamBadge team={m.home} />
        <span className="abbr">{m.home}</span>
        <span className="rating">{m.home_rating.toFixed(0)}</span>
      </div>

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
    </div>
  );
}

export function TodaysGames({ data }: Props) {
  if (data.matchups.length === 0) {
    return <div className="empty">No NHL games scheduled for {data.date}.</div>;
  }
  return (
    <>
      <div className="games-grid">
        {data.matchups.map((m) => (
          <GameCard key={m.game_id} m={m} />
        ))}
      </div>
      {!data.frozen_params && (
        <div className="disclaimer">
          Pre-release: probabilities use the in-development rating engine, not the
          frozen-parameter model that the methodology requires for live games. Calibration
          is not yet evaluated.
        </div>
      )}
      {data.frozen_params && (
        <div className="disclaimer ok">
          Probabilities derived from the frozen v1 model. Live in-game updates are deferred to v2.
        </div>
      )}
    </>
  );
}
