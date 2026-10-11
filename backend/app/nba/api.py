"""NBA endpoints, mounted under /nba (methodology/NBA.md §3, §9 #6).

Response shapes deliberately match the NHL endpoints so the shared frontend
components render both sports. NBA-only additions (home-rate baseline,
§8 flags, breakdowns) ride along as extra fields.

The historical cache is built lazily on the first NBA request (NHL §13.K),
from the frozen artifact only — the frozen-parameter invariant (inherited
NHL §5 v1.1) applies to every probability served here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException

from ..core import detail as core_detail, live_history, rosters
from . import backtest, espn, live_wp, pipeline, ratings
from .teams import DISPLAY_COLORS, TEAMS, display_abbr, is_franchise

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "artifacts" / "nba" / "frozen_params.json"
RESULTS = ROOT / "results" / "nba" / "test_evaluation.json"
EASTERN = ZoneInfo("America/New_York")

router = APIRouter(prefix="/nba", tags=["nba"])


@dataclass
class Cache:
    params: ratings.Params
    artifact: dict
    seasons: list[int]                                   # seasons with ≥1 modeled game
    trajectories: dict[int, dict[int, list[backtest.TrajectoryPoint]]]
    abbrs: dict[int, dict[int, str]]                     # season → team → era code
    champions: dict[int, int]                            # season → franchise id
    current: dict[int, float]
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_cache: Cache | None = None


def season_label(sid: int) -> str:
    start = sid // 10000
    return f"{start}-{(start + 1) % 100:02d}"


def _load_params() -> tuple[ratings.Params, dict]:
    if not ARTIFACT.exists():
        raise HTTPException(503, "NBA model not frozen; run `uv run python -m scripts.nba_freeze`")
    a = json.loads(ARTIFACT.read_text())
    w = a["winner"]
    return ratings.Params(
        k_regular=float(w["k_regular"]), k_playoff=float(w["k_playoff"]),
        carry=float(w["carry"]), home_bump=float(w["home_bump"]), mov=bool(w["mov"]),
    ), a


def _build() -> Cache:
    params, artifact = _load_params()
    seasons = backtest.model_seasons()
    rows = {s: backtest.model_rows(s) for s in seasons}
    res = backtest.run(seasons, params, record_trajectories=True, rows_by_season=rows)

    abbrs: dict[int, dict[int, str]] = {}
    champions: dict[int, int] = {}
    in_progress = pipeline.current_season_id()
    for sid, season_rows in rows.items():
        codes: dict[int, str] = {}
        for r in season_rows:  # chronological, so the last code seen wins
            codes[r["home_team_id"]] = display_abbr(r["home_team_id"], r["home_abbr"], sid)
            codes[r["away_team_id"]] = display_abbr(r["away_team_id"], r["away_abbr"], sid)
        abbrs[sid] = codes
        playoffs = [r for r in season_rows if r["season_type"] == pipeline.PLAYOFF]
        if playoffs and sid < in_progress:
            last = playoffs[-1]  # the deciding game of the Finals
            champions[sid] = (last["home_team_id"] if last["home_score"] > last["away_score"]
                              else last["away_team_id"])

    return Cache(
        params=params, artifact=artifact,
        seasons=[s for s in seasons if rows[s]],
        trajectories=res.trajectories, abbrs=abbrs, champions=champions,
        current=res.ratings,
    )


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        try:
            _cache = _build()
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc
    return _cache


def _team_code(c: Cache, tid: int, sid: int | None = None) -> str:
    if sid is not None and tid in c.abbrs.get(sid, {}):
        return c.abbrs[sid][tid]
    return TEAMS[tid].abbr


# ---- Endpoints -----------------------------------------------------------------

@router.get("/seasons")
async def seasons():
    c = get_cache()
    ids = sorted(c.seasons, reverse=True)
    return {
        "count": len(ids),
        "seasons": [{"season_id": s, "label": season_label(s), "pre_1967": False} for s in ids],
    }


@router.get("/ratings/current")
async def ratings_current():
    c = get_cache()
    rows = sorted(c.current.items(), key=lambda kv: -kv[1])
    return {
        "as_of": c.built_at.isoformat(),
        "teams": [
            {"team": TEAMS[tid].abbr, "franchise_id": str(tid), "name": TEAMS[tid].name,
             "color": DISPLAY_COLORS[tid], "rating": round(r, 2)}
            for tid, r in rows
        ],
    }


@router.get("/ratings/history/{season}")
async def ratings_history(season: int):
    c = get_cache()
    if season not in c.trajectories or season not in c.seasons:
        raise HTTPException(404, f"season {season} not available; see GET /nba/seasons")
    champ = c.champions.get(season)
    return {
        "season": season,
        "label": season_label(season),
        "pre_1967": False,
        "n_franchises": len(c.trajectories[season]),
        "cup_winner": _team_code(c, champ, season) if champ else None,
        "cup_winner_franchise": str(champ) if champ else None,
        "teams": [
            {
                "franchise_id": str(tid),
                "team": _team_code(c, tid, season),
                "name": TEAMS[tid].name,
                "is_defunct": False,
                "color": DISPLAY_COLORS[tid],
                "points": [
                    {"game_id": p.game_id or None, "date": p.game_date.isoformat(),
                     "rating": round(p.rating, 2)}
                    for p in pts
                ],
            }
            for tid, pts in c.trajectories[season].items()
        ],
    }


def live_block(r: dict, p_home: float) -> dict:
    """Live score/clock plus the v1.1 live WP (§12). The WP is omitted, not
    faked, if the live model artifact is missing.
    """
    period = r["n_periods"] or 1
    home, away = r["home_score"] or 0, r["away_score"] or 0
    out = {"live_state": {
        "game_state": "LIVE", "period": period, "time_remaining_s": int(r["clock_s"]),
        "home_score": home, "away_score": away,
    }}
    if live_wp.ARTIFACT.exists():
        wp = live_wp.predict(live_wp.load(), pre_game_p=p_home, period=period,
                             sec_left=r["clock_s"], d=home - away)
        out["live_wp"] = {"home_win_prob": round(wp, 4), "n_samples": 0, "smoothed": False}
    return out


def _today_eastern() -> date:
    return datetime.now(EASTERN).date()


@router.get("/games/today")
async def games_today():
    c = get_cache()
    today = _today_eastern()
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-nba"}) as client:
        try:
            events = await espn.fetch_day(client, today)
        except Exception as exc:  # noqa: BLE001 — upstream failure is a 502, not a crash
            raise HTTPException(502, f"ESPN scoreboard unavailable: {exc}") from exc

    matchups = []
    for r in events:
        h, a = r["home_team_id"], r["away_team_id"]
        if not (is_franchise(h) and is_franchise(a)):
            continue
        if r["season_type"] not in backtest.MODEL_SEASON_TYPES:
            continue  # preseason / exhibitions are not modeled
        rh = c.current.get(h, ratings.INITIAL_RATING)
        ra = c.current.get(a, ratings.INITIAL_RATING)
        neutral = espn.is_neutral(r)
        p_home = ratings.win_probability(rh, ra, home_bump=c.params.home_bump, neutral=neutral)
        state = "FINAL" if r["completed"] else ("LIVE" if r["state"] == "in" else "PRE")
        m = {
            "game_id": r["game_id"],
            "game_date": today.isoformat(),
            "state": state,
            "home": TEAMS[h].abbr,
            "away": TEAMS[a].abbr,
            "home_color": DISPLAY_COLORS[h],
            "away_color": DISPLAY_COLORS[a],
            "neutral": neutral,
            "home_rating": round(rh, 2),
            "away_rating": round(ra, 2),
            "home_win_prob": round(p_home, 4),
            "away_win_prob": round(1 - p_home, 4),
            "home_score": r["home_score"],
            "away_score": r["away_score"],
        }
        if state == "LIVE":
            m.update(live_block(r, p_home))
        matchups.append(m)
    live_history.record_matchups("nba", matchups)
    return {"date": today.isoformat(), "frozen_params": True, "matchups": matchups}


def _normalized_games(c: Cache, seasons: list[int]) -> list[dict]:
    out = []
    for sid in seasons:
        for r in backtest.model_rows(sid):
            out.append({"date": r["game_date"].isoformat(), "season_label": season_label(sid),
                        "home": TEAMS[r["home_team_id"]].abbr, "away": TEAMS[r["away_team_id"]].abbr,
                        "home_score": r["home_score"], "away_score": r["away_score"]})
    return out


@router.get("/games/{game_id}/detail")
async def game_detail(game_id: int):
    """Deeper look at one of today's games (no new model; see core.detail)."""
    c = get_cache()
    today = await games_today()
    m = next((x for x in today["matchups"] if str(x["game_id"]) == str(game_id)), None)
    if m is None:
        raise HTTPException(404, f"game {game_id} is not on today's NBA slate")
    by_abbr = {t.abbr: t.espn_id for t in TEAMS.values()}
    h_id, a_id = by_abbr[m["home"]], by_abbr[m["away"]]
    recent = c.seasons[-3:]
    games = _normalized_games(c, recent)
    trend_season = c.seasons[-1]

    def pts(tid):
        return [{"date": p.game_date.isoformat(), "rating": round(p.rating, 2)}
                for p in c.trajectories.get(trend_season, {}).get(tid, [])]

    buckets = json.loads(RESULTS.read_text())["overall"]["calibration_buckets"] if RESULTS.exists() else []
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-nba"}) as client:
        home_roster = await rosters.fetch(client, "basketball/nba", str(h_id))
        away_roster = await rosters.fetch(client, "basketball/nba", str(a_id))
    return {
        "sport": "nba", "game": m,
        "probability": core_detail.probability_breakdown(
            m["home_rating"], m["away_rating"], home_bump=c.params.home_bump,
            neutral=m["neutral"], p_home=m["home_win_prob"]),
        "model": {"name": "NBA v1 Elo", "home_bump": c.params.home_bump, "k_regular": c.params.k_regular,
                  "mov": c.params.mov, "live": "NBA v1.1 in-game model"},
        "calibration_context": core_detail.calibration_context(
            m["home_win_prob"], buckets, "NBA one-shot test (2024-25 + 2025-26)"),
        "home": {"code": m["home"], "name": TEAMS[h_id].name, "color": m["home_color"],
                 "form": core_detail.team_form(m["home"], games), "roster": home_roster,
                 "trend": core_detail.trend(pts(h_id), season_label(trend_season))},
        "away": {"code": m["away"], "name": TEAMS[a_id].name, "color": m["away_color"],
                 "form": core_detail.team_form(m["away"], games), "roster": away_roster,
                 "trend": core_detail.trend(pts(a_id), season_label(trend_season))},
        "head_to_head": core_detail.head_to_head(m["home"], m["away"], games),
        "live_history": live_history.get("nba", game_id),
        "projections": None,  # Tilt has no player model (see methodology/NBA.md §13)
    }


