"""Walk-forward NBA backtest (methodology/NBA.md §7, inheriting NHL §7).

Predict-then-update over every valid game in chronological order, from the
first modeled season (`pipeline.first_model_season()`, 2000-01 under v1.1).
Between seasons every existing rating regresses toward 1500 once; a franchise
seen for the first time starts at 1500 with no regression (expansion rule).

This module is evaluation-blind: it records predictions only for the seasons
it's told to, and never scores them. Scoring lives in the tuner (validation)
and the one-shot evaluation script (test).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from . import espn, pipeline, ratings
from .teams import is_franchise

MODEL_SEASON_TYPES = {pipeline.REGULAR: "regular", pipeline.PLAYOFF: "playoff", pipeline.PLAY_IN: "play_in"}


@dataclass(frozen=True)
class Prediction:
    season_id: int
    game_id: int
    game_date: date
    season_type: int
    home_team_id: int
    away_team_id: int
    home_win_prob: float
    home_won: bool
    neutral: bool
    # Regular-season team-game numbers (1-based) at tip-off; None for
    # play-in/playoff games. Used for the §6 season-segment breakdown.
    home_game_no: int | None
    away_game_no: int | None
    season_length: int  # scheduled games per team that season


@dataclass(frozen=True)
class TrajectoryPoint:
    game_id: int
    game_date: date
    rating: float


@dataclass
class Result:
    ratings: dict[int, float]
    predictions: list[Prediction]
    trajectories: dict[int, dict[int, list[TrajectoryPoint]]] = field(default_factory=dict)
    games_processed: int = 0
    seasons: list[int] = field(default_factory=list)


def season_length(season_id: int) -> int:
    """Scheduled games per team (§6 segments scale with this)."""
    return round(2 * pipeline.scheduled_regular_games(season_id) / pipeline.n_teams(season_id))


def model_rows(season_id: int) -> list[dict]:
    """Valid, completed NBA-vs-NBA games of a modeled season type."""
    rows, _ = pipeline.clean_rows(pipeline.read_season(season_id))
    return [
        r for r in rows
        if r["completed"]
        and r["season_type"] in MODEL_SEASON_TYPES
        and is_franchise(r["home_team_id"]) and is_franchise(r["away_team_id"])
        and r["home_score"] is not None and r["away_score"] is not None
    ]


def run(
    seasons: Iterable[int],
    params: ratings.Params,
    *,
    record_predictions_for: set[int] | None = None,
    record_trajectories: bool = False,
    rows_by_season: dict[int, list[dict]] | None = None,
) -> Result:
    """Replay `seasons` (must be consecutive and in order). `rows_by_season`
    lets the tuner load parquets once and reuse them across grid cells.
    """
    record = record_predictions_for or set()
    state: dict[int, float] = {}
    preds: list[Prediction] = []
    traj: dict[int, dict[int, list[TrajectoryPoint]]] = {}
    processed = 0
    seasons = list(seasons)

    for i, sid in enumerate(seasons):
        if i > 0:
            for tid in state:
                state[tid] = ratings.regress(state[tid], params.carry)
        rows = rows_by_season[sid] if rows_by_season is not None else model_rows(sid)
        length = season_length(sid)
        game_no: dict[int, int] = defaultdict(int)
        season_traj: dict[int, list[TrajectoryPoint]] | None = {} if record_trajectories else None

        for r in rows:
            h, a = r["home_team_id"], r["away_team_id"]
            for tid in (h, a):
                state.setdefault(tid, ratings.INITIAL_RATING)  # expansion seed
                if season_traj is not None and tid not in season_traj:
                    # Opening point: the post-regression (or seed) rating.
                    season_traj[tid] = [TrajectoryPoint(0, r["game_date"], state[tid])]

            is_regular = r["season_type"] == pipeline.REGULAR
            if is_regular:
                game_no[h] += 1
                game_no[a] += 1
            neutral = espn.is_neutral(r)
            k = params.k_regular if is_regular else params.k_playoff
            new_h, new_a, p_home = ratings.update(
                state[h], state[a],
                home_score=r["home_score"], away_score=r["away_score"],
                k=k, home_bump=params.home_bump, neutral=neutral, mov=params.mov,
            )
            if sid in record:
                preds.append(Prediction(
                    season_id=sid, game_id=r["game_id"], game_date=r["game_date"],
                    season_type=r["season_type"], home_team_id=h, away_team_id=a,
                    home_win_prob=p_home, home_won=r["home_score"] > r["away_score"],
                    neutral=neutral,
                    home_game_no=game_no[h] if is_regular else None,
                    away_game_no=game_no[a] if is_regular else None,
                    season_length=length,
                ))
            state[h], state[a] = new_h, new_a
            processed += 1
            if season_traj is not None:
                season_traj[h].append(TrajectoryPoint(r["game_id"], r["game_date"], new_h))
                season_traj[a].append(TrajectoryPoint(r["game_id"], r["game_date"], new_a))

        if season_traj is not None:
            traj[sid] = season_traj

    return Result(ratings=state, predictions=preds, trajectories=traj,
                  games_processed=processed, seasons=seasons)


def model_seasons(through: int | None = None) -> list[int]:
    """Every modeled season from `first_model_season()` through `through`
    (default: the latest ingested), consecutive.
    """
    first = pipeline.first_model_season()
    ingested = [s for s in pipeline.ingested_seasons() if s >= first]
    if through is not None:
        ingested = [s for s in ingested if s <= through]
    expected = [y * 10000 + y + 1 for y in range(first // 10000, ingested[-1] // 10000 + 1)]
    if ingested != expected:
        missing = sorted(set(expected) - set(ingested))
        raise FileNotFoundError(f"missing NBA seasons {missing}; run app.nba.pipeline ingest")
    return ingested
