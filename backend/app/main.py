"""FastAPI app — Phase D wired to the frozen historical engine.

Endpoints:
  GET  /healthz                      liveness + cache status
  GET  /seasons                      list of all available seasons (sorted)
  GET  /ratings/current              current ratings for the 32 active franchises
  GET  /ratings/history/{season}     trajectory for one season (any of 108)
  GET  /games/today                  today's matchups with pre-game probabilities
  GET  /calibration/current          §6 test-set metrics + calibration buckets
  POST /admin/refresh                re-ingest current season + rebuild cache
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from dataclasses import asdict

from . import cup_simulator, engine, historical, live_wp, standings
from .franchises import current_code
from .seasons import parse as parse_season
from .teams import TEAMS

CURRENT_SEASON_ID = 20252026  # the in-progress season the Cup sim operates on
DEFAULT_CUP_SIMS = 10_000

# Cached Cup-sim result; rebuilt on /admin/refresh and at first request.
_cup_result: cup_simulator.CupSimResult | None = None

# Cached live-WP model; loaded lazily on first request.
_wp_model: live_wp.WPModel | None = None


def _wp_model_or_503() -> live_wp.WPModel:
    global _wp_model
    if _wp_model is not None:
        return _wp_model
    try:
        _wp_model = live_wp.load_artifact()
        return _wp_model
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "no live-WP artifact yet; "
                "run `uv run python -m scripts.build_live_wp` after ingesting PBP"
            ),
        ) from exc

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "test_evaluation.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the cache at startup. Cheap (~1-2s) and avoids per-request hits.
    try:
        historical.initialize()
    except FileNotFoundError as exc:
        # No frozen artifact yet — surface a clear error in the logs but let
        # the app start so error responses can guide the operator.
        print(f"[startup] {exc}", file=sys.stderr)
    yield


app = FastAPI(
    title="Tilt — NHL Rating System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---- Helpers -------------------------------------------------------------------

def _cache_or_503():
    try:
        return historical.get_cache()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---- Endpoints -----------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    try:
        cache = historical.get_cache()
        return {
            "ok": True,
            "seasons_in_cache": len(cache.seasons_replayed),
            "last_built_at": cache.last_built_at.isoformat() if cache.last_built_at else None,
            "frozen_params": {
                "k_regular": cache.params.k_regular,
                "k_playoff": cache.params.k_playoff,
                "decay_carry": cache.params.decay_carry,
                "frozen_at": cache.params.frozen_at,
                "methodology_version": cache.params.methodology_version,
            },
        }
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/seasons")
async def list_seasons():
    cache = _cache_or_503()
    ids = sorted(cache.trajectories.keys(), reverse=True)
    return {
        "count": len(ids),
        "seasons": [
            {
                "season_id": sid,
                "label": parse_season(sid).label,
                "pre_1967": historical.is_pre_1967(sid),
            }
            for sid in ids
        ],
    }


@app.get("/ratings/current")
async def ratings_current():
    cache = _cache_or_503()
    rows = []
    for code, fid, rating in historical.current_active_ratings_with_codes():
        rows.append({
            "team": code,
            "franchise_id": fid,
            "name": TEAMS.get(code, fid),
            "rating": round(rating, 2),
        })
    return {
        "as_of": cache.last_built_at.isoformat() if cache.last_built_at else None,
        "teams": rows,
    }


@app.get("/ratings/history/{season}")
async def ratings_history(season: int):
    cache = _cache_or_503()
    if season not in cache.trajectories:
        raise HTTPException(
            status_code=404,
            detail=f"season {season} not in cache; available seasons via GET /seasons",
        )
    parsed = parse_season(season)
    bucket = cache.trajectories[season]

    teams = []
    for fid, points in bucket.items():
        code = current_code(fid)
        teams.append({
            "franchise_id": fid,
            "team": code,  # None for defunct franchises
            "name": TEAMS.get(code, fid) if code else fid.replace("_", " ").title(),
            "is_defunct": code is None,
            "points": [
                {"game_id": p.game_id, "date": p.date, "rating": round(p.rating, 2)}
                for p in points
            ],
        })
    return {
        "season": season,
        "label": parsed.label,
        "pre_1967": parsed.is_pre_1967,
        "n_franchises": len(teams),
        "teams": teams,
    }


@app.get("/games/today")
async def games_today():
    _cache_or_503()  # ensure cache exists; fail clearly if not
    matchups = await engine.todays_matchups()
    return {
        "date": date.today().isoformat(),
        "frozen_params": True,  # v1 milestone-2 complete; frozen artifact in use
        "matchups": matchups,
    }


@app.get("/calibration/current")
async def calibration_current():
    if not RESULTS_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "no test-evaluation results yet; "
                "run `uv run python -m scripts.evaluate --confirm`"
            ),
        )
    return json.loads(RESULTS_PATH.read_text())


@app.get("/simulation/cup")
async def simulation_cup(n: int | None = None, refresh: bool = False):
    """Monte Carlo Cup-win probabilities per §14.

    Cached across requests. Pass `?refresh=true` to force a fresh run, or
    `?n=N` to override the default 10,000 simulations.
    """
    global _cup_result
    cache = _cache_or_503()
    n_sims = int(n) if n else DEFAULT_CUP_SIMS
    needs_fresh = (
        refresh
        or _cup_result is None
        or _cup_result.n_simulations != n_sims
    )
    if needs_fresh:
        state = standings.derive_playoff_state(CURRENT_SEASON_ID)
        stand = standings.compute_standings(CURRENT_SEASON_ID)
        ratings_by_code = cup_simulator.ratings_by_team_code(
            historical.current_active_ratings_with_codes()
        )
        _cup_result = cup_simulator.simulate_cup(
            state, stand, ratings_by_code,
            k_playoff=cache.params.k_playoff,
            home_bump=cache.params.home_bump,
            n_simulations=n_sims,
        )

    # Pretty-format the response: include rating and franchise name per team.
    by_code_rating = cup_simulator.ratings_by_team_code(
        historical.current_active_ratings_with_codes()
    )
    teams_payload = []
    for code, prob in sorted(
        _cup_result.cup_probabilities.items(),
        key=lambda kv: -kv[1],
    ):
        teams_payload.append({
            "team": code,
            "name": TEAMS.get(code, code),
            "rating": round(by_code_rating.get(code, 1500.0), 2),
            "cup_probability": prob,
            "alive": code in _cup_result.alive,
        })
    return {
        "season": CURRENT_SEASON_ID,
        "simulated_at": _cup_result.simulated_at,
        "n_simulations": _cup_result.n_simulations,
        "wall_seconds": _cup_result.wall_seconds,
        "current_round": _cup_result.state_round,
        "in_progress_series": _cup_result.in_progress_series,
        "teams": teams_payload,
        "frozen_params": {
            "k_playoff": cache.params.k_playoff,
            "home_bump": cache.params.home_bump,
            "methodology_version": cache.params.methodology_version,
        },
    }


@app.get("/wp")
async def wp(period: int, time_remaining_s: int, score_diff: int):
    """v2.2 §15 — empirical state-aware home win probability.

    Stateless lookup. The caller knows the game state; the endpoint returns
    P(home wins | state) from the lookup table.
    """
    model = _wp_model_or_503()
    if period not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="period must be 1, 2, 3, or 4")
    if time_remaining_s < 0:
        raise HTTPException(status_code=400, detail="time_remaining_s must be >= 0")
    r = live_wp.query(
        model, period=period, time_remaining_s=time_remaining_s, score_diff=score_diff,
    )
    return {
        "home_win_prob": r.home_win_prob,
        "n_samples": r.n,
        "smoothed": r.smoothed,
        "bin": {
            "period": r.bin.period,
            "mins_remaining": r.bin.mins_remaining,
            "score_diff": r.bin.score_diff,
        },
        "model": {
            "methodology_version": "2.2",
            "n_games": model.n_games,
            "n_samples": model.n_samples,
            "training_seasons": model.training_seasons,
        },
    }


@app.post("/admin/refresh")
async def admin_refresh():
    global _cup_result
    status = await engine.refresh_current_season()
    _cup_result = None  # force the Cup sim to rebuild next request
    return {"ok": True, **status}
