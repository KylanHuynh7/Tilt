"""Play page: matchup machine, beat-the-model slate and results, watch tonight /
rewatch. Everything here reuses the frozen models; nothing is fitted, tuned
or evaluated, and nothing is stored server-side (picks live in the browser).
"""

from __future__ import annotations

import asyncio
import statistics
import time
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/play", tags=["play"])
SPORTS = ("nhl", "nba", "nfl", "mlb", "cfb")


# ---- Matchup machine ----------------------------------------------------------------

def _season_label(sport: str, s: int) -> str:
    return f"{s // 10000}-{str(s % 100).zfill(2)}" if s > 9999 else str(s)


def _teams_and_seasons(sport: str) -> dict:
    """{teams: [{code, name, color}], seasons: [...], ratings: {(code, season|None): rating}, bump, neutral_ok}"""
    if sport == "nhl":
        from . import historical
        from . import ratings as nhl_ratings
        from .teams import TEAMS
        c = historical.get_cache()
        active = historical.current_active_ratings_with_codes()
        fid_by_code = {code: fid for code, fid, _ in active}
        teams = [{"code": code, "name": TEAMS.get(code, code), "color": None} for code, _, _ in active]
        def rating(code, season):
            if season is None:
                return next(r for cd, _, r in active if cd == code)
            pts = c.trajectories.get(season, {}).get(fid_by_code[code])
            return pts[-1].rating if pts else None
        return {"teams": teams, "seasons": sorted(s for s in c.trajectories if s >= 19671968), "rating": rating,
                "p": lambda rh, ra, neutral: nhl_ratings.win_probability(
                    rh, ra, home_bump=0.0 if neutral else c.params.home_bump)}
    if sport == "nba":
        from .nba import api, ratings
        from .nba.teams import DISPLAY_COLORS, TEAMS
        c = api.get_cache()
        teams = [{"code": TEAMS[t].abbr, "id": t, "name": TEAMS[t].name, "color": DISPLAY_COLORS.get(t)}
                 for t in sorted(c.current)]
        ids = {x["code"]: x["id"] for x in teams}
        def rating(code, season):
            if season is None:
                return c.current[ids[code]]
            pts = c.trajectories.get(season, {}).get(ids[code])
            return pts[-1].rating if pts else None
        return {"teams": teams, "seasons": sorted(s for s, v in c.trajectories.items() if any(v.values())), "rating": rating,
                "p": lambda rh, ra, neutral: ratings.win_probability(rh, ra, home_bump=c.params.home_bump, neutral=neutral)}
    if sport == "nfl":
        from .nfl import api, ratings
        from .nfl.teams import TEAMS
        c = api.get_cache()
        teams = [{"code": t, "name": TEAMS[t].name if t in TEAMS else t, "color": TEAMS[t].color if t in TEAMS else None}
                 for t in sorted(c.current)]
        def rating(code, season):
            if season is None:
                return c.current[code]
            pts = c.trajectories.get(season, {}).get(code)
            return pts[-1].rating if pts else None
        return {"teams": teams, "seasons": sorted(c.trajectories), "rating": rating,
                "p": lambda rh, ra, neutral: ratings.win_probability(rh, ra, home_bump=c.params.home_bump, neutral=neutral)}
    if sport == "mlb":
        from .mlb import api, ratings
        from .mlb.teams import TEAMS
        c = api.get_cache()
        teams = [{"code": TEAMS[t].abbr, "id": t, "name": TEAMS[t].name, "color": TEAMS[t].color}
                 for t in sorted(c.current) if t in TEAMS]
        ids = {x["code"]: x["id"] for x in teams}
        def rating(code, season):
            if season is None:
                return c.current[ids[code]]
            pts = c.trajectories.get(season, {}).get(ids[code])
            return pts[-1].rating if pts else None
        return {"teams": teams, "seasons": sorted(c.trajectories), "rating": rating,
                "p": lambda rh, ra, neutral: ratings.win_probability(rh, ra, home_bump=c.params.home_bump, neutral=neutral)}
    if sport == "cfb":
        from .cfb import api, ratings
        c = api.get_cache()
        teams = [{"code": c.names[t][0], "id": t, "name": c.names[t][1], "color": c.colors.get(t)}
                 for t in sorted(c.fbs_now, key=lambda t: c.names.get(t, ("", ""))[1]) if t in c.names]
        ids = {x["code"]: x["id"] for x in teams}
        def rating(code, season):
            if season is None:
                return c.current.get(ids[code])
            pts = c.trajectories.get(season, {}).get(ids[code])
            return pts[-1].rating if pts else None
        return {"teams": teams, "seasons": sorted(c.trajectories), "rating": rating,
                "p": lambda rh, ra, neutral: ratings.win_probability(rh, ra, home_bump=c.params.home_bump, neutral=neutral)}
    raise HTTPException(404, f"unknown sport {sport}")


