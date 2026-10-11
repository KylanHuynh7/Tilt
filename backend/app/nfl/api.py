"""NFL endpoints under /nfl (methodology/NFL.md §9). Same response shapes as
NHL/NBA so the shared frontend components render NFL too. Lazy cache;
frozen-parameter invariant applies to every probability served.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from ..core import detail as core_detail, live_history, rosters
from . import backtest, espn, pipeline, ratings
from .teams import TEAMS, franchise

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "artifacts" / "nfl" / "frozen_params.json"
RESULTS = ROOT / "results" / "nfl" / "test_evaluation.json"

router = APIRouter(prefix="/nfl", tags=["nfl"])


@dataclass
class Cache:
    params: ratings.Params
    seasons: list[int]
    trajectories: dict[int, dict[str, list[backtest.TrajectoryPoint]]]
    era_codes: dict[int, dict[str, str]]   # season → franchise → code used that season
    champions: dict[int, str]
    current: dict[str, float]
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_cache: Cache | None = None


def load_params() -> ratings.Params:
    if not ARTIFACT.exists():
        raise HTTPException(503, "NFL model not frozen; run `uv run python -m scripts.nfl_freeze`")
    w = json.loads(ARTIFACT.read_text())["winner"]
    return ratings.Params(k_regular=float(w["k_regular"]), k_playoff=float(w["k_playoff"]),
                          carry=float(w["carry"]), home_bump=float(w["home_bump"]), mov=bool(w["mov"]))


def _build() -> Cache:
    params = load_params()
    rows = backtest.rows_by_season()
    seasons = backtest.model_seasons(rows)
    res = backtest.run(seasons, params, rows=rows, record_trajectories=True)
    era: dict[int, dict[str, str]] = {}
    champs: dict[int, str] = {}
    for s, season_rows in rows.items():
        codes = {}
        for r in season_rows:
            for raw in (r["home_team"], r["away_team"]):
                codes[franchise(raw)] = raw
        era[s] = codes
        sb = [r for r in season_rows if r["game_type"] == "SB"]
        if sb:
            g = sb[-1]
            champs[s] = franchise(g["home_team"] if g["home_score"] > g["away_score"] else g["away_team"])
    return Cache(params, seasons, res.trajectories, era, champs, res.ratings)


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        try:
            _cache = _build()
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc
    return _cache


@router.get("/seasons")
async def seasons():
    c = get_cache()
    ids = sorted(c.seasons, reverse=True)
    return {"count": len(ids), "seasons": [{"season_id": s, "label": str(s), "pre_1967": False} for s in ids]}


@router.get("/ratings/current")
async def ratings_current():
    c = get_cache()
    return {
        "as_of": c.built_at.isoformat(),
        "teams": [{"team": t, "franchise_id": t, "name": TEAMS[t].name, "color": TEAMS[t].color,
                   "rating": round(r, 2)} for t, r in sorted(c.current.items(), key=lambda kv: -kv[1])],
    }


@router.get("/ratings/history/{season}")
async def ratings_history(season: int):
    c = get_cache()
    if season not in c.trajectories:
        raise HTTPException(404, f"season {season} not available; see GET /nfl/seasons")
    champ = c.champions.get(season)
    codes = c.era_codes.get(season, {})
    return {
        "season": season, "label": str(season), "pre_1967": False,
        "n_franchises": len(c.trajectories[season]),
        "cup_winner": codes.get(champ, champ) if champ else None,
        "cup_winner_franchise": champ,
        "teams": [{
            "franchise_id": t, "team": codes.get(t, t), "name": TEAMS[t].name,
            "is_defunct": False, "color": TEAMS[t].color,
            "points": [{"game_id": p.game_id or None, "date": p.gameday.isoformat(),
                        "rating": round(p.rating, 2)} for p in pts],
        } for t, pts in c.trajectories[season].items()],
    }


def live_block(g: dict, p_home: float | None = None) -> dict:
    """Live score/clock plus the v1.1 live WP (§12) when the artifact exists.
    ESPN's situation gives possession and field position; if it's missing
    (between plays, breaks) the possession terms are zero.
    """
    from . import live_wp  # lazy: live_wp imports this module

    period = g["period"] or 1
    home, away = g["home_score"] or 0, g["away_score"] or 0
    out = {"live_state": {
        "game_state": "LIVE", "period": period, "time_remaining_s": int(g["clock_s"]),
        "home_score": home, "away_score": away,
    }}
    if p_home is not None and live_wp.ARTIFACT.exists():
        s = {"home": 1, "away": -1}.get(g.get("possession"), 0)
        y = g.get("yardline_100") if g.get("yardline_100") is not None else 50
        wp = live_wp.predict(live_wp.load(), pre_game_p=p_home, qtr=period, qsr=g["clock_s"],
                             d=home - away, s=s, y=y)
        out["live_wp"] = {"home_win_prob": round(wp, 4), "n_samples": 0, "smoothed": False}
    return out


@router.get("/games/today")
async def games_this_week():
    """The current NFL week (ESPN's default scoreboard), not just today."""
    c = get_cache()
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-nfl"}) as client:
        try:
            events = await espn.fetch_current_week(client)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"ESPN NFL scoreboard unavailable: {exc}") from exc
    out = []
    for g in events:
        if g["home"] is None or g["away"] is None or g["season_type"] not in (2, 3):
            continue
        rh, ra = c.current.get(g["home"], 1500.0), c.current.get(g["away"], 1500.0)
        p = ratings.win_probability(rh, ra, home_bump=c.params.home_bump, neutral=g["neutral"])
        state = "FINAL" if g["completed"] else ("LIVE" if g["state"] == "in" else "PRE")
        m = {
            "game_id": g["game_id"], "game_date": (g["date"] or "")[:10], "state": state,
            "home": g["home"], "away": g["away"],
            "home_color": TEAMS[g["home"]].color, "away_color": TEAMS[g["away"]].color,
            "neutral": g["neutral"],
            "home_rating": round(rh, 2), "away_rating": round(ra, 2),
            "home_win_prob": round(p, 4), "away_win_prob": round(1 - p, 4),
            "home_score": g["home_score"], "away_score": g["away_score"],
        }
        if state == "LIVE":
            m.update(live_block(g, p))
        out.append(m)
    live_history.record_matchups("nfl", out)
    week = next((g["week"] for g in events if g["week"]), None)
    return {"date": f"Week {week}" if week else "", "frozen_params": True, "matchups": out}


