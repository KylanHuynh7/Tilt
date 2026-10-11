"""NFL v1.1 live win probability (methodology/NFL.md §12, v1.1).

    logit P = β0 + β1·pre·(τ/3600) + β2·d/√(m+1)
              + β3·s·(1 − y/100)/√(m+1) + β4·s/√(m+1)

    pre = logit of the frozen pre-game P(home wins); τ = seconds left in
    regulation (OT: in the OT period); m = τ/60; d = home − away score;
    s = +1 home ball, −1 away ball, 0 neither; y = yards to the end zone.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..core.logistic import fit as logistic_fit, sigmoid
from . import backtest, pbp, ratings
from .api import load_params

ARTIFACT = Path(__file__).resolve().parents[2] / "artifacts" / "nfl" / "live_wp_v1.json"
REGULATION_S = 3600
QUARTER_S = 900


@dataclass(frozen=True)
class Sample:
    game_id: str
    qtr: int
    tau: float
    pre: float
    d: int
    s: int
    y: int
    outcome: float  # 1 / 0.5 / 0

    def x(self) -> list[float]:
        return features(self.pre, self.tau, self.d, self.s, self.y)


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def tau_for(qtr: int, qsr: float) -> float:
    return (4 - qtr) * QUARTER_S + qsr if qtr <= 4 else qsr


def features(pre: float, tau: float, d: float, s: int, y: float) -> list[float]:
    root = math.sqrt(tau / 60.0 + 1.0)
    return [1.0, pre * tau / REGULATION_S, d / root, s * (1 - y / 100.0) / root, s / root]


def predict(beta: Sequence[float], *, pre_game_p: float, qtr: int, qsr: float, d: int,
            s: int = 0, y: int = 50) -> float:
    x = features(logit(pre_game_p), tau_for(qtr, qsr), d, s, y)
    return sigmoid(sum(b * v for b, v in zip(beta, x)))


def pregame_predictions(seasons: Sequence[int]) -> dict[str, backtest.Prediction]:
    params = load_params()
    rows = backtest.rows_by_season(through=max(seasons))
    res = backtest.run(backtest.model_seasons(rows), params, rows=rows, record_predictions_for=set(seasons))
    return {p.game_id: p for p in res.predictions}


def build_samples(seasons: Sequence[int], pre: dict[str, backtest.Prediction]) -> list[Sample]:
    out = []
    for season in seasons:
        for r in pbp.read_season(season):
            p = pre.get(r["game_id"])
            if p is None:
                continue
            out.append(Sample(r["game_id"], r["qtr"], tau_for(r["qtr"], r["qsr"]), logit(p.home_win_prob),
                              r["home_score"] - r["away_score"], r["home_poss"], r["yardline_100"], p.outcome))
    return out


def fit(samples: Sequence[Sample]) -> list[float]:
    return logistic_fit([s.x() for s in samples], [s.outcome for s in samples])


def checks(beta: Sequence[float], pre_game_ps: Sequence[float]) -> dict:
    """§12 structural checks (v1.1 definitions)."""
    lo, hi = min(pre_game_ps), max(pre_game_ps)
    grid = [lo + (hi - lo) * i / 50 for i in range(51)]
    kickoff_gap = max(abs(predict(beta, pre_game_p=p, qtr=1, qsr=900, d=0) - p) for p in grid)
    worst = 1.0
    for p in grid:
        for s in (-1, 0, 1):
            for y in range(1, 100, 2):
                worst = min(worst,
                            predict(beta, pre_game_p=p, qtr=4, qsr=120, d=17, s=s, y=y),
                            1 - predict(beta, pre_game_p=p, qtr=4, qsr=120, d=-17, s=s, y=y))
    return {
        "pre_game_p_range": [round(lo, 4), round(hi, 4)],
        "kickoff_max_abs_gap_to_pregame": kickoff_gap,
        "kickoff_within_0_02": kickoff_gap <= 0.02,
        "monotone_in_score_diff": beta[2] > 0,
        "leader_by_17_with_2_min_left_min_wp": worst,
        "leader_by_17_with_2_min_left_ge_0_97": worst >= 0.97,
    }


def save(beta: Sequence[float], payload: dict) -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps({
        "methodology_version": "nfl-1.1",
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "coefficients": dict(zip(["b0", "b1", "b2", "b3", "b4"], beta)),
        **payload,
    }, indent=2))


_beta: list[float] | None = None


def load() -> list[float]:
    global _beta
    if _beta is None:
        c = json.loads(ARTIFACT.read_text())["coefficients"]
        _beta = [c[k] for k in ("b0", "b1", "b2", "b3", "b4")]
    return _beta
