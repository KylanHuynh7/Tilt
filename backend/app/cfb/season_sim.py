"""College football projected records (methodology/CFB.md §14). A forward
projection from the frozen v1 ratings; not a calibration claim.

The CFP field is picked by a committee, which can't be simulated faithfully,
so only regular-season outcomes are projected: wins, bowl eligibility
(≥ 6 wins; every FCS win counts here, a simplification) and an unbeaten
regular season. Conference title games aren't scheduled until their teams
are known, so they are not included. FCS opponents use the pooled FCS rating.
"""

from __future__ import annotations

import random
from collections import defaultdict

from . import pipeline, ratings


def simulate(season: int, current: dict, params: ratings.Params, fbs: set[int], fcs_key, *,
             n: int = 5_000, seed: int = 7) -> dict:
    games = [g for g in pipeline.read_games(season) if g["season_type"] == 2]
    key = lambda t: t if t in fbs else fcs_key            # noqa: E731
    wins0, losses0 = defaultdict(int), defaultdict(int)
    left, names = [], {}
    for g in games:
        h, a = g["home_id"], g["away_id"]
        for t, nm in ((h, g.get("home_abbr")), (a, g.get("away_abbr"))):
            if t in fbs:
                names[t] = nm
        if g["completed"]:
            if g["home_score"] == g["away_score"]:
                continue
            w, l = (h, a) if g["home_score"] > g["away_score"] else (a, h)
            wins0[w] += 1
            losses0[l] += 1
        elif h in fbs or a in fbs:
            left.append((h, a, bool(g["neutral"])))
    rng = random.Random(seed)
    tally = {t: defaultdict(float) for t in fbs}
    for _ in range(n):
        r = dict(current)
        wins, losses = dict(wins0), dict(losses0)
        for h, a, neutral in left:
            kh, ka = key(h), key(a)
            rh, ra = r.get(kh, r[fcs_key]), r.get(ka, r[fcs_key])
            p = ratings.win_probability(rh, ra, home_bump=params.home_bump, neutral=neutral)
            hw = rng.random() < p
            w, l = (h, a) if hw else (a, h)
            wins[w] = wins.get(w, 0) + 1
            losses[l] = losses.get(l, 0) + 1
            if kh != fcs_key and ka != fcs_key:
                d = params.k_regular * ((1.0 if hw else 0.0) - p)
                r[kh] += d
                r[ka] -= d
        for t in fbs:
            x = tally[t]
            x["wins"] += wins.get(t, 0)
            x["bowl"] += wins.get(t, 0) >= 6
            x["unbeaten"] += losses.get(t, 0) == 0
    rows = [{"team": names.get(t, str(t)), "team_id": t, "group": "FBS", "rating": round(current.get(t, 0), 1),
             "record_now": f"{wins0.get(t, 0)}-{losses0.get(t, 0)}",
             "proj_wins": round(tally[t]["wins"] / n, 1), "bowl": tally[t]["bowl"] / n,
             "unbeaten": tally[t]["unbeaten"] / n} for t in fbs if t in names]
    rows.sort(key=lambda x: (-x["rating"]))
    return {"n": n, "games_left": len(left), "rows": rows}