@router.get("/teams")
async def teams(sport: str):
    t = _teams_and_seasons(sport)
    return {"sport": sport, "teams": sorted(t["teams"], key=lambda x: x["name"]),
            "seasons": [{"id": s, "label": _season_label(sport, s)} for s in reversed(t["seasons"])]}


@router.get("/matchup")
async def matchup(sport: str, home: str, away: str, neutral: bool = False,
                  home_season: int | None = None, away_season: int | None = None):
    t = _teams_and_seasons(sport)
    codes = {x["code"] for x in t["teams"]}
    if home not in codes or away not in codes:
        raise HTTPException(404, "unknown team")
    rh, ra = t["rating"](home, home_season), t["rating"](away, away_season)
    if rh is None or ra is None:
        raise HTTPException(404, "that team has no rating for that season")
    p = t["p"](rh, ra, neutral)
    cross_era = (home_season or 0) != (away_season or 0)
    return {"sport": sport, "home": home, "away": away, "neutral": neutral,
            "home_season": home_season, "away_season": away_season,
            "home_rating": round(rh, 1), "away_rating": round(ra, 1), "home_win_prob": round(p, 4),
            "note": ("For fun: ratings are relative to each team's own season, so a cross-era matchup compares how "
                     "dominant each team was in its time, not who'd actually win.") if cross_era else
                    "Frozen model, current ratings; same formula as the game cards (no starting pitchers or lineups)."}


# ---- Beat the model: today's slate + results --------------------------------------------

async def _slate_rows() -> list[dict]:
    from . import main
    from .cfb import api as cfb_api
    from .mlb import api as mlb_api
    from .nba import api as nba_api
    from .nfl import api as nfl_api
    calls = {"nhl": main.games_today, "nba": nba_api.games_today, "nfl": nfl_api.games_this_week,
             "mlb": mlb_api.games_today, "cfb": cfb_api.games_this_week}
    results = await asyncio.gather(*[f() for f in calls.values()], return_exceptions=True)
    rows = []
    for sport, r in zip(calls, results):
        if isinstance(r, Exception):
            continue
        for m in r.get("matchups", []):
            state = {"OFF": "FINAL", "CRIT": "LIVE", "FUT": "PRE"}.get(m.get("state"), m.get("state"))
            rows.append({"sport": sport, "game_id": str(m["game_id"]), "date": m.get("game_date"), "state": state,
                         "home": m["home"], "away": m["away"], "home_color": m.get("home_color"),
                         "away_color": m.get("away_color"), "home_win_prob": m["home_win_prob"],
                         "home_rating": m.get("home_rating"), "away_rating": m.get("away_rating"),
                         "home_score": m.get("home_score"), "away_score": m.get("away_score")})
    return rows


def _watch_scores(rows: list[dict]) -> None:
    """Fox-style 'game of the week' before kickoff: good teams × a close game.
    quality = how far the pair's mean rating sits above its league's mean (z-score),
    closeness = 1 − |2p − 1|. Scored within each sport, so sports compare fairly."""
    by_sport: dict[str, list[dict]] = {}
    for r in rows:
        by_sport.setdefault(r["sport"], []).append(r)
    for sport, rs in by_sport.items():
        try:
            cur = list(_teams_and_seasons(sport)["teams"])
            vals = [v for v in (_teams_and_seasons(sport)["rating"](t["code"], None) for t in cur) if v is not None]
            mu, sd = statistics.mean(vals), statistics.pstdev(vals) or 1.0
        except Exception:  # noqa: BLE001
            mu, sd = 1500.0, 100.0
        for r in rs:
            if r.get("home_rating") is None:
                r["watch_score"] = None
                continue
            z = ((r["home_rating"] + r["away_rating"]) / 2 - mu) / sd
            closeness = 1 - abs(2 * r["home_win_prob"] - 1)
            r["watch_score"] = round(closeness * (1 + max(z, -0.9)), 4)
            r["watch_strong"] = min(r["home_rating"], r["away_rating"]) > mu


_slate_cache: tuple[float, list[dict]] | None = None


@router.get("/slate")
async def slate():
    """Today's games across sports (NFL/CFB: this week). Picks are stored in the browser."""
    global _slate_cache
    if _slate_cache and time.time() - _slate_cache[0] < 120:
        rows = _slate_cache[1]
    else:
        rows = await _slate_rows()
        _watch_scores(rows)
        _slate_cache = (time.time(), rows)
    # Watch tonight = the best game on the NEXT day with unplayed games (NFL / college
    # lists cover the whole week); also the best game per sport on that day.
    pre = [r for r in rows if r["state"] == "PRE" and r.get("watch_score") is not None and r.get("date")]
    day = min((r["date"] for r in pre), default=None)
    today = [r for r in pre if r["date"] == day]
    watch = max(today, key=lambda r: r["watch_score"]) if today else None
    per_sport = {}
    for r in today:
        if r["sport"] not in per_sport or r["watch_score"] > per_sport[r["sport"]]["watch_score"]:
            per_sport[r["sport"]] = r
    return {"games": rows, "watch_day": day, "watch_tonight": watch, "watch_by_sport": per_sport}


