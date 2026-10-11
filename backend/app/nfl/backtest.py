"""Walk-forward NFL backtest (methodology/NFL.md §7, inheriting NBA §7).

Predict-then-update over every completed game in date order. Regression to
1500 once per franchise at each season boundary; first-seen franchises
(Houston, 2002) start at 1500 unregressed. Evaluation-blind: predictions are
recorded only for requested seasons and never scored here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from . import pipeline, ratings
from .teams import franchise


@dataclass(frozen=True)
class Prediction:
    season: int
    game_id: str
    gameday: date
    game_type: str
    week: int
    home: str
    away: str
    home_win_prob: float
    outcome: float      # 1 home win, 0.5 tie, 0 away win
    neutral: bool

    @property
    def is_playoff(self) -> bool:
        return self.game_type in pipeline.PLAYOFF_TYPES


@dataclass(frozen=True)
class TrajectoryPoint:
    game_id: str
    gameday: date
    rating: float


@dataclass
class Result:
    ratings: dict[str, float]
    predictions: list[Prediction]
    trajectories: dict[int, dict[str, list[TrajectoryPoint]]] = field(default_factory=dict)
    games_processed: int = 0


def regular_weeks(season: int) -> int:
    """Regular-season weeks: 17 through 2020, 18 from 2021 (17 games + bye)."""
    return 17 if season < 2021 else 18


def segment(p: Prediction) -> str:
    """§6 week segments: 1–4 / 5–16 / 17–18 (18-week seasons) or
    1–4 / 5–15 / 16–17 (17-week seasons); playoffs separate.
    """
    if p.is_playoff:
        return "postseason"
    last_mid = regular_weeks(p.season) - 2
    return "early" if p.week <= 4 else ("late" if p.week > last_mid else "mid")


def rows_by_season(through: int | None = None) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for r in pipeline.read_games():
        if r["home_score"] is None or r["away_score"] is None:
            continue
        if through is not None and r["season"] > through:
            continue
        if franchise(r["home_team"]) is None or franchise(r["away_team"]) is None:
            continue
        out[r["season"]].append(r)
    return dict(sorted(out.items()))


def run(
    seasons: Iterable[int],
    params: ratings.Params,
    *,
    rows: dict[int, list[dict]],
    record_predictions_for: set[int] | None = None,
    record_trajectories: bool = False,
) -> Result:
    record = record_predictions_for or set()
    state: dict[str, float] = {}
    preds: list[Prediction] = []
    traj: dict[int, dict[str, list[TrajectoryPoint]]] = {}
    processed = 0

    for i, season in enumerate(seasons):
        if i > 0:
            for t in state:
                state[t] = ratings.regress(state[t], params.carry)
        season_traj: dict[str, list[TrajectoryPoint]] | None = {} if record_trajectories else None
        for r in rows.get(season, []):
            h, a = franchise(r["home_team"]), franchise(r["away_team"])
            for t in (h, a):
                state.setdefault(t, ratings.INITIAL_RATING)
                if season_traj is not None and t not in season_traj:
                    season_traj[t] = [TrajectoryPoint("", r["gameday"], state[t])]
            neutral = r["location"] == "Neutral"
            playoff = r["game_type"] in pipeline.PLAYOFF_TYPES
            new_h, new_a, p_home = ratings.update(
                state[h], state[a], home_score=r["home_score"], away_score=r["away_score"],
                k=params.k_playoff if playoff else params.k_regular,
                home_bump=params.home_bump, neutral=neutral, mov=params.mov,
            )
            if season in record:
                preds.append(Prediction(
                    season=season, game_id=r["game_id"], gameday=r["gameday"],
                    game_type=r["game_type"], week=r["week"], home=h, away=a,
                    home_win_prob=p_home, outcome=ratings.outcome(r["home_score"], r["away_score"]),
                    neutral=neutral,
                ))
            state[h], state[a] = new_h, new_a
            processed += 1
            if season_traj is not None:
                season_traj[h].append(TrajectoryPoint(r["game_id"], r["gameday"], new_h))
                season_traj[a].append(TrajectoryPoint(r["game_id"], r["gameday"], new_a))
        if season_traj is not None:
            traj[season] = season_traj
    return Result(state, preds, traj, processed)


def model_seasons(rows: dict[int, list[dict]]) -> list[int]:
    seasons = sorted(rows)
    if seasons != list(range(seasons[0], seasons[-1] + 1)):
        raise FileNotFoundError("NFL seasons are not consecutive; re-run app.nfl.pipeline ingest")
    return seasons
