"""College football endpoints under /cfb (methodology/CFB.md §9). Same response
shapes as the other sports. FBS teams by ESPN id; FCS opponents use the pooled
rating. Frozen-parameter invariant applies to every probability served.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from ..core import detail as core_detail, lineups, live_history, rosters
from . import backtest, pipeline, ratings
from .ratings import FCS

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "artifacts" / "cfb" / "frozen_params.json"
RESULTS = ROOT / "results" / "cfb" / "test_evaluation.json"
SCOREBOARD = pipeline.SCOREBOARD

router = APIRouter(prefix="/cfb", tags=["cfb"])


def _lum(hex_color: str | None) -> float:
    h = (hex_color or "888888").lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 0.5
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def display_color(primary: str | None, alt: str | None) -> str:
    """ESPN's team color, or its alternate when the primary is too dark for
    the dark UI (NHL §13.I reasoning)."""
    p, a = (primary or "888888").lstrip("#"), (alt or "").lstrip("#")
    if _lum(p) < 0.18 and a and _lum(a) > _lum(p) and a.lower() not in ("ffffff", "000000"):
        return f"#{a}"
    if _lum(p) < 0.12:
        return "#9aa3ad"
    return f"#{p}"


@dataclass
class Cache:
    params: ratings.Params
    seasons: list[int]
    trajectories: dict
    names: dict[int, tuple[str, str]]     # id → (abbr, name)
    colors: dict[int, str]
    champions: dict[int, int]
    current: dict
    fbs_now: set[int]
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_cache: Cache | None = None


def load_params() -> ratings.Params:
    if not ARTIFACT.exists():
        raise HTTPException(503, "CFB model not frozen; run `uv run python -m scripts.cfb_freeze`")
    w = json.loads(ARTIFACT.read_text())["winner"]
    return ratings.Params(**{f.name: w[f.name] for f in dataclasses.fields(ratings.Params)})


def _build() -> Cache:
    params = load_params()
    seasons = [s for s in range(pipeline.FIRST_SEASON, pipeline.current_season() + 1)
               if (pipeline.GAMES_DIR / f"{s}.parquet").exists()]
    data = backtest.load(seasons)
    res = backtest.run(seasons, params, data=data, record_trajectories=True)
    names, champs = {}, {}
    for s in seasons:
        games, _ = data[s]
        for g in games:
            names[g["home_id"]] = (g["home_abbr"], g["home_name"])
            names[g["away_id"]] = (g["away_abbr"], g["away_name"])
        post = [g for g in games if g["season_type"] == 3]
        if post and s < pipeline.current_season():
            last = post[-1]  # the national championship game is the final postseason game
            champs[s] = last["home_id"] if last["home_score"] > last["away_score"] else last["away_id"]
    return Cache(params, [s for s in seasons if data[s][0]], res.trajectories, names, _team_colors(), champs,
                 res.ratings, data[seasons[-1]][1])


def _team_colors() -> dict[int, str]:
    """ESPN team colors for every D-I program (one request), dark-UI adjusted.
    Missing colors fall back to the frontend default.
    """
    try:
        r = httpx.get("https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams",
                      params={"limit": 1000}, timeout=30)
        teams = [t["team"] for t in r.json()["sports"][0]["leagues"][0]["teams"]]
        return {int(t["id"]): display_color(t.get("color"), t.get("alternateColor")) for t in teams}
    except Exception:  # noqa: BLE001
        return {}


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = _build()
    return _cache


def _abbr(c: Cache, t) -> str:
    return c.names.get(t, (str(t), str(t)))[0] or str(t)


@router.get("/seasons")
async def seasons():
    c = get_cache()
    ids = sorted(c.seasons, reverse=True)
    return {"count": len(ids), "seasons": [{"season_id": s, "label": str(s), "pre_1967": False} for s in ids]}


@router.get("/ratings/current")
async def ratings_current():
    c = get_cache()
    rows = sorted(((t, r) for t, r in c.current.items() if t != FCS), key=lambda kv: -kv[1])
    return {"as_of": c.built_at.isoformat(), "fcs_pool_rating": round(c.current[FCS], 2),
            "teams": [{"team": _abbr(c, t), "franchise_id": str(t), "name": c.names.get(t, ("", ""))[1],
                       "rating": round(r, 2)} for t, r in rows]}


@router.get("/ratings/history/{season}")
async def ratings_history(season: int):
    c = get_cache()
    if season not in c.trajectories:
        raise HTTPException(404, f"season {season} not available; see GET /cfb/seasons")
    champ = c.champions.get(season)
    # 130+ lines are unreadable; the chart shows the season's top 25 at its end plus the champion.
    pts = c.trajectories[season]
    final = sorted(pts, key=lambda t: -pts[t][-1].rating)
    keep = set(final[:25]) | ({champ} if champ else set())
    return {
        "season": season, "label": str(season), "pre_1967": False, "n_franchises": len(pts),
        "shown": "top 25 by end-of-season rating (+ champion)",
        "cup_winner": _abbr(c, champ) if champ else None, "cup_winner_franchise": str(champ) if champ else None,
        "teams": [{"franchise_id": str(t), "team": _abbr(c, t), "name": c.names.get(t, ("", ""))[1],
                   "is_defunct": False, "color": c.colors.get(t),
                   "points": [{"game_id": p.game_id or None, "date": p.game_date, "rating": round(p.rating, 2)}
                              for p in pts[t]]} for t in final if t in keep],
    }


def live_block(g: dict, p_home: float | None = None, situation: dict | None = None) -> dict:
    """Live score/clock plus the v1.1 live WP (§12). College OT is untimed and
    the model was badly overconfident there in testing (§13), so OT carries
    an `unreliable` flag the UI surfaces.
    """
    from . import live_wp  # lazy: live_wp imports this module

    st = g["status"]
    period = int(st.get("period") or 1)
    clock = int(float(st.get("clock") or 0))
    home, away = int(g["_home"].get("score") or 0), int(g["_away"].get("score") or 0)
    out = {"live_state": {"game_state": "LIVE", "period": period, "time_remaining_s": clock,
                          "home_score": home, "away_score": away}}
    if p_home is not None and live_wp.ARTIFACT.exists():
        sit = situation or {}
        poss = str(sit.get("possession") or "")
        s = 1 if poss == str(g["_home"]["team"]["id"]) else (-1 if poss == str(g["_away"]["team"]["id"]) else 0)
        y = sit.get("yardsToEndzone") if isinstance(sit.get("yardsToEndzone"), int) else 50
        wp = live_wp.predict(live_wp.load(), pre_game_p=p_home, qtr=period, clock_s=clock, d=home - away, s=s, y=y)
        out["live_wp"] = {"home_win_prob": round(wp, 4), "n_samples": 0, "smoothed": False,
                          "unreliable": period > 4}
    return out


async def _week_raw() -> tuple[int | None, list[dict]]:
    """This week's FBS games with internal ids (not for the public response)."""
    c = get_cache()
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-cfb"}) as client:
        try:
            r = await client.get(SCOREBOARD, params={"groups": 80, "limit": 400}, timeout=30)
            r.raise_for_status()
            events = r.json().get("events") or []
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"ESPN CFB scoreboard unavailable: {exc}") from exc
    out = []
    week = None
    for e in events:
        if not e:
            continue
        comp = e["competitions"][0]
        sides = {x["homeAway"]: x for x in comp["competitors"]}
        h, a = sides["home"], sides["away"]
        hid, aid = int(h["team"]["id"]), int(a["team"]["id"])
        if hid not in c.fbs_now and aid not in c.fbs_now:
            continue
        kh = hid if hid in c.fbs_now else FCS
        ka = aid if aid in c.fbs_now else FCS
        rh, ra = c.current.get(kh, c.current[FCS]), c.current.get(ka, c.current[FCS])
        neutral = bool(comp.get("neutralSite"))
        p = ratings.win_probability(rh, ra, home_bump=c.params.home_bump, neutral=neutral)
        stype = comp["status"]["type"]
        state = "FINAL" if stype.get("completed") else ("LIVE" if stype.get("state") == "in" else "PRE")
        week = week or (e.get("week") or {}).get("number")
        m = {
            "game_id": int(e["id"]), "game_date": (e.get("date") or "")[:10], "state": state,
            "home": h["team"].get("abbreviation"), "away": a["team"].get("abbreviation"),
            "home_name": h["team"].get("displayName"), "away_name": a["team"].get("displayName"),
            "home_color": display_color(h["team"].get("color"), h["team"].get("alternateColor")),
            "away_color": display_color(a["team"].get("color"), a["team"].get("alternateColor")),
            "neutral": neutral, "home_rating": round(rh, 2), "away_rating": round(ra, 2),
            "home_win_prob": round(p, 4), "away_win_prob": round(1 - p, 4),
            "home_score": int(h["score"]) if h.get("score") not in (None, "") else None,
            "away_score": int(a["score"]) if a.get("score") not in (None, "") else None,
            "fcs_opponent": FCS in (kh, ka),
            "_ids": (hid, aid),
        }
        if state == "LIVE":
            m.update(live_block({"status": comp["status"], "_home": h, "_away": a}, p, comp.get("situation")))
        out.append(m)
    live_history.record_matchups("cfb", out)
    return week, out


