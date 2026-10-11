"""MLB validation grid (methodology/MLB.md §4–§6). Test seasons (2022–2025)
are never loaded. The static baseline is computed for the winner only (a
cost optimization; it doesn't affect selection, which is by model LL).
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Sequence

from .. import metrics
from . import backtest, ratings

WARMUP_SEASONS = list(range(2000, 2015))
VALIDATION_SEASONS = list(range(2015, 2022))
TEST_SEASONS_DO_NOT_TOUCH = [2022, 2023, 2024, 2025]
LAST_VALIDATION = VALIDATION_SEASONS[-1]

GRID = {
    "k_regular": [2.0, 4.0, 6.0, 8.0],
    "k_playoff": [2.0, 4.0, 6.0, 8.0],
    "carry": [0.50, 0.60, 0.70, 0.80],
    "home_bump": [0.0, 15.0, 25.0, 35.0, 50.0],
    "mov": [False, True],
    "c": [0.0, 3.0, 4.7, 6.0],
    "alpha": [0.1, 0.2],
}


def grid_points() -> list[ratings.Params]:
    keys = list(GRID)
    pts = [ratings.Params(**dict(zip(keys, v))) for v in itertools.product(*GRID.values())]
    return pts  # 5,120 cells (α is inert when c = 0 but kept so the grid matches §5 exactly)


def load_data():
    seasons = WARMUP_SEASONS + VALIDATION_SEASONS
    assert not set(seasons) & set(TEST_SEASONS_DO_NOT_TOUCH)
    return seasons, backtest.load(seasons)


def score(probs: Sequence[float], ys: Sequence[float]) -> dict:
    return {"n": len(probs), "log_loss": metrics.log_loss(probs, ys),
            "brier": metrics.brier_score(probs, ys), "ece": metrics.expected_calibration_error(probs, ys)}


def home_rate(preds) -> float:
    g = [p for p in preds if not p.neutral]
    return sum(p.outcome for p in g) / len(g)


def home_rate_probs(preds, rate: float) -> list[float]:
    return [0.5 if p.neutral else rate for p in preds]


def static_probs(preds, frozen: dict[int, float], home_bump: float) -> list[float]:
    return [ratings.win_probability(frozen.get(p.home_id, 1500.0), frozen.get(p.away_id, 1500.0),
                                    home_bump=home_bump, neutral=p.neutral) for p in preds]


@dataclass(frozen=True)
class Row:
    params: ratings.Params
    model: dict

    def sort_key(self):
        return (self.model["log_loss"], self.model["ece"], self.model["brier"])

    def to_dict(self):
        return {**asdict(self.params), "model": self.model}


def evaluate(params, seasons, data):
    res = backtest.run(seasons, params, data=data, record_predictions_for=set(VALIDATION_SEASONS))
    preds = res.predictions
    return Row(params, score([p.home_win_prob for p in preds], [p.outcome for p in preds])), preds


def grid_search(seasons, data, *, progress=False) -> list[Row]:
    pts = grid_points()
    out = []
    for i, p in enumerate(pts, 1):
        out.append(evaluate(p, seasons, data)[0])
        if progress and i % 256 == 0:
            print(f"  {i}/{len(pts)}", flush=True)
    out.sort(key=Row.sort_key)
    return out
