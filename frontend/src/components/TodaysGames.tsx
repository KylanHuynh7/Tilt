import type { TodayResponse } from "../api";

type Props = { data: TodayResponse };

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function TodaysGames({ data }: Props) {
  if (data.matchups.length === 0) {
    return <div className="empty">No NHL games scheduled for {data.date}.</div>;
  }
  return (
    <>
      <div className="games-grid">
        {data.matchups.map((m) => {
          const awayPct = m.away_win_prob * 100;
          const homePct = m.home_win_prob * 100;
          return (
            <div key={m.game_id} className="game">
              <div className="team">
                <span className="abbr">{m.away}</span>
                <span className="rating">{m.away_rating.toFixed(0)}</span>
              </div>
              <div className="divider">@</div>
              <div className="team right">
                <span className="abbr">{m.home}</span>
                <span className="rating">{m.home_rating.toFixed(0)}</span>
              </div>
              <div className="prob-bar">
                <div className="away" style={{ width: `${awayPct}%` }} />
                <div className="home" style={{ width: `${homePct}%` }} />
              </div>
              <div className="prob-meta">
                <span>{pct(m.away_win_prob)}</span>
                <span>{pct(m.home_win_prob)}</span>
              </div>
            </div>
          );
        })}
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
