"""NFL validation grid search (methodology/NFL.md §4–§6).

Scores every §5 grid cell on 2015–2021. Test seasons (2022–2025) are named
but never loaded: rows are cut at the last validation season before any
replay.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Sequence

from .. import metrics
from . import backtest, ratings

WARMUP_SEASONS = list(range(1999, 2015))
VALIDATION_SEASONS = list(range(2015, 2022))
TEST_SEASONS_DO_NOT_TOUCH = [2022, 2023, 2024, 2025]
LAST_VALIDATION = VALIDATION_SEASONS[-1]

GRID = {
    "k_regular": [10.0, 15.0, 20.0, 25.0, 30.0, 40.0],
    "k_playoff": [10.0, 20.0, 30.0, 40.0],
    "carry": [0.50, 0.60, 0.67, 0.75, 0.85],
    "home_bump": [0.0, 20.0, 35.0, 50.0, 65.0, 80.0],
    "mov": [False, True],
}


def grid_points() -> list[ratings.Params]:
    keys = list(GRID)
    return [ratings.Params(**dict(zip(keys, c))) for c in itertools.product(*GRID.values())]


def load_rows() -> dict[int, list[dict]]:
    rows = backtest.rows_by_season(through=LAST_VALIDATION)
    assert not set(rows) & set(TEST_SEASONS_DO_NOT_TOUCH)
    return rows


def score(probs: Sequence[float], actuals: Sequence[float]) -> dict:
    return {
        "n": len(probs),
        "log_loss": metrics.log_loss(probs, actuals),
        "brier": metrics.brier_score(probs, actuals),
        "ece": metrics.expected_calibration_error(probs, actuals),
    }


def home_rate(preds: Sequence[backtest.Prediction]) -> float:
    games = [p for p in preds if not p.neutral]
    return sum(p.outcome for p in games) / len(games)


def home_rate_probs(preds, rate: float) -> list[float]:
    return [0.5 if p.neutral else rate for p in preds]


def static_probs(preds, frozen: dict[str, float], home_bump: float) -> list[float]:
    return [
        ratings.win_probability(frozen.get(p.home, 1500.0), frozen.get(p.away, 1500.0),
                                home_bump=home_bump, neutral=p.neutral)
        for p in preds
    ]


@dataclass(frozen=True)
class Row:
    params: ratings.Params
    model: dict
    static: dict

    def sort_key(self) -> tuple:
        return (self.model["log_loss"], self.model["ece"], self.model["brier"])

    def to_dict(self) -> dict:
        return {**asdict(self.params), "model": self.model, "static_baseline": self.static}


def evaluate(params: ratings.Params, rows) -> tuple[Row, list[backtest.Prediction]]:
    seasons = backtest.model_seasons(rows)
    full = backtest.run(seasons, params, rows=rows, record_predictions_for=set(VALIDATION_SEASONS))
    warm = backtest.run([s for s in seasons if s in WARMUP_SEASONS], params, rows=rows)
    preds = full.predictions
    actuals = [p.outcome for p in preds]
    return Row(params,
               score([p.home_win_prob for p in preds], actuals),
               score(static_probs(preds, warm.ratings, params.home_bump), actuals)), preds


def grid_search(rows=None) -> list[Row]:
    rows = rows or load_rows()
    out = [evaluate(p, rows)[0] for p in grid_points()]
    out.sort(key=Row.sort_key)
    return out
