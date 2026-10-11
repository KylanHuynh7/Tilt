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


def live_block(g: dict) -> dict:
    return {"live_state": {
        "game_state": "LIVE", "period": g["period"] or 1, "time_remaining_s": int(g["clock_s"]),
        "home_score": g["home_score"] or 0, "away_score": g["away_score"] or 0,
    }}


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
            m.update(live_block(g))
        out.append(m)
    week = next((g["week"] for g in events if g["week"]), None)
    return {"date": f"Week {week}" if week else "", "frozen_params": True, "matchups": out}


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
