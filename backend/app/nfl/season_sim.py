"""NFL season + playoff odds (methodology/NFL.md §14). A forward projection from
the frozen v1 ratings; not a calibration claim and not evaluated.

Each of N simulations:
  1. plays every unplayed regular-season game: P from the frozen model (home
     field unless neutral); ties not simulated; ratings update in-sim with
     K_regular × (W − P) (no MOV, since there is no simulated margin);
  2. seeds 7 per conference: 4 division winners (1–4 by wins), then the 3 best
     other records. Ties are broken at random; the NFL's real tiebreakers are
     not modelled;
  3. plays the bracket: 2v7, 3v6, 4v5 (1 has a bye), reseeded each round, the
     higher seed at home, a neutral Super Bowl, K_playoff updates.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from . import pipeline, ratings

DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"], "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"], "AFC West": ["DEN", "KC", "LAC", "LV"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"], "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"], "NFC West": ["ARI", "LA", "SEA", "SF"],
}
DIV_OF = {t: d for d, ts in DIVISIONS.items() for t in ts}
CONF_OF = {t: d.split()[0] for t, d in DIV_OF.items()}


@dataclass
class SimResult:
    season: int
    n: int
    games_left: int
    rows: list[dict]


def _p(r: dict[str, float], h: str, a: str, params: ratings.Params, neutral: bool) -> float:
    return ratings.win_probability(r[h], r[a], home_bump=params.home_bump, neutral=neutral)


def simulate(season: int, current: dict[str, float], params: ratings.Params, *, n: int = 10_000,
             seed: int = 7) -> SimResult:
    games = [g for g in pipeline.read_games() if g["season"] == season and g["game_type"] == "REG"]
    wins0: dict[str, float] = defaultdict(float)
    left = []
    for g in games:
        h, a = g["home_team"], g["away_team"]
        if g["home_score"] is None:
            left.append((h, a, g["location"] == "Neutral"))
        else:
            w = ratings.outcome(g["home_score"], g["away_score"])
            wins0[h] += w
            wins0[a] += 1 - w
    teams = sorted(DIV_OF)
    rng = random.Random(seed)
    tally = {t: defaultdict(float) for t in teams}

    for _ in range(n):
        r = dict(current)
        wins = dict(wins0)
        for h, a, neutral in left:
            p = _p(r, h, a, params, neutral)
            w = 1.0 if rng.random() < p else 0.0
            wins[h] = wins.get(h, 0) + w
            wins[a] = wins.get(a, 0) + 1 - w
            d = params.k_regular * (w - p)
            r[h] += d
            r[a] -= d
        jitter = {t: rng.random() for t in teams}           # random tiebreaks
        key = lambda t: (wins.get(t, 0), jitter[t])          # noqa: E731
        for t in teams:
            tally[t]["wins"] += wins.get(t, 0)
        champs = {}
        for conf in ("AFC", "NFC"):
            div_winners = sorted((max(ts, key=key) for d, ts in DIVISIONS.items() if d.startswith(conf)),
                                 key=key, reverse=True)
            rest = sorted((t for t in teams if CONF_OF[t] == conf and t not in div_winners), key=key, reverse=True)
            seeds = div_winners + rest[:3]
            for i, t in enumerate(seeds):
                tally[t]["playoffs"] += 1
                if i < 4:
                    tally[t]["division"] += 1
                if i == 0:
                    tally[t]["top_seed"] += 1
            alive = list(range(1, 8))            # seed numbers
            # Wild card: 2v7, 3v6, 4v5; seed 1 rests.
            for rnd in range(3):
                playing = [s for s in alive if not (rnd == 0 and s == 1)]
                playing.sort()
                nxt = [1] if rnd == 0 else []
                while playing:
                    hi, lo = playing.pop(0), playing.pop(-1)
                    th, ta = seeds[hi - 1], seeds[lo - 1]
                    p = _p(r, th, ta, params, False)
                    hw = rng.random() < p
                    d = params.k_playoff * ((1.0 if hw else 0.0) - p)
                    r[th] += d
                    r[ta] -= d
                    nxt.append(hi if hw else lo)
                alive = sorted(nxt)
            champs[conf] = seeds[alive[0] - 1]
            tally[champs[conf]]["conference"] += 1
        a, b = champs["AFC"], champs["NFC"]
        p = _p(r, a, b, params, True)
        sb = a if rng.random() < p else b
        tally[sb]["title"] += 1

    rows = []
    for t in teams:
        x = tally[t]
        rows.append({"team": t, "group": DIV_OF[t], "rating": round(current[t], 1),
                     "wins_now": wins0.get(t, 0), "proj_wins": round(x["wins"] / n, 1),
                     "playoffs": x["playoffs"] / n, "division": x["division"] / n, "top_seed": x["top_seed"] / n,
                     "conference": x["conference"] / n, "title": x["title"] / n})
    rows.sort(key=lambda r: (-r["title"], -r["playoffs"], -r["proj_wins"]))
    return SimResult(season, n, len(left), rows)