@router.get("/games/today")
async def games_this_week():
    week, out = await _week_raw()
    clean = [{k: v for k, v in m.items() if k != "_ids"} for m in out]
    return {"date": f"Week {week}" if week else "", "frozen_params": True, "matchups": clean}


def _normalized_games(c: Cache, seasons) -> list[dict]:
    out = []
    for s in seasons:
        for g in pipeline.completed_games(pipeline.read_games(s)):
            out.append({"date": g["game_date"], "season_label": str(s), "home": g["home_abbr"], "away": g["away_abbr"],
                        "home_score": g["home_score"], "away_score": g["away_score"]})
    return out


@router.get("/games/{game_id}/detail")
async def game_detail(game_id: int):
    c = get_cache()
    _, raw_games = await _week_raw()
    raw = next((x for x in raw_games if x["game_id"] == game_id), None)
    if raw is None:
        raise HTTPException(404, f"game {game_id} is not on this week's FBS slate")
    m = {k: v for k, v in raw.items() if k != "_ids"}
    hid, aid = raw["_ids"]
    games = _normalized_games(c, c.seasons[-3:])
    latest = c.seasons[-1]

    def pts(tid):
        return [{"date": p.game_date, "rating": round(p.rating, 2)} for p in c.trajectories.get(latest, {}).get(tid, [])]

    buckets = json.loads(RESULTS.read_text())["overall"]["calibration_buckets"] if RESULTS.exists() else []
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-cfb"}) as client:
        rh = lineups.attach(await rosters.fetch(client, "football/college-football", str(hid)), None, "cfb")
        ra = lineups.attach(await rosters.fetch(client, "football/college-football", str(aid)), None, "cfb")
    side = lambda code, name, color, tid, r: {  # noqa: E731
        "code": code, "name": name, "color": color, "roster": r,
        "form": core_detail.team_form(code, games), "trend": core_detail.trend(pts(tid), str(latest))}
    return {
        "sport": "cfb", "game": m,
        "probability": core_detail.probability_breakdown(m["home_rating"], m["away_rating"], home_bump=c.params.home_bump,
                                                         neutral=m["neutral"], p_home=m["home_win_prob"]),
        "model": {"name": "CFB v1 Elo (pooled FCS)", "home_bump": c.params.home_bump, "k_regular": c.params.k_regular,
                  "mov": c.params.mov, "live": "CFB v1.1 in-game model (unreliable in overtime)"},
        "calibration_context": None if m["fcs_opponent"] else core_detail.calibration_context(
            m["home_win_prob"], buckets, "CFB one-shot test (2022–2025, FBS vs FBS)"),
        "home": side(m["home"], m["home_name"], m["home_color"], hid, rh),
        "away": side(m["away"], m["away_name"], m["away_color"], aid, ra),
        "head_to_head": core_detail.head_to_head(m["home"], m["away"], games),
        "live_history": live_history.get("cfb", game_id),
        "projections": None,
    }