@router.get("/calibration/current")
async def calibration_current():
    """The one-shot test evaluation, reshaped to the NHL calibration contract."""
    if not RESULTS.exists():
        raise HTTPException(503, "NBA test evaluation has not been run")
    r = json.loads(RESULTS.read_text())
    o = r["overall"]
    fp = r["frozen_params"]
    return {
        "evaluated_at": r["evaluated_at"],
        "methodology_version": r["methodology_version"],
        "frozen_at": r["frozen_at"],
        "frozen_params": {**fp, "decay_carry": fp["carry"]},
        "test_seasons": r["test_seasons"],
        "n_test_predictions": o["n"],
        "metrics": {
            "model": o["model"],
            "naive_baseline": o["naive_baseline"],
            "static_rating_baseline": o["static_rating_baseline"],
            "home_rate_baseline": o["home_rate_baseline"],
        },
        "per_season": {
            s: {k: b[k] for k in ("model", "naive_baseline", "static_rating_baseline")}
            for s, b in r["breakdowns"]["per_season"].items()
        },
        "calibration_buckets": o["calibration_buckets"],
        "section_6_targets": r["targets"],
        "verdict": r["verdict"],
        "flags": r["flags"],
        "breakdowns": r["breakdowns"],
    }


@router.post("/admin/refresh")
async def admin_refresh():
    global _cache
    sid = pipeline.current_season_id()
    result = await pipeline.ingest_one(sid)
    _cache = None
    c = get_cache()
    return {"ok": True, "season": sid, "rows": result["rows"], "seasons": len(c.seasons)}