ESPN_ROSTER_CODES = {"LA": "lar", "WAS": "wsh"}


def _normalized_games(seasons: list[int]) -> list[dict]:
    rows = backtest.rows_by_season()
    out = []
    for s in seasons:
        for r in rows.get(s, []):
            out.append({"date": r["gameday"].isoformat(), "season_label": str(s),
                        "home": franchise(r["home_team"]), "away": franchise(r["away_team"]),
                        "home_score": r["home_score"], "away_score": r["away_score"]})
    return out


@router.get("/games/{game_id}/detail")
async def game_detail(game_id: str):
    """Deeper look at one of this week's games (no new model; see core.detail)."""
    c = get_cache()
    week = await games_this_week()
    m = next((x for x in week["matchups"] if str(x["game_id"]) == str(game_id)), None)
    if m is None:
        raise HTTPException(404, f"game {game_id} is not on this week's NFL slate")
    games = _normalized_games(c.seasons[-3:])
    trend_season = c.seasons[-1]

    def pts(code):
        return [{"date": p.gameday.isoformat(), "rating": round(p.rating, 2)}
                for p in c.trajectories.get(trend_season, {}).get(code, [])]

    buckets = json.loads(RESULTS.read_text())["overall"]["calibration_buckets"] if RESULTS.exists() else []
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-nfl"}) as client:
        rh = await rosters.fetch(client, "football/nfl", ESPN_ROSTER_CODES.get(m["home"], m["home"].lower()))
        ra = await rosters.fetch(client, "football/nfl", ESPN_ROSTER_CODES.get(m["away"], m["away"].lower()))
    side = lambda code, color, roster: {  # noqa: E731
        "code": code, "name": TEAMS[code].name, "color": color, "roster": roster,
        "form": core_detail.team_form(code, games),
        "trend": core_detail.trend(pts(code), str(trend_season)),
    }
    return {
        "sport": "nfl", "game": m,
        "probability": core_detail.probability_breakdown(
            m["home_rating"], m["away_rating"], home_bump=c.params.home_bump,
            neutral=m["neutral"], p_home=m["home_win_prob"]),
        "model": {"name": "NFL v1 Elo", "home_bump": c.params.home_bump, "k_regular": c.params.k_regular,
                  "mov": c.params.mov, "live": "NFL v1.1 in-game model"},
        "calibration_context": core_detail.calibration_context(
            m["home_win_prob"], buckets, "NFL one-shot test (2022–2025)"),
        "home": side(m["home"], m["home_color"], rh),
        "away": side(m["away"], m["away_color"], ra),
        "head_to_head": core_detail.head_to_head(m["home"], m["away"], games),
        "live_history": live_history.get("nfl", game_id),
        "projections": None,  # no player model; QB effects aren't modeled (NFL §13)
    }


@router.get("/calibration/current")
async def calibration_current():
    if not RESULTS.exists():
        raise HTTPException(503, "NFL test evaluation has not been run")
    r = json.loads(RESULTS.read_text())
    o = r["overall"]
    fp = r["frozen_params"]
    return {
        "evaluated_at": r["evaluated_at"], "methodology_version": r["methodology_version"],
        "frozen_at": r["frozen_at"], "frozen_params": {**fp, "decay_carry": fp["carry"]},
        "test_seasons": r["test_seasons"], "n_test_predictions": o["n"],
        "metrics": {k: o[k] for k in ("model", "naive_baseline", "static_rating_baseline", "home_rate_baseline")},
        "per_season": {s: {k: b[k] for k in ("model", "naive_baseline", "static_rating_baseline")}
                       for s, b in r["breakdowns"]["per_season"].items()},
        "calibration_buckets": o["calibration_buckets"],
        "section_6_targets": r["targets"], "verdict": r["verdict"], "flags": r["flags"],
        "breakdowns": r["breakdowns"],
    }


@router.post("/admin/refresh")
async def admin_refresh():
    global _cache
    m = pipeline.ingest()
    _cache = None
    return {"ok": True, "rows": m["rows"], "seasons": len(get_cache().seasons)}
