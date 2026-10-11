"""College football validation grid (methodology/CFB.md §4–§6). Metrics use
FBS-vs-FBS games only (DECISION 2). Test seasons (2022–2025) never loaded.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass

from .. import metrics
from . import backtest, ratings

WARMUP_SEASONS = list(range(2001, 2014))
VALIDATION_SEASONS = list(range(2014, 2022))
TEST_SEASONS_DO_NOT_TOUCH = [2022, 2023, 2024, 2025]
GRID = {
    "k_regular": [20.0, 30.0, 40.0, 50.0], "k_post": [10.0, 20.0, 30.0, 40.0],
    "carry": [0.40, 0.50, 0.60, 0.70], "home_bump": [0.0, 40.0, 60.0, 80.0, 100.0, 120.0],
    "mov": [False, True], "fcs_init": [1100.0, 1200.0, 1300.0],
}


def grid_points():
    keys = list(GRID)
    return [ratings.Params(**dict(zip(keys, v))) for v in itertools.product(*GRID.values())]


def load_data():
    seasons = WARMUP_SEASONS + VALIDATION_SEASONS
    assert not set(seasons) & set(TEST_SEASONS_DO_NOT_TOUCH)
    return seasons, backtest.load(seasons)


def score(probs, ys):
    return {"n": len(probs), "log_loss": metrics.log_loss(probs, ys), "brier": metrics.brier_score(probs, ys),
            "ece": metrics.expected_calibration_error(probs, ys)}


def fbs_only(preds):
    return [p for p in preds if not p.fcs_game]


def home_rate(preds):
    g = [p for p in preds if not p.neutral]
    return sum(p.outcome for p in g) / len(g)


def home_rate_probs(preds, rate):
    return [0.5 if p.neutral else rate for p in preds]


def static_probs(preds, frozen, params):
    return [ratings.win_probability(frozen.get(p.home, params.fcs_init), frozen.get(p.away, params.fcs_init),
                                    home_bump=params.home_bump, neutral=p.neutral) for p in preds]


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
    preds = fbs_only(res.predictions)
    return Row(params, score([p.home_win_prob for p in preds], [p.outcome for p in preds])), preds, res


def grid_search(seasons, data):
    out = [evaluate(p, seasons, data)[0] for p in grid_points()]
    out.sort(key=Row.sort_key)
    return out
