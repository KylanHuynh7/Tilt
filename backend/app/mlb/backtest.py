"""Walk-forward MLB backtest with the rolling starting-pitcher term
(methodology/MLB.md §5, §7; v1.1 clarifications).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from . import pipeline, ratings
from .teams import is_franchise

PROBABLES_FROM = 2010


@dataclass(frozen=True)
class Prediction:
    season: int
    game_pk: int
    game_date: date
    game_type: str
    home_id: int
    away_id: int
    home_win_prob: float
    outcome: float
    neutral: bool
    home_pitcher_first_start: bool
    away_pitcher_first_start: bool

    @property
    def is_playoff(self) -> bool:
        return self.game_type in pipeline.PLAYOFF_TYPES


@dataclass(frozen=True)
class TrajectoryPoint:
    game_pk: int
    game_date: date
    rating: float


@dataclass
class Result:
    ratings: dict[int, float]
    predictions: list[Prediction]
    trajectories: dict[int, dict[int, list[TrajectoryPoint]]] = field(default_factory=dict)
    pitcher_rgs: dict[int, float] = field(default_factory=dict)
    team_rgs: dict[int, float] = field(default_factory=dict)


@dataclass
class SeasonData:
    games: list[dict]
    starters: dict[tuple[int, str], dict]   # (game_pk, side) → starter line


def load(seasons: Iterable[int]) -> dict[int, SeasonData]:
    out = {}
    for s in seasons:
        games = [g for g in pipeline.read_games(s)
                 if pipeline.is_valid_result(g) and is_franchise(g["home_id"]) and is_franchise(g["away_id"])]
        starters = {(x["game_pk"], x["side"]): x for x in pipeline.read_starters(s)}
        out[s] = SeasonData(games, starters)
    return out


def segment(p: Prediction) -> str:
    """§6 month segments: Apr–May / Jun–Aug / Sep–Oct (March counts as early)."""
    if p.is_playoff:
        return "postseason"
    m = p.game_date.month
    return "early" if m <= 5 else ("late" if m >= 9 else "mid")


def run(seasons: list[int], params: ratings.Params, *, data: dict[int, SeasonData],
        record_predictions_for: set[int] | None = None, record_trajectories: bool = False) -> Result:
    record = record_predictions_for or set()
    R: dict[int, float] = {}
    p_rgs: dict[int, float] = {}
    t_rgs: dict[int, float] = {}
    gs_sum, gs_n = 0.0, 0
    preds: list[Prediction] = []
    traj: dict[int, dict[int, list[TrajectoryPoint]]] = {}

    fip = params.pitcher_model == "fip"
    d_p = 0.5 ** (1.0 / params.h_p)
    f_num: dict[int, float] = {}            # pitcher → decayed Σ FIP numerator
    f_ip: dict[int, float] = {}             # pitcher → decayed Σ innings
    rotation: dict[int, list[int]] = {}     # team → last 5 starters
    lg_num = lg_ip = 0.0                    # current season league totals
    f_lg = 0.0                              # league FIP numerator per inning; set each season

    def pitcher_fip(pid: int | None) -> float:
        if pid is None:
            return f_lg
        return (f_num.get(pid, 0.0) + params.m_ip * f_lg) / (f_ip.get(pid, 0.0) + params.m_ip)

    for i, season in enumerate(seasons):
        if fip:
            # League value = previous season's FIP numerator per inning (first season: its own, warm-up only).
            if lg_ip > 0:
                f_lg = lg_num / lg_ip
            elif i == 0:
                sd0 = data[season]
                n0 = sum(ratings.fip_num(x["k"], x["bb"], x["hr"]) for x in sd0.starters.values())
                ip0 = sum(x["outs"] for x in sd0.starters.values()) / 3.0
                f_lg = n0 / ip0 if ip0 else 0.0
            lg_num = lg_ip = 0.0
        if i > 0:
            for t in R:
                R[t] = ratings.regress(R[t], params.carry)
        st = {} if record_trajectories else None
        sd = data[season]
        for g in sd.games:
            h, a = g["home_id"], g["away_id"]
            league_mean = gs_sum / gs_n if gs_n else ratings.INITIAL_GAME_SCORE
            for t in (h, a):
                R.setdefault(t, ratings.INITIAL_RATING)
                t_rgs.setdefault(t, league_mean)
                if st is not None and t not in st:
                    st[t] = [TrajectoryPoint(0, g["game_date"], R[t])]

            # Which pitcher's rating feeds the prediction (v1.1 iv).
            def chosen(side: str, team: int) -> int | None:
                prob = g[f"{side}_probable_id"] if season >= PROBABLES_FROM else None
                if prob:
                    return prob
                line = sd.starters.get((g["game_pk"], side))
                return line["pitcher_id"] if line else None

            def adj(pid: int | None, team: int) -> tuple[float, bool]:
                if fip:
                    first = pid is None or pid not in f_ip
                    if params.c == 0 or pid is None:
                        return 0.0, first
                    rot = rotation.get(team) or []
                    team_val = sum(pitcher_fip(x) for x in rot) / len(rot) if rot else f_lg
                    # (13·HR + 3·BB − 2·K)/IP is already in runs per nine innings
                    # (FIP without its constant). Lower is better.
                    return params.c * (team_val - pitcher_fip(pid)), first
                if params.c == 0 or pid is None or pid not in p_rgs:
                    return 0.0, pid is None or pid not in p_rgs
                return params.c * (p_rgs[pid] - t_rgs[team]), False

            a_h, first_h = adj(chosen("home", h), h)
            a_a, first_a = adj(chosen("away", a), a)
            bump = 0.0 if g["neutral"] else params.home_bump
            p_home = ratings.win_probability(R[h], R[a], a_home=a_h, a_away=a_a,
                                             home_bump=params.home_bump, neutral=g["neutral"])
            playoff = g["game_type"] in pipeline.PLAYOFF_TYPES
            new_h, new_a = ratings.update(
                R[h], R[a], home_score=g["home_score"], away_score=g["away_score"],
                k=params.k_playoff if playoff else params.k_regular, p_home=p_home,
                eff_diff_home=(R[h] + a_h + bump) - (R[a] + a_a), mov=params.mov,
            )
            if season in record:
                preds.append(Prediction(season, g["game_pk"], g["game_date"], g["game_type"], h, a,
                                        p_home, ratings.outcome(g["home_score"], g["away_score"]),
                                        g["neutral"], first_h, first_a))
            R[h], R[a] = new_h, new_a
            if st is not None:
                st[h].append(TrajectoryPoint(g["game_pk"], g["game_date"], new_h))
                st[a].append(TrajectoryPoint(g["game_pk"], g["game_date"], new_a))

            # Post-game pitcher updates from the ACTUAL starters (v1.1 iii).
            for side, team in (("home", h), ("away", a)):
                line = sd.starters.get((g["game_pk"], side))
                if not line:
                    continue
                if fip:
                    pid = line["pitcher_id"]
                    num, ip = ratings.fip_num(line["k"], line["bb"], line["hr"]), line["outs"] / 3.0
                    f_num[pid] = f_num.get(pid, 0.0) * d_p + num
                    f_ip[pid] = f_ip.get(pid, 0.0) * d_p + ip
                    lg_num += num
                    lg_ip += ip
                    rot = rotation.setdefault(team, [])
                    rot.append(pid)
                    del rot[:-5]
                    continue
                gs = ratings.game_score(line["outs"], line["k"], line["bb"], line["h"], line["r"], line["hr"])
                pid = line["pitcher_id"]
                p_rgs[pid] = (1 - params.alpha) * p_rgs.get(pid, t_rgs[team]) + params.alpha * gs
                t_rgs[team] = (1 - params.alpha) * t_rgs[team] + params.alpha * gs
                gs_sum += gs
                gs_n += 1
        if st is not None:
            traj[season] = st
    return Result(R, preds, traj, p_rgs, t_rgs)