@router.get("/calibration/current")
async def calibration_current():
    if not RESULTS.exists():
        raise HTTPException(503, "CFB test evaluation has not been run")
    r = json.loads(RESULTS.read_text())
    o, fp = r["overall"], r["frozen_params"]
    return {"evaluated_at": r["evaluated_at"], "methodology_version": r["methodology_version"], "frozen_at": r["frozen_at"],
            "frozen_params": {**fp, "k_playoff": fp["k_post"], "decay_carry": fp["carry"]},
            "test_seasons": r["test_seasons"], "n_test_predictions": o["n"],
            "metrics": {k: o[k] for k in ("model", "naive_baseline", "static_rating_baseline", "home_rate_baseline")},
            "per_season": {s: {k: b[k] for k in ("model", "naive_baseline", "static_rating_baseline")} for s, b in r["breakdowns"]["per_season"].items()},
            "calibration_buckets": o["calibration_buckets"], "section_6_targets": r["targets"],
            "verdict": r["verdict"], "flags": r["flags"], "breakdowns": r["breakdowns"],
            "fbs_vs_fcs": r["fbs_vs_fcs_reported_separately"]}


@router.post("/admin/refresh")
async def admin_refresh():
    global _cache
    r = await pipeline.ingest_season(pipeline.current_season())
    _cache = None
    return {"ok": True, **r}
