"""Walk-forward college football backtest (methodology/CFB.md §5, §7; v1.2).

Keys are ESPN team ids for FBS programs and the string "FCS" for the pooled
opponent. Each season: FBS ratings regress toward 1500 and the pool toward
`fcs_init` (same carry); programs new to FBS start at the pool's value.
FBS-vs-FCS games update ratings and are recorded with `fcs_game=True` so the
evaluator can keep them out of every metric (DECISION 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..core import elo
from . import pipeline, ratings
from .ratings import FCS


@dataclass(frozen=True)
class Prediction:
    season: int
    game_id: int
    week: int
    postseason: bool
    home: int | str
    away: int | str
    home_win_prob: float
    outcome: float
    neutral: bool
    conference_game: bool
    fcs_game: bool


@dataclass(frozen=True)
class TrajectoryPoint:
    game_id: int
    game_date: str
    rating: float


@dataclass
class Result:
    ratings: dict
    predictions: list[Prediction]
    trajectories: dict = field(default_factory=dict)
    fbs_by_season: dict = field(default_factory=dict)


def load(seasons: Iterable[int]) -> dict[int, tuple[list[dict], set[int]]]:
    out = {}
    for s in seasons:
        rows = pipeline.read_games(s)
        fbs = pipeline.fbs_teams(s, rows)
        games = [r for r in pipeline.completed_games(rows) if r["home_id"] in fbs or r["away_id"] in fbs]
        games.sort(key=lambda r: (r["game_date"], r["game_id"]))
        out[s] = (games, fbs)
    return out


def segment(p: Prediction) -> str:
    """§6 segments: weeks 1–4 / 5–10 / 11+; bowls and playoff separate."""
    if p.postseason:
        return "postseason"
    return "early" if p.week <= 4 else ("mid" if p.week <= 10 else "late")


def run(seasons: list[int], params: ratings.Params, *, data, record_predictions_for: set[int] | None = None,
        record_trajectories: bool = False) -> Result:
    record = record_predictions_for or set()
    R: dict = {FCS: params.fcs_init}
    preds: list[Prediction] = []
    traj: dict = {}
    for i, season in enumerate(seasons):
        games, fbs = data[season]
        if i > 0:
            for k in list(R):
                if k == FCS:
                    R[k] = elo.regress(R[k], carry=params.carry, mean=params.fcs_init)
                elif k in fbs:
                    R[k] = ratings.regress(R[k], params.carry)
                else:
                    del R[k]  # left FBS → represented by the pool from now on
        for t in fbs:
            if t not in R:
                R[t] = 1500.0 if i == 0 else R[FCS]   # 2001 programs at 1500; entrants at the pool (DECISION 3)
        st = {} if record_trajectories else None
        for g in games:
            h = g["home_id"] if g["home_id"] in fbs else FCS
            a = g["away_id"] if g["away_id"] in fbs else FCS
            post = g["season_type"] == 3
            if st is not None:
                for k in (h, a):
                    if k != FCS and k not in st:
                        st[k] = [TrajectoryPoint(0, g["game_date"], R[k])]
            new_h, new_a, p = ratings.update(
                R[h], R[a], home_score=g["home_score"], away_score=g["away_score"],
                k=params.k_post if post else params.k_regular, home_bump=params.home_bump,
                neutral=g["neutral"], mov=params.mov)
            if season in record:
                preds.append(Prediction(season, g["game_id"], g["week"], post, h, a, p,
                                        ratings.outcome(g["home_score"], g["away_score"]),
                                        g["neutral"], g["conference_game"], FCS in (h, a)))
            R[h], R[a] = new_h, new_a
            if st is not None:
                for k, v in ((h, new_h), (a, new_a)):
                    if k != FCS:
                        st[k].append(TrajectoryPoint(g["game_id"], g["game_date"], v))
        if st is not None:
            traj[season] = st
    return Result(R, preds, traj, {s: data[s][1] for s in seasons})
