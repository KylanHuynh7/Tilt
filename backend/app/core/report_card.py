"""Cross-sport model report card: last slate, upsets, season-to-date record.

Every probability is the frozen model's PRE-GAME number from a walk-forward
replay (never refitted). Totals obey the §10 quarantine (author decision,
2026-10-12): seasons that are still a pending one-shot test show results and
upsets only, never aggregate accuracy, and postseason games are excluded from
every total (two postseason layers are under test).
"""

from __future__ import annotations

import time
from datetime import date

# Seasons that are a pending one-shot test: no aggregate accuracy until it runs.
QUARANTINE = {
    "nhl": {20262027: "NHL v3's one-time test runs after the 2027 Stanley Cup Final."},
    "mlb": {2026: "MLB v2's one-time test runs after the 2026 World Series."},
}
SPORTS = ("nhl", "nba", "nfl", "mlb", "cfb")
_cache: dict = {}


def _row(sport, d, home, away, p, home_won, post, gid):
    return {"sport": sport, "date": d.isoformat() if isinstance(d, date) else str(d), "home": home, "away": away,
            "p_home": round(p, 4), "home_won": home_won, "postseason": bool(post), "game_id": str(gid)}


def _nhl() -> tuple[int, list[dict]]:
    from .. import backtest, historical, roster_moves
    from ..franchises import current_code
    c = historical.get_cache()
    seasons = historical._ingested_season_ids()
    cur = seasons[-1]
    params = c.params.to_backtest_params()
    events = roster_moves.events_for(seasons) if params.boost_amount > 0 else None
    res = backtest.run(seasons, params=params, record_predictions_for={cur}, roster_events=events)
    rows = [_row("nhl", p.game_date, current_code(p.home_franchise), current_code(p.away_franchise), p.home_win_prob,
                 None if p.home_score == p.away_score else p.home_score > p.away_score, p.is_playoff, p.game_id)
            for p in res.predictions]
    return cur, rows


def _nba() -> tuple[int, list[dict]]:
    from ..nba import live_wp, pipeline
    from ..nba.teams import display_abbr
    cur = pipeline.current_season_id()
    try:
        preds = live_wp.pregame_predictions([cur]).values()
    except Exception:  # noqa: BLE001 — before opening night there is nothing to replay
        preds = []
    return cur, [_row("nba", p.game_date, display_abbr(p.home_team_id, cur), display_abbr(p.away_team_id, cur),
                      p.home_win_prob, p.home_won, p.season_type == 3, p.game_id) for p in preds]


def _nfl() -> tuple[int, list[dict]]:
    from ..nfl import api, live_wp
    cur = max(api.get_cache().seasons)
    preds = live_wp.pregame_predictions([cur]).values()
    return cur, [_row("nfl", p.gameday, p.home, p.away, p.home_win_prob,
                      None if p.outcome == 0.5 else p.outcome == 1.0, p.is_playoff, p.game_id) for p in preds]


def _mlb() -> tuple[int, list[dict]]:
    from ..mlb import api, live_wp
    from ..mlb.teams import TEAMS
    cur = max(api.get_cache().seasons)
    preds = live_wp.pregame([cur]).values()
    from . import postseason
    rows = []
    for p in preds:
        pub, _ = postseason.apply("mlb", p.home_win_prob, p.is_playoff)     # the probability the site published
        rows.append(_row("mlb", p.game_date, TEAMS[p.home_id].abbr, TEAMS[p.away_id].abbr, pub,
                         None if p.outcome == 0.5 else p.outcome == 1.0, p.is_playoff, p.game_pk))
    return cur, rows


