"""MLB postseason odds from the current series state (methodology/MLB.md §15).

A forward projection from the frozen v1 ratings; not a calibration claim. The
live MLB schedule gives every LCS / World Series game with its series game
number and scheduled home team. Completed games count as played; each
simulation plays the remaining games in order until a team has 4 wins.

Per game: frozen v1 team ratings + home field, starting pitchers unknown
(pitcher term 0), then the postseason layer (methodology/POSTSEASON.md, λ
for MLB) as published. Ratings update in-sim with K_playoff on the raw p.
Supported from the League Championship Series on; earlier rounds and the
regular season are not simulated yet (§15).
"""

from __future__ import annotations

import random
from collections import defaultdict

import httpx

from ..core import postseason
from . import ratings
from .teams import TEAMS

AL = {108, 110, 111, 114, 116, 117, 118, 133, 136, 139, 140, 141, 142, 145, 147}
SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"


async def postseason_state(season: int) -> list[dict]:
    """LCS + World Series games: type, game number, home/away ids (None = TBD), winner id."""
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-mlb (non-commercial)"}) as client:
        r = await client.get(SCHEDULE, params={"sportId": 1, "season": season, "gameType": ["L", "W"]}, timeout=30)
        r.raise_for_status()
    out = []
    for d in r.json().get("dates", []):
        for g in d["games"]:
            t = g["teams"]
            hid, aid = t["home"]["team"].get("id"), t["away"]["team"].get("id")
            final = g["status"]["abstractGameState"] == "Final"
            winner = None
            if final and t["home"].get("isWinner") is not None:
                winner = hid if t["home"]["isWinner"] else aid
            out.append({"type": g["gameType"], "num": int(g.get("seriesGameNumber") or 0),
                        "home": hid if hid in TEAMS else None, "away": aid if aid in TEAMS else None,
                        "home_label": t["home"]["team"].get("name", ""), "winner": winner})
    return out


def _play(rng, r, games, params, a: int, b: int) -> int:
    """Play a best-of-7 between a and b from its current state; returns the winner."""
    wins = {a: 0, b: 0}
    for g in sorted(games, key=lambda g: g["num"]):
        if wins[a] == 4 or wins[b] == 4:
            break
        if g["winner"] is not None:
            wins[g["winner"]] += 1
            continue
        home = g["home"]
        away = b if home == a else a
        p_raw = ratings.win_probability(r[home], r[away], home_bump=params.home_bump, neutral=False)
        p, _ = postseason.apply("mlb", p_raw, True)
        hw = rng.random() < p
        d = params.k_playoff * ((1.0 if hw else 0.0) - p_raw)
        r[home] += d
        r[away] -= d
        wins[home if hw else away] += 1
    return a if wins[a] > wins[b] else b


def simulate(state: list[dict], current: dict[int, float], params: ratings.Params, *, n: int = 10_000,
             seed: int = 7) -> dict:
    lcs = [g for g in state if g["type"] == "L" and g["home"] and g["away"]]
    ws = [g for g in state if g["type"] == "W"]
    pairs = {}
    for g in lcs:
        pairs.setdefault(frozenset((g["home"], g["away"])), []).append(g)
    if len(pairs) != 2:
        return {"supported": False, "rows": []}
    rng = random.Random(seed)
    tally = defaultdict(lambda: defaultdict(float))
    series = list(pairs.items())
    for _ in range(n):
        r = dict(current)
        champs = {}
        for teams, games in series:
            a, b = sorted(teams)
            w = _play(rng, r, games, params, a, b)
            champs["AL" if w in AL else "NL"] = w
            tally[w]["pennant"] += 1
        # World Series: map "AL Champion" / "NL Champion" placeholders (or real ids) to the sim's champions.
        games = []
        for g in ws:
            home = g["home"] or (champs["AL"] if g["home_label"].startswith("AL") else champs["NL"])
            games.append({**g, "home": home, "winner": g["winner"]})
        a, b = champs["AL"], champs["NL"]
        tally[_play(rng, r, games, params, a, b)]["title"] += 1
    rows = []
    for teams, games in series:
        for t in sorted(teams):
            done = [g for g in games if g["winner"] is not None]
            rows.append({"team": TEAMS[t].abbr, "team_id": t, "group": "AL" if t in AL else "NL",
                         "rating": round(current[t], 1),
                         "series_wins": sum(1 for g in done if g["winner"] == t),
                         "series_losses": sum(1 for g in done if g["winner"] not in (t, None)),
                         "pennant": tally[t]["pennant"] / n, "title": tally[t]["title"] / n})
    rows.sort(key=lambda x: -x["title"])
    return {"supported": True, "n": n, "rows": rows,
            "games_left": sum(1 for g in lcs if g["winner"] is None) + sum(1 for g in ws if g["winner"] is None)}
