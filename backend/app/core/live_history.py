"""In-memory live win-probability history per game, for the detail-page chart.

Every time a sport's today/this-week endpoint computes a live WP, it records
a point here. Memory only: a backend restart (or a free-tier sleep) clears
it, so the chart covers only the stretch of the game the server observed.
"""

from __future__ import annotations

from datetime import datetime, timezone

MAX_POINTS = 600
_history: dict[tuple[str, str], list[dict]] = {}


def record(sport: str, game_id, live_state: dict, home_wp: float) -> None:
    key = (sport, str(game_id))
    pts = _history.setdefault(key, [])
    point = {
        "t": datetime.now(timezone.utc).isoformat(),
        "period": live_state["period"],
        "time_remaining_s": live_state["time_remaining_s"],
        "home_score": live_state["home_score"],
        "away_score": live_state["away_score"],
        "home_wp": home_wp,
    }
    if pts and all(pts[-1][k] == point[k] for k in ("period", "time_remaining_s", "home_score", "away_score")):
        return  # same game state as the last poll
    pts.append(point)
    del pts[:-MAX_POINTS]


def get(sport: str, game_id) -> list[dict]:
    return list(_history.get((sport, str(game_id)), []))


def record_matchups(sport: str, matchups: list[dict]) -> None:
    for m in matchups:
        if m.get("live_state") and m.get("live_wp"):
            record(sport, m["game_id"], m["live_state"], m["live_wp"]["home_win_prob"])