def _cfb() -> tuple[int, list[dict]]:
    from ..cfb import api, live_wp
    c = api.get_cache()
    cur = max(c.seasons)
    from ..cfb import pipeline
    preds = live_wp.pregame([cur]).values()
    dates = {g["game_id"]: g["game_date"] for g in pipeline.read_games(cur)}
    name = lambda t: c.names.get(t, (str(t), str(t)))[0] if isinstance(t, int) else "FCS"   # noqa: E731
    return cur, [_row("cfb", dates.get(p.game_id, f"{cur}-W{p.week:02d}"), name(p.home), name(p.away), p.home_win_prob,
                      None if p.outcome == 0.5 else p.outcome == 1.0, p.postseason, p.game_id) for p in preds]


ADAPTERS = {"nhl": _nhl, "nba": _nba, "nfl": _nfl, "mlb": _mlb, "cfb": _cfb}


def _summary(rows: list[dict]) -> dict:
    import math
    scored = [r for r in rows if r["home_won"] is not None]
    if not scored:
        return {"n": 0}
    fav_right = sum((r["p_home"] >= 0.5) == r["home_won"] for r in scored)
    y = [1.0 if r["home_won"] else 0.0 for r in scored]
    p = [r["p_home"] for r in scored]
    brier = sum((a - b) ** 2 for a, b in zip(p, y)) / len(p)
    ll = -sum(b * math.log(max(a, 1e-12)) + (1 - b) * math.log(max(1 - a, 1e-12)) for a, b in zip(p, y)) / len(p)
    conf = [r for r in scored if max(r["p_home"], 1 - r["p_home"]) >= 0.65]
    conf_right = sum((r["p_home"] >= 0.5) == r["home_won"] for r in conf)
    return {"n": len(scored), "favorites_won": fav_right, "favorites_lost": len(scored) - fav_right,
            "brier": round(brier, 4), "log_loss": round(ll, 4), "coin_flip_log_loss": 0.6931,
            "confident_n": len(conf), "confident_right": conf_right,
            "confident_mean_p": round(sum(max(r["p_home"], 1 - r["p_home"]) for r in conf) / len(conf), 3) if conf else None}


def _upset(r: dict) -> dict:
    p_winner = r["p_home"] if r["home_won"] else 1 - r["p_home"]
    winner, loser = (r["home"], r["away"]) if r["home_won"] else (r["away"], r["home"])
    return {**r, "winner": winner, "loser": loser, "p_winner": round(p_winner, 4)}


def build() -> dict:
    out = {"generated_at": time.time(), "sports": {}}
    for s in SPORTS:
        try:
            season, rows = ADAPTERS[s]()
        except Exception as exc:  # noqa: BLE001 — one sport failing must not hide the others
            out["sports"][s] = {"error": repr(exc)[:200]}
            continue
        done = [r for r in rows if r["home_won"] is not None]
        last_date = max((r["date"] for r in done), default=None)
        last = [_upset(r) for r in done if r["date"] == last_date]
        quarantined = QUARANTINE.get(s, {}).get(season)
        regular = [r for r in done if not r["postseason"]]
        out["sports"][s] = {
            "season": season,
            "last_slate": {"date": last_date, "games": sorted(last, key=lambda u: u["p_winner"]),
                           "favorites_won": None if quarantined else sum(u["p_winner"] >= 0.5 for u in last)},
            "season_upsets": sorted((_upset(r) for r in done), key=lambda u: u["p_winner"])[:5],
            "season_summary": None if quarantined else _summary(regular),
            "quarantine_note": quarantined,
        }
    # Upset of the night: the least likely winner among the most recent two days of results.
    slates = [g for v in out["sports"].values() if "last_slate" in v for g in v["last_slate"]["games"]]
    latest = max((g["date"] for g in slates), default=None)
    if latest:
        from datetime import timedelta
        cutoff = (date.fromisoformat(latest) - timedelta(days=1)).isoformat()
        slates = [g for g in slates if g["date"] >= cutoff]
    out["upset_of_the_night"] = min(slates, key=lambda u: u["p_winner"]) if slates else None
    return out


def get(ttl: float = 1800) -> dict:
    hit = _cache.get("r")
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    r = build()
    _cache["r"] = (time.time(), r)
    return r
