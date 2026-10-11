"""MLB endpoints under /mlb (methodology/MLB.md §9). Same response shapes as
the other sports, plus a pitching-matchup block on game detail.

All MLB facts come from the MLB Stats API (MLB Advanced Media, non-commercial
use, attributed in the UI): schedule, live linescore, rosters, injured list,
player stats and headshots. Probabilities come only from the frozen artifact.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException

from ..core import detail as core_detail, live_history
from . import backtest, pipeline, ratings
from .teams import TEAMS, is_franchise

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "artifacts" / "mlb" / "frozen_params.json"
RESULTS = ROOT / "results" / "mlb" / "test_evaluation.json"
API = pipeline.API
EASTERN = ZoneInfo("America/New_York")
HEADSHOT = "https://img.mlbstatic.com/mlb-photos/image/upload/w_213,q_auto:best/v1/people/{pid}/headshot/67/current"
ATTRIBUTION = "Data and photos: MLB Advanced Media (non-commercial use)."

router = APIRouter(prefix="/mlb", tags=["mlb"])


@dataclass
class Cache:
    params: ratings.Params
    seasons: list[int]
    trajectories: dict[int, dict[int, list[backtest.TrajectoryPoint]]]
    era_abbrs: dict[int, dict[int, str]]
    champions: dict[int, int]
    current: dict[int, float]
    pitcher_rgs: dict[int, float]
    team_rgs: dict[int, float]
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_cache: Cache | None = None


def load_params() -> ratings.Params:
    if not ARTIFACT.exists():
        raise HTTPException(503, "MLB model not frozen; run `uv run python -m scripts.mlb_freeze`")
    w = json.loads(ARTIFACT.read_text())["winner"]
    return ratings.Params(**{f.name: w[f.name] for f in dataclasses.fields(ratings.Params)})


def _build() -> Cache:
    params = load_params()
    seasons = list(range(pipeline.FIRST_SEASON, pipeline.current_season() + 1))
    seasons = [s for s in seasons if (pipeline.GAMES_DIR / f"{s}.parquet").exists()]
    data = backtest.load(seasons)
    res = backtest.run(seasons, params, data=data, record_trajectories=True)
    era, champs = {}, {}
    for s, sd in data.items():
        codes = {}
        for g in sd.games:
            codes[g["home_id"]] = g["home_abbr"] or TEAMS[g["home_id"]].abbr
            codes[g["away_id"]] = g["away_abbr"] or TEAMS[g["away_id"]].abbr
        era[s] = codes
        ws = [g for g in sd.games if g["game_type"] == "W"]
        if ws and s < pipeline.current_season():
            last = ws[-1]
            champs[s] = last["home_id"] if last["home_score"] > last["away_score"] else last["away_id"]
    return Cache(params, [s for s in seasons if data[s].games], res.trajectories, era, champs,
                 res.ratings, res.pitcher_rgs, res.team_rgs)


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = _build()
    return _cache


def _code(c: Cache, tid: int, season: int | None = None) -> str:
    return (c.era_abbrs.get(season, {}) if season else {}).get(tid) or TEAMS[tid].abbr


@router.get("/seasons")
async def seasons():
    c = get_cache()
    ids = sorted(c.seasons, reverse=True)
    return {"count": len(ids), "seasons": [{"season_id": s, "label": str(s), "pre_1967": False} for s in ids]}


@router.get("/ratings/current")
async def ratings_current():
    c = get_cache()
    return {"as_of": c.built_at.isoformat(), "teams": [
        {"team": TEAMS[t].abbr, "franchise_id": str(t), "name": TEAMS[t].name, "color": TEAMS[t].color,
         "rating": round(r, 2)} for t, r in sorted(c.current.items(), key=lambda kv: -kv[1])]}


@router.get("/ratings/history/{season}")
async def ratings_history(season: int):
    c = get_cache()
    if season not in c.trajectories:
        raise HTTPException(404, f"season {season} not available; see GET /mlb/seasons")
    champ = c.champions.get(season)
    return {
        "season": season, "label": str(season), "pre_1967": False,
        "n_franchises": len(c.trajectories[season]),
        "cup_winner": _code(c, champ, season) if champ else None,
        "cup_winner_franchise": str(champ) if champ else None,
        "teams": [{"franchise_id": str(t), "team": _code(c, t, season), "name": TEAMS[t].name,
                   "is_defunct": False, "color": TEAMS[t].color,
                   "points": [{"game_id": p.game_pk or None, "date": p.game_date.isoformat(),
                               "rating": round(p.rating, 2)} for p in pts]}
                  for t, pts in c.trajectories[season].items()],
    }


def pitching_side(c: Cache, team_id: int, pitcher: dict | None) -> dict:
    """Frozen-model pitcher adjustment for one side (A = c·(rGS_p − rGS_t))."""
    t_rgs = c.team_rgs.get(team_id)
    pid = (pitcher or {}).get("id")
    p_rgs = c.pitcher_rgs.get(pid) if pid else None
    adj = c.params.c * (p_rgs - t_rgs) if (p_rgs is not None and t_rgs is not None) else 0.0
    return {"id": pid, "name": (pitcher or {}).get("fullName"),
            "rolling_game_score": round(p_rgs, 1) if p_rgs is not None else None,
            "team_rolling_game_score": round(t_rgs, 1) if t_rgs is not None else None,
            "adjustment_elo": round(adj, 1), "first_start": pid is not None and p_rgs is None,
            "headshot": HEADSHOT.format(pid=pid) if pid else None}


def _live_label(ls: dict) -> str:
    half = ls.get("inningHalf") or ls.get("inningState") or ""
    inn = ls.get("currentInning")
    outs = ls.get("outs")
    return f"{half} {inn}" + (f" · {outs} out" if outs is not None else "") if inn else "Live"


async def _schedule_today(client: httpx.AsyncClient) -> list[dict]:
    today = datetime.now(EASTERN).date().isoformat()
    r = await client.get(f"{API}/schedule", params={"sportId": 1, "date": today, "gameType": pipeline.GAME_TYPES,
                                                    "hydrate": "probablePitcher,linescore"}, timeout=30)
    r.raise_for_status()
    return [g for d in r.json().get("dates", []) for g in d["games"]]


@router.get("/games/today")
async def games_today():
    c = get_cache()
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-mlb (non-commercial)"}) as client:
        try:
            games = await _schedule_today(client)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"MLB schedule unavailable: {exc}") from exc
    out = []
    for g in games:
        t = g["teams"]
        h, a = int(t["home"]["team"]["id"]), int(t["away"]["team"]["id"])
        if not (is_franchise(h) and is_franchise(a)):
            continue
        ph, pa = pitching_side(c, h, t["home"].get("probablePitcher")), pitching_side(c, a, t["away"].get("probablePitcher"))
        rh, ra = c.current.get(h, 1500.0), c.current.get(a, 1500.0)
        p = ratings.win_probability(rh, ra, a_home=ph["adjustment_elo"], a_away=pa["adjustment_elo"],
                                    home_bump=c.params.home_bump, neutral=False)
        st = g["status"]["abstractGameState"]
        state = "FINAL" if st == "Final" else ("LIVE" if st == "Live" else "PRE")
        m = {
            "game_id": g["gamePk"], "game_date": g.get("officialDate"), "state": state,
            "home": TEAMS[h].abbr, "away": TEAMS[a].abbr,
            "home_color": TEAMS[h].color, "away_color": TEAMS[a].color, "neutral": False,
            "home_rating": round(rh, 2), "away_rating": round(ra, 2),
            "home_win_prob": round(p, 4), "away_win_prob": round(1 - p, 4),
            "home_score": t["home"].get("score"), "away_score": t["away"].get("score"),
            "series": g.get("seriesDescription") if g.get("gameType") != "R" else None,
            "pitching": {"home": ph, "away": pa},
        }
        if state == "LIVE":
            ls = g.get("linescore") or {}
            m["live_state"] = {"game_state": "LIVE", "period": ls.get("currentInning") or 1, "time_remaining_s": 0,
                               "home_score": m["home_score"] or 0, "away_score": m["away_score"] or 0,
                               "label": _live_label(ls)}
        out.append(m)
    live_history.record_matchups("mlb", out)
    return {"date": datetime.now(EASTERN).date().isoformat(), "frozen_params": True, "matchups": out}


# ---- Rosters, player stats (MLB Stats API) ----------------------------------------

INJURED_PREFIXES = ("D", "IL")  # D7/D10/D15/D60 = injured list
GROUP_ORDER = ["Pitcher", "Two-Way Player", "Catcher", "Infielder", "Outfielder", "Hitter"]


async def roster(client: httpx.AsyncClient, team_id: int) -> dict:
    try:
        r = await client.get(f"{API}/teams/{team_id}/roster", params={"rosterType": "40Man"}, timeout=20)
        r.raise_for_status()
        rows = r.json().get("roster", [])
    except Exception:  # noqa: BLE001
        return {"loaded": False, "available": [], "ruled_out": [], "source": "MLB"}
    groups: dict[str, list] = {}
    ruled_out = []
    for x in rows:
        code = (x.get("status") or {}).get("code", "")
        p = {"id": str(x["person"]["id"]), "name": x["person"]["fullName"],
             "position": (x.get("position") or {}).get("abbreviation"),
             "jersey": x.get("jerseyNumber"), "headshot": HEADSHOT.format(pid=x["person"]["id"]), "status": None}
        if code == "A":
            groups.setdefault((x.get("position") or {}).get("type", "Other"), []).append(p)
        elif code.startswith(INJURED_PREFIXES):
            ruled_out.append({**p, "reason": (x.get("status") or {}).get("description", "Injured list")})
        # other statuses (optioned / minors / reassigned) aren't on the game-day squad
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    available = [{"group": g + "s" if not g.endswith("s") else g, "players": ps}
                 for g, ps in sorted(groups.items(), key=lambda kv: order.get(kv[0], 99))]
    return {"loaded": True, "available": available, "ruled_out": ruled_out, "source": "MLB"}


HITTING = [("G", "gamesPlayed"), ("AB", "atBats"), ("R", "runs"), ("H", "hits"), ("2B", "doubles"),
           ("3B", "triples"), ("HR", "homeRuns"), ("RBI", "rbi"), ("BB", "baseOnBalls"), ("SO", "strikeOuts"),
           ("SB", "stolenBases"), ("AVG", "avg"), ("OBP", "obp"), ("SLG", "slg"), ("OPS", "ops")]
PITCHING = [("G", "gamesPlayed"), ("GS", "gamesStarted"), ("W", "wins"), ("L", "losses"), ("SV", "saves"),
            ("IP", "inningsPitched"), ("H", "hits"), ("ER", "earnedRuns"), ("BB", "baseOnBalls"),
            ("SO", "strikeOuts"), ("HR", "homeRuns"), ("ERA", "era"), ("WHIP", "whip")]


def normalize_player(payload: dict) -> dict:
    person = (payload.get("people") or [{}])[0]
    by = {}
    for st in person.get("stats", []):
        by[(st["type"]["displayName"], st["group"]["displayName"])] = st.get("splits", [])
    cats = []
    for group, cols in (("pitching", PITCHING), ("hitting", HITTING)):
        years = by.get(("yearByYear", group), [])
        career = by.get(("career", group), [])
        if not years and not career:
            continue
        seasons = [{"season": s.get("season"), "year": int(s["season"]) if s.get("season") else None,
                    "team": TEAMS[s["team"]["id"]].abbr if s.get("team", {}).get("id") in TEAMS else (s.get("team") or {}).get("name"),
                    "stats": [str(s["stat"].get(k, "")) for _, k in cols]} for s in years]
        seasons.sort(key=lambda r: r["year"] or 0, reverse=True)
        cats.append({"name": group, "display_name": group.title(), "labels": [l for l, _ in cols],
                     "descriptions": [k for _, k in cols], "seasons": seasons,
                     "career": [str(career[0]["stat"].get(k, "")) for _, k in cols] if career else []})
    # Two-way players: show the role they're listed at first.
    if person.get("primaryPosition", {}).get("abbreviation") not in ("P", "TWP"):
        cats.sort(key=lambda c: c["name"] != "hitting")
    return {"categories": cats}


async def player_stats(athlete_id: str) -> dict:
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-mlb (non-commercial)"}) as client:
        r = await client.get(f"{API}/people/{athlete_id}",
                             params={"hydrate": "stats(group=[hitting,pitching],type=[yearByYear,career])"}, timeout=20)
        r.raise_for_status()
    return {"sport": "mlb", "athlete_id": athlete_id, **normalize_player(r.json()), "source": "MLB"}


@router.get("/games/{game_id}/detail")
async def game_detail(game_id: int):
    c = get_cache()
    today = await games_today()
    m = next((x for x in today["matchups"] if str(x["game_id"]) == str(game_id)), None)
    if m is None:
        raise HTTPException(404, f"game {game_id} is not on today's MLB slate")
    by_abbr = {t.abbr: t.mlb_id for t in TEAMS.values()}
    h_id, a_id = by_abbr[m["home"]], by_abbr[m["away"]]
    recent = c.seasons[-3:]
    games = []
    for s in recent:
        for g in backtest.load([s])[s].games:
            games.append({"date": g["game_date"].isoformat(), "season_label": str(s),
                          "home": TEAMS[g["home_id"]].abbr, "away": TEAMS[g["away_id"]].abbr,
                          "home_score": g["home_score"], "away_score": g["away_score"]})
    latest = c.seasons[-1]

    def pts(tid):
        return [{"date": p.game_date.isoformat(), "rating": round(p.rating, 2)}
                for p in c.trajectories.get(latest, {}).get(tid, [])]

    buckets = json.loads(RESULTS.read_text())["overall"]["calibration_buckets"] if RESULTS.exists() else []
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-mlb (non-commercial)"}) as client:
        rh, ra = await roster(client, h_id), await roster(client, a_id)
    side = lambda code, tid, r: {  # noqa: E731
        "code": code, "name": TEAMS[tid].name, "color": TEAMS[tid].color, "roster": r,
        "form": core_detail.team_form(code, games), "trend": core_detail.trend(pts(tid), str(latest))}
    breakdown = core_detail.probability_breakdown(
        m["home_rating"] + m["pitching"]["home"]["adjustment_elo"],
        m["away_rating"] + m["pitching"]["away"]["adjustment_elo"],
        home_bump=c.params.home_bump, neutral=False, p_home=m["home_win_prob"])
    return {
        "sport": "mlb", "game": m, "probability": breakdown,
        "pitching": m["pitching"],
        "model": {"name": "MLB v1 Elo + starting pitcher", "home_bump": c.params.home_bump,
                  "k_regular": c.params.k_regular, "mov": c.params.mov, "live": "not yet (MLB v1.1)"},
        "calibration_context": core_detail.calibration_context(m["home_win_prob"], buckets, "MLB one-shot test (2022–2025)"),
        "home": side(m["home"], h_id, rh), "away": side(m["away"], a_id, ra),
        "head_to_head": core_detail.head_to_head(m["home"], m["away"], games),
        "live_history": live_history.get("mlb", game_id),
        "attribution": ATTRIBUTION,
        "projections": None,
    }


@router.get("/calibration/current")
async def calibration_current():
    if not RESULTS.exists():
        raise HTTPException(503, "MLB test evaluation has not been run")
    r = json.loads(RESULTS.read_text())
    o, fp = r["overall"], r["frozen_params"]
    return {
        "evaluated_at": r["evaluated_at"], "methodology_version": r["methodology_version"],
        "frozen_at": r["frozen_at"], "frozen_params": {**fp, "decay_carry": fp["carry"]},
        "test_seasons": r["test_seasons"], "n_test_predictions": o["n"],
        "metrics": {k: o[k] for k in ("model", "naive_baseline", "static_rating_baseline", "home_rate_baseline")},
        "per_season": {s: {k: b[k] for k in ("model", "naive_baseline", "static_rating_baseline")}
                       for s, b in r["breakdowns"]["per_season"].items()},
        "calibration_buckets": o["calibration_buckets"], "section_6_targets": r["targets"],
        "verdict": r["verdict"], "flags": r["flags"], "breakdowns": r["breakdowns"],
    }


@router.post("/admin/refresh")
async def admin_refresh():
    global _cache
    r = await pipeline.ingest_season(pipeline.current_season())
    _cache = None
    return {"ok": True, "season": r["season"], "rows": r["rows"]}
