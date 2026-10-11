"""NHL skater projections: P(≥1 point), P(≥1 goal) per game (methodology/NHL_PLAYERS.md).

For skater i before game g (only earlier games are used):

    TOI_hat  = decayed mean TOI (half-life H_toi games) with a 2-game prior at
               the position's debut TOI
    rate_hat = (Σ w·x + m·r_pos) / (Σ w·toi/60 + m)        per-60 rate, w = 0.5^(age/H)
    λ        = rate_hat · TOI_hat/60 · opp^γ · home^(±1)
    P(≥1)    = 1 − exp(−λ)

Splits (§3, approved): warm-up 1998-99 → 2009-10, validation 2010-11 → 2022-23,
test 2023-24 → 2025-26 (read once, by scripts.players_evaluate only).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from . import boxscores, metrics

EVENTS = ("points", "goals")
WARMUP = [s for s in range(19981999, 20092010 + 1, 10001) if s != 20042005]
VALIDATION = list(range(20102011, 20222023 + 1, 10001))
TEST_DO_NOT_TOUCH = [20232024, 20242025, 20252026]
M_TOI = 2.0
OPP_HALF_LIFE = 20.0
DEBUT_GAMES = 10

GRID = [dict(H=H, m=m, H_toi=ht, gamma=g, home=h)
        for H in (20, 40, 80, 160, 320) for m in (1, 2, 4, 8) for ht in (5, 10, 20)
        for g in (0.0, 0.5, 1.0) for h in (1.00, 1.03, 1.06)]


@dataclass
class Row:
    """One skater-game, in chronological order, with the state-free facts."""

    season: int
    game_id: int
    player_id: int
    team: str
    opponent: str
    is_home: bool
    pos: str
    toi_min: float
    points: int
    goals: int


def load_sorted(seasons: Sequence[int]) -> list[Row]:
    """Rows in true date order (game ids are not date-ordered across types)."""
    raw: list[tuple] = []
    for s in seasons:
        for r in boxscores.read_season(s):
            if r["pos"] == "G" or r["game_type"] not in (2, 3):
                continue
            raw.append((r["game_date"], r["game_id"], Row(s, r["game_id"], r["player_id"], r["team"], r["opponent"],
                                                         r["is_home"], r["pos"], (r["toi_s"] or 0) / 60.0,
                                                         r["points"], r["goals"])))
    raw.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in raw]


@dataclass
class SeasonPriors:
    """Per-season position priors, computed from the PREVIOUS season (§4, v0.3)."""

    rate60: dict[tuple[str, str], float]      # (event, pos) -> per-60 rate
    base: dict[tuple[str, str], float]        # (event, pos) -> P(≥1) per game (Baseline A)
    debut_toi: dict[str, float]               # pos -> mean TOI in first 10 career games
    league_ga: float                          # goals allowed per team-game


def season_priors(rows: Iterable[Row], career_games_before: dict[int, int]) -> SeasonPriors:
    toi = defaultdict(float)
    cnt = defaultdict(float)
    hit = defaultdict(float)
    n = defaultdict(int)
    debut = defaultdict(list)
    ga = defaultdict(int)
    team_games: set[tuple[int, str]] = set()
    seen = dict(career_games_before)
    for r in rows:
        toi[r.pos] += r.toi_min
        n[r.pos] += 1
        for e in EVENTS:
            v = getattr(r, e)
            cnt[(e, r.pos)] += v
            hit[(e, r.pos)] += v >= 1
        if seen.get(r.player_id, 0) < DEBUT_GAMES:
            debut[r.pos].append(r.toi_min)
        seen[r.player_id] = seen.get(r.player_id, 0) + 1
        ga[(r.game_id, r.opponent)] += r.goals
        team_games.add((r.game_id, r.team))
    return SeasonPriors(
        rate60={(e, p): cnt[(e, p)] / (toi[p] / 60.0) for e in EVENTS for p in toi},
        base={(e, p): hit[(e, p)] / n[p] for e in EVENTS for p in n},
        debut_toi={p: sum(v) / len(v) for p, v in debut.items()},
        league_ga=sum(ga.values()) / max(len(team_games), 1),
    )


def _by_season(rows: list[Row]) -> dict[int, list[Row]]:
    out: dict[int, list[Row]] = defaultdict(list)
    for r in rows:
        out[r.season].append(r)
    return out


def priors_for(rows: list[Row]) -> dict[int, SeasonPriors]:
    """Priors used DURING each season = computed from the season before (the
    first season uses its own, warm-up only)."""
    seasons = _by_season(rows)
    order = sorted(seasons)
    career: dict[int, int] = {}
    stats: dict[int, SeasonPriors] = {}
    for s in order:
        stats[s] = season_priors(seasons[s], career)
        for r in seasons[s]:
            career[r.player_id] = career.get(r.player_id, 0) + 1
    return {s: stats[order[i - 1]] if i else stats[s] for i, s in enumerate(order)}


@dataclass
class Prediction:
    season: int
    game_id: int
    player_id: int
    pos: str
    p: float
    y: int


def replay(rows: list[Row], event: str, params: dict, priors: dict[int, SeasonPriors],
           record: set[int]) -> list[Prediction]:
    """Walk-forward predictions for one event. Updates happen after each game."""
    d = 0.5 ** (1.0 / params["H"])
    dt = 0.5 ** (1.0 / params["H_toi"])
    do = 0.5 ** (1.0 / OPP_HALF_LIFE)
    m, gamma, home = params["m"], params["gamma"], params["home"]
    sx: dict[int, float] = {}
    st: dict[int, float] = {}
    tw: dict[int, float] = {}
    tt: dict[int, float] = {}
    ga_w: dict[str, float] = {}
    ga_s: dict[str, float] = {}
    out: list[Prediction] = []
    i, n = 0, len(rows)
    while i < n:
        gid = rows[i].game_id
        j = i
        while j < n and rows[j].game_id == gid:
            j += 1
        game = rows[i:j]
        pr = priors[game[0].season]
        if game[0].season in record:
            for r in game:
                debut = pr.debut_toi.get(r.pos, 15.0)
                toi_hat = (tt.get(r.player_id, 0.0) + M_TOI * debut) / (tw.get(r.player_id, 0.0) + M_TOI)
                r_pos = pr.rate60[(event, r.pos)]
                rate = (sx.get(r.player_id, 0.0) + m * r_pos) / (st.get(r.player_id, 0.0) + m)
                opp = (ga_s[r.opponent] / ga_w[r.opponent] / pr.league_ga
                       if r.opponent in ga_w and pr.league_ga > 0 else 1.0)
                lam = rate * toi_hat / 60.0 * opp ** gamma * (home if r.is_home else 1.0 / home)
                out.append(Prediction(r.season, gid, r.player_id, r.pos, 1.0 - math.exp(-lam),
                                      int(getattr(r, event) >= 1)))
        ga: dict[str, int] = defaultdict(int)
        for r in game:
            pid = r.player_id
            sx[pid] = sx.get(pid, 0.0) * d + getattr(r, event)
            st[pid] = st.get(pid, 0.0) * d + r.toi_min / 60.0
            tt[pid] = tt.get(pid, 0.0) * dt + r.toi_min
            tw[pid] = tw.get(pid, 0.0) * dt + 1.0
            ga[r.opponent] += r.goals
        for team in {r.team for r in game}:
            ga_s[team] = ga_s.get(team, 0.0) * do + ga.get(team, 0)
            ga_w[team] = ga_w.get(team, 0.0) * do + 1.0
        i = j
    return out


def baselines(rows: list[Row], event: str, priors: dict[int, SeasonPriors], record: set[int]):
    """(Baseline A, Baseline B) predictions, aligned with `replay` order."""
    hist: dict[int, list[int]] = defaultdict(list)
    a, b = [], []
    for r in rows:
        pr = priors[r.season]
        if r.season in record:
            pa = pr.base[(event, r.pos)]
            h = hist[r.player_id]
            pb = pa if len(h) < 10 else 1.0 - math.exp(-sum(h[-82:]) / len(h[-82:]))
            a.append(pa)
            b.append(pb)
        hist[r.player_id].append(getattr(r, event))
    return a, b


def top_decile_gap(p: Sequence[float], y: Sequence[int]) -> float:
    order = sorted(range(len(p)), key=lambda i: p[i], reverse=True)[: max(len(p) // 10, 1)]
    return abs(sum(p[i] for i in order) / len(order) - sum(y[i] for i in order) / len(order))


def score(p: Sequence[float], y: Sequence[int]) -> dict:
    return {"n": len(p), "log_loss": metrics.log_loss(p, y), "brier": metrics.brier_score(p, y),
            "ece": metrics.expected_calibration_error(p, y), "top_decile_gap": top_decile_gap(p, y),
            "mean_p": sum(p) / len(p), "rate": sum(y) / len(y)}
