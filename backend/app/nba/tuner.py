"""NBA validation grid search (methodology/NBA.md §4–§6).

Scores every §5 grid cell on the validation seasons only. The test seasons
are named here so other modules can refer to them, but this module never
loads them: every replay stops at the last validation season.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Sequence

from .. import metrics
from . import backtest, ratings

VALIDATION_SEASONS: list[int] = [20182019, 20192020, 20202021, 20212022, 20222023, 20232024]
TEST_SEASONS_DO_NOT_TOUCH: list[int] = [20242025, 20252026]
LAST_VALIDATION = VALIDATION_SEASONS[-1]

GRID = {
    "k_regular": [10.0, 15.0, 20.0, 25.0, 30.0],
    "k_playoff": [10.0, 15.0, 20.0, 25.0, 30.0],
    "carry": [0.55, 0.65, 0.75, 0.85],
    "home_bump": [0.0, 40.0, 60.0, 80.0, 100.0, 120.0],
    "mov": [False, True],
}


def grid_points() -> list[ratings.Params]:
    keys = list(GRID)
    return [ratings.Params(**dict(zip(keys, combo))) for combo in itertools.product(*GRID.values())]


def warmup_seasons() -> list[int]:
    return [s for s in backtest.model_seasons(through=LAST_VALIDATION) if s < VALIDATION_SEASONS[0]]


def load_rows() -> dict[int, list[dict]]:
    """Warm-up + validation rows, loaded once. Refuses to include test seasons."""
    seasons = backtest.model_seasons(through=LAST_VALIDATION)
    assert not set(seasons) & set(TEST_SEASONS_DO_NOT_TOUCH)
    return {s: backtest.model_rows(s) for s in seasons}


def score(probs: Sequence[float], actuals: Sequence[float]) -> dict:
    return {
        "n": len(probs),
        "log_loss": metrics.log_loss(probs, actuals),
        "brier": metrics.brier_score(probs, actuals),
        "ece": metrics.expected_calibration_error(probs, actuals),
    }


def home_rate(predictions: Sequence[backtest.Prediction]) -> float:
    """Home win rate over non-neutral games — the §6 home-rate baseline's constant."""
    games = [p for p in predictions if not p.neutral]
    return sum(p.home_won for p in games) / len(games)


def home_rate_probs(predictions: Sequence[backtest.Prediction], rate: float) -> list[float]:
    return [0.5 if p.neutral else rate for p in predictions]


def static_probs(
    predictions: Sequence[backtest.Prediction], frozen: dict[int, float], home_bump: float
) -> list[float]:
    """§6 static-rating baseline: end-of-warm-up ratings held fixed."""
    return [
        ratings.win_probability(
            frozen.get(p.home_team_id, ratings.INITIAL_RATING),
            frozen.get(p.away_team_id, ratings.INITIAL_RATING),
            home_bump=home_bump, neutral=p.neutral,
        )
        for p in predictions
    ]


@dataclass(frozen=True)
class Row:
    params: ratings.Params
    model: dict
    static: dict

    def sort_key(self) -> tuple:
        # §5: lowest log-loss, ties by ECE then Brier (inherits NHL rule).
        return (self.model["log_loss"], self.model["ece"], self.model["brier"])

    def to_dict(self) -> dict:
        return {**asdict(self.params), "model": self.model, "static_baseline": self.static}


def evaluate(params: ratings.Params, rows: dict[int, list[dict]]) -> tuple[Row, list[backtest.Prediction]]:
    seasons = sorted(rows)
    full = backtest.run(seasons, params, record_predictions_for=set(VALIDATION_SEASONS),
                        rows_by_season=rows)
    warm = backtest.run([s for s in seasons if s < VALIDATION_SEASONS[0]], params,
                        rows_by_season=rows)
    preds = full.predictions
    actuals = [1.0 if p.home_won else 0.0 for p in preds]
    model = score([p.home_win_prob for p in preds], actuals)
    static = score(static_probs(preds, warm.ratings, params.home_bump), actuals)
    return Row(params, model, static), preds


def grid_search(rows: dict[int, list[dict]] | None = None, *, progress: bool = False) -> list[Row]:
    rows = rows or load_rows()
    out: list[Row] = []
    points = grid_points()
    for i, params in enumerate(points, 1):
        out.append(evaluate(params, rows)[0])
        if progress and i % 100 == 0:
            print(f"  {i}/{len(points)} cells", flush=True)
    out.sort(key=Row.sort_key)
    return out
