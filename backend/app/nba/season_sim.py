"""NBA season + playoff odds (methodology/NBA.md §14). A forward projection from
the frozen v1 ratings; not a calibration claim and not evaluated.

Each simulation plays every unplayed regular-season game (ratings update in-sim
with K_regular × (W − P); no MOV), then per conference:
  - seeds 1–6 qualify; 7–10 play the play-in (7 hosts 8 → 7th seed; 9 hosts 10,
    loser out; the 7–8 loser hosts that winner → 8th seed);
  - a fixed bracket 1v8, 4v5, 3v6, 2v7 (no reseeding), every round best-of-7 with
    2-2-1-1-1 home court for the better record; the Finals the same.
Ties in the standings are broken at random (the NBA's tiebreakers are not modelled).
The remaining schedule comes from ESPN's scoreboard and is cached for a day.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from . import espn, pipeline, ratings

EAST = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DET", "IND", "MIA", "MIL", "NY", "ORL", "PHI", "TOR", "WSH"}
SCHEDULE_DIR = pipeline.DATA_DIR / "schedule"


@dataclass
class SimResult:
    season: int
    n: int
    games_left: int
    rows: list[dict]


async def _fetch_schedule(season: int) -> list[dict]:
    start = max(date.today(), date(season // 10000, 10, 1))
    end = date(season // 10000 + 1, 4, 20)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    sem = asyncio.Semaphore(8)

    async def one(client, d):
        async with sem:
            return await espn.fetch_day(client, d)

    async with httpx.AsyncClient(headers={"User-Agent": "tilt-nba-schedule"}) as client:
        per_day = await asyncio.gather(*[one(client, d) for d in days])
    return [{"game_id": r["game_id"], "home": r["home_team_id"], "away": r["away_team_id"],
             "home_abbr": r["home_abbr"], "away_abbr": r["away_abbr"], "neutral": r["espn_neutral"]}
            for rows in per_day for r in rows
            if r["season_id"] == season and r["season_type"] == 2 and not r["completed"]]


async def remaining_schedule(season: int) -> list[dict]:
    """Unplayed regular-season games, cached for a day."""
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    path = SCHEDULE_DIR / f"{season}.json"
    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text())
    games = await _fetch_schedule(season)
    path.write_text(json.dumps(games))
    return games


def _series(rng, r, hi, lo, params) -> int:
    """Best-of-7, 2-2-1-1-1 (hi has home court). Returns the winner."""
    wins = {hi: 0, lo: 0}
    for g in range(7):
        home, away = (hi, lo) if g in (0, 1, 4, 6) else (lo, hi)
        p = ratings.win_probability(r[home], r[away], home_bump=params.home_bump, neutral=False)
        hw = rng.random() < p
        d = params.k_playoff * ((1.0 if hw else 0.0) - p)
        r[home] += d
        r[away] -= d
        wins[home if hw else away] += 1
        if wins[home if hw else away] == 4:
            return home if hw else away
    raise AssertionError("unreachable")


def _game(rng, r, home, away, params) -> int:
    p = ratings.win_probability(r[home], r[away], home_bump=params.home_bump, neutral=False)
    return home if rng.random() < p else away


def simulate(season: int, current: dict[int, float], params: ratings.Params, left: list[dict], *,
             n: int = 5_000, seed: int = 7) -> SimResult:
    played = [g for g in pipeline.read_season(season) if g["season_type"] == 2 and g["completed"]]
    done_ids = {g["game_id"] for g in played}
    left = [g for g in left if g["game_id"] not in done_ids]
    abbr: dict[int, str] = {}
    wins0: dict[int, float] = defaultdict(float)
    for g in played:
        h, a = g["home_team_id"], g["away_team_id"]
        abbr[h], abbr[a] = g["home_abbr"], g["away_abbr"]
        wins0[h if g["home_score"] > g["away_score"] else a] += 1
    for g in left:
        abbr[g["home"]], abbr[g["away"]] = g["home_abbr"], g["away_abbr"]
    teams = sorted(t for t in abbr if t in current)
    conf = {t: "East" if abbr[t] in EAST else "West" for t in teams}
    rng = random.Random(seed)
    tally = {t: defaultdict(float) for t in teams}

    for _ in range(n):
        r = dict(current)
        wins = dict(wins0)
        for g in left:
            h, a = g["home"], g["away"]
            if h not in r or a not in r:
                continue
            p = ratings.win_probability(r[h], r[a], home_bump=params.home_bump, neutral=g["neutral"])
            hw = rng.random() < p
            wins[h if hw else a] = wins.get(h if hw else a, 0) + 1
            d = params.k_regular * ((1.0 if hw else 0.0) - p)
            r[h] += d
            r[a] -= d
        jitter = {t: rng.random() for t in teams}
        for t in teams:
            tally[t]["wins"] += wins.get(t, 0)
        champs = []
        for c in ("East", "West"):
            order = sorted((t for t in teams if conf[t] == c), key=lambda t: (wins.get(t, 0), jitter[t]), reverse=True)
            for t in order[:6]:
                tally[t]["top6"] += 1
            s7, s8, s9, s10 = order[6:10]
            w78 = _game(rng, r, s7, s8, params)
            l78 = s8 if w78 == s7 else s7
            w910 = _game(rng, r, s9, s10, params)
            eighth = _game(rng, r, l78, w910, params)
            seeds = order[:6] + [w78, eighth]
            for t in seeds:
                tally[t]["playoffs"] += 1
            bracket = [seeds[i] for i in (0, 7, 3, 4, 2, 5, 1, 6)]
            rank = {t: i for i, t in enumerate(order)}
            while len(bracket) > 1:
                nxt = []
                for i in range(0, len(bracket), 2):
                    x, y = bracket[i], bracket[i + 1]
                    hi, lo = (x, y) if rank.get(x, 99) < rank.get(y, 99) else (y, x)
                    nxt.append(_series(rng, r, hi, lo, params))
                bracket = nxt
            tally[bracket[0]]["conference"] += 1
            champs.append(bracket[0])
        e, w = champs
        hi, lo = (e, w) if (wins.get(e, 0), jitter[e]) > (wins.get(w, 0), jitter[w]) else (w, e)
        tally[_series(rng, r, hi, lo, params)]["title"] += 1

    rows = [{"team": abbr[t], "team_id": t, "group": conf[t], "rating": round(current[t], 1),
             "wins_now": wins0.get(t, 0), "proj_wins": round(tally[t]["wins"] / n, 1),
             "top6": tally[t]["top6"] / n, "playoffs": tally[t]["playoffs"] / n,
             "conference": tally[t]["conference"] / n, "title": tally[t]["title"] / n} for t in teams]
    rows.sort(key=lambda x: (-x["title"], -x["playoffs"], -x["proj_wins"]))
    return SimResult(season, n, len(left), rows)