_finals: dict[str, dict] = {}


async def _final(client: httpx.AsyncClient, sport: str, gid: str) -> dict | None:
    key = f"{sport}:{gid}"
    if key in _finals:
        return _finals[key]
    try:
        if sport == "nhl":
            d = (await client.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/landing", timeout=20)).json()
            if d.get("gameState") not in ("OFF", "FINAL"):
                return None
            hs, as_ = d["homeTeam"]["score"], d["awayTeam"]["score"]
        elif sport == "mlb":
            d = (await client.get("https://statsapi.mlb.com/api/v1/schedule", params={"gamePk": gid}, timeout=20)).json()
            g = d["dates"][0]["games"][0]
            if g["status"]["abstractGameState"] != "Final":
                return None
            hs, as_ = g["teams"]["home"]["score"], g["teams"]["away"]["score"]
        else:
            from .core.wp_curve import ESPN_SUMMARY
            d = (await client.get(ESPN_SUMMARY[sport], params={"event": gid}, timeout=20)).json()
            comp = d["header"]["competitions"][0]
            if not comp["status"]["type"].get("completed"):
                return None
            sc = {c["homeAway"]: int(c.get("score") or 0) for c in comp["competitors"]}
            hs, as_ = sc["home"], sc["away"]
    except Exception:  # noqa: BLE001
        return None
    out = {"home_score": hs, "away_score": as_, "home_won": None if hs == as_ else hs > as_}
    _finals[key] = out
    return out


@router.get("/results")
async def results(games: str):
    """Final results for up to 60 picked games: games=nfl:401872980,nhl:2026020084,..."""
    keys = [k for k in games.split(",") if ":" in k][:60]
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-play"}) as client:
        outs = await asyncio.gather(*[_final(client, *k.split(":", 1)) for k in keys])
    return {k: o for k, o in zip(keys, outs) if o is not None}


# ---- Rewatch: last night's games ranked by swing ------------------------------------------

_rewatch_cache: tuple[float, dict] | None = None


async def _espn_nfl_ids() -> dict[tuple[str, str], str]:
    from .nfl import espn
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-play"}) as client:
        events = await espn.fetch_current_week(client)
    return {(e["home"], e["away"]): str(e["game_id"]) for e in events if e.get("home") and e.get("away")}


@router.get("/rewatch")
async def rewatch():
    """Games from the latest two days, ranked by total win-probability movement."""
    global _rewatch_cache
    if _rewatch_cache and time.time() - _rewatch_cache[0] < 3 * 3600:
        return _rewatch_cache[1]
    from .core import report_card, wp_curve
    rc = report_card.get()
    rows = [g for v in rc["sports"].values() if "last_slate" in v for g in v["last_slate"]["games"]]
    latest = max((g["date"] for g in rows), default=None)
    if latest:
        cutoff = (date.fromisoformat(latest) - timedelta(days=1)).isoformat()
        rows = [g for g in rows if g["date"] >= cutoff]
    nfl_ids = await _espn_nfl_ids() if any(g["sport"] == "nfl" for g in rows) else {}
    sem = asyncio.Semaphore(8)

    async def one(g):
        gid = nfl_ids.get((g["home"], g["away"])) if g["sport"] == "nfl" else g["game_id"]
        if not gid:
            return None
        async with sem:
            try:
                c = await wp_curve.build(g["sport"], gid, pre_game_p=g["p_home"], final_home_won=g["home_won"])
            except Exception:  # noqa: BLE001
                return None
        if not c:
            return None
        pts = c["points"][:-1] if c["points"][-1].get("label") == "Final" else c["points"]
        swing = sum(abs(b["wp"] - a["wp"]) for a, b in zip(pts, pts[1:]))
        lead_changes = sum((a["wp"] - 0.5) * (b["wp"] - 0.5) < 0 for a, b in zip(pts, pts[1:]))
        winner_low = min((p["wp"] if g["home_won"] else 1 - p["wp"]) for p in pts)
        return {**g, "espn_id": gid, "swing": round(swing, 3), "lead_changes": int(lead_changes),
                "winner_low": round(winner_low, 3),
                # Winner's perspective, so every line finishes at the top.
                "spark": [round(p["wp"] if g["home_won"] else 1 - p["wp"], 3) for p in c["points"]][::max(1, len(c["points"]) // 60)]
                         + [1.0],
                "top_swing": max(c["swings"], key=lambda s: abs(s["to"] - s["from"])) if c["swings"] else None}

    scored = [x for x in await asyncio.gather(*[one(g) for g in rows]) if x]
    scored.sort(key=lambda x: -x["swing"])
    out = {"date": latest, "games": scored[:8],
           "note": "Ranked by total win-probability movement (how much the live model's number swung); "
                   "'lowest point' is the winner's worst moment."}
    _rewatch_cache = (time.time(), out)
    return out
