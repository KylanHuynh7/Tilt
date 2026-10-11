"""NBA v1.1 live win probability (methodology/NBA.md §12, v1.2).

    logit P(home wins | state) = β0 + β1 · pre · (τ / 2880) + β2 · d / sqrt(m + 1)

    pre = logit of the frozen pre-game P(home wins)
    τ   = seconds left in regulation; in overtime, seconds left in the OT period
    m   = τ / 60 (minutes remaining)
    d   = home score − away score

Fitted by Newton's method (three coefficients, no numpy needed) on minute-mark
samples from the training seasons only. The test seasons are scored once, by
scripts/nba_live_wp_evaluate.py.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from . import backtest, pbp, ratings

ARTIFACT = Path(__file__).resolve().parents[2] / "artifacts" / "nba" / "live_wp_v1.json"
REGULATION_S = 2880


@dataclass(frozen=True)
class Model:
    b0: float
    b1: float
    b2: float


@dataclass(frozen=True)
class Sample:
    game_id: int
    period: int
    tau: float
    pre: float      # pre-game logit
    d: int
    home_won: bool

    def features(self) -> tuple[float, float]:
        return features(self.pre, self.tau, self.d)


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def tau_for(period: int, sec_left: float) -> float:
    """§12: seconds left in regulation; overtime is its own short period."""
    if period <= 4:
        return (4 - period) * pbp.QUARTER_S + sec_left
    return sec_left


def features(pre: float, tau: float, d: float) -> tuple[float, float]:
    m = tau / 60.0
    return pre * (tau / REGULATION_S), d / math.sqrt(m + 1.0)


def predict(model: Model, *, pre_game_p: float, period: int, sec_left: float, d: int) -> float:
    x1, x2 = features(logit(pre_game_p), tau_for(period, sec_left), d)
    return sigmoid(model.b0 + model.b1 * x1 + model.b2 * x2)


# ---- Samples -------------------------------------------------------------------

def pregame_predictions(seasons: Sequence[int]) -> dict[int, backtest.Prediction]:
    """Frozen-model pre-game predictions for `seasons`, from a walk-forward
    replay through the last of them (no later season is loaded).
    """
    from ..nba.api import _load_params  # frozen artifact loader, 503-free here

    params, _ = _load_params()
    replay = backtest.model_seasons(through=max(seasons))
    res = backtest.run(replay, params, record_predictions_for=set(seasons))
    return {p.game_id: p for p in res.predictions}


def build_samples(seasons: Iterable[int], pre: dict[int, backtest.Prediction]) -> list[Sample]:
    out = []
    for sid in seasons:
        for r in pbp.read_season(sid):
            p = pre.get(r["game_id"])
            if p is None:
                continue
            out.append(Sample(
                game_id=r["game_id"], period=r["period"],
                tau=tau_for(r["period"], r["sec_left"]),
                pre=logit(p.home_win_prob), d=r["home_score"] - r["away_score"],
                home_won=p.home_won,
            ))
    return out


# ---- Fit -----------------------------------------------------------------------

def fit(samples: Sequence[Sample], *, iterations: int = 25, tol: float = 1e-10) -> Model:
    """Maximum-likelihood logistic regression by Newton's method."""
    xs = [(1.0, *s.features()) for s in samples]
    ys = [1.0 if s.home_won else 0.0 for s in samples]
    b = [0.0, 0.0, 0.0]
    for _ in range(iterations):
        g = [0.0, 0.0, 0.0]
        h = [[0.0] * 3 for _ in range(3)]
        for x, y in zip(xs, ys):
            p = sigmoid(b[0] * x[0] + b[1] * x[1] + b[2] * x[2])
            w = p * (1 - p)
            r = y - p
            for i in range(3):
                g[i] += r * x[i]
                for j in range(i, 3):
                    h[i][j] += w * x[i] * x[j]
        for i in range(3):
            for j in range(i):
                h[i][j] = h[j][i]
        step = _solve3(h, g)
        b = [b[i] + step[i] for i in range(3)]
        if max(abs(s) for s in step) < tol:
            break
    return Model(*b)


def _solve3(a: list[list[float]], v: list[float]) -> list[float]:
    """Solve a 3×3 linear system by Cramer's rule."""
    def det(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    d = det(a)
    out = []
    for k in range(3):
        m = [row[:] for row in a]
        for i in range(3):
            m[i][k] = v[i]
        out.append(det(m) / d)
    return out


# ---- §12 pre-registered checks ---------------------------------------------------

def checks(model: Model, pre_game_ps: Sequence[float]) -> dict:
    """The three §12 checks, evaluated over the range of pre-game probabilities
    the model actually sees.
    """
    lo, hi = min(pre_game_ps), max(pre_game_ps)
    grid = [lo + (hi - lo) * i / 50 for i in range(51)]
    tip_gap = max(abs(predict(model, pre_game_p=p, period=1, sec_left=720, d=0) - p) for p in grid)
    # Leader with |d| = 20 and m = 2 (τ = 120), worst case = leader was the
    # biggest pre-game underdog. By symmetry check the home side only.
    worst_leader = min(predict(model, pre_game_p=p, period=4, sec_left=120, d=20) for p in grid)
    worst_trailer = max(predict(model, pre_game_p=p, period=4, sec_left=120, d=-20) for p in grid)
    return {
        "pre_game_p_range": [round(lo, 4), round(hi, 4)],
        "tipoff_max_abs_gap_to_pregame": tip_gap,
        "tipoff_within_0_01": tip_gap <= 0.01,
        "monotone_in_score_diff": model.b2 > 0,
        "leader_by_20_with_2_min_left_min_wp": min(worst_leader, 1 - worst_trailer),
        "leader_by_20_with_2_min_left_ge_0_97": min(worst_leader, 1 - worst_trailer) >= 0.97,
    }


def save(model: Model, payload: dict) -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps({
        "methodology_version": "nba-1.2",
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "coefficients": {"b0": model.b0, "b1": model.b1, "b2": model.b2},
        **payload,
    }, indent=2))


_model: Model | None = None


def load() -> Model:
    global _model
    if _model is None:
        c = json.loads(ARTIFACT.read_text())["coefficients"]
        _model = Model(c["b0"], c["b1"], c["b2"])
    return _model
