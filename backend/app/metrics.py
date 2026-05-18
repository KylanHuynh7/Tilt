"""Scoring metrics for win-probability predictions, per METHODOLOGY.md §6.

Each function takes parallel sequences of predicted probabilities (in [0, 1])
and binary actual outcomes (0 or 1, home perspective). Higher-rated baselines
and naive baselines are also defined here so all model-vs-baseline comparisons
share one implementation.

Per §10 #5, no metric is omitted in the final report — log-loss, Brier, and
ECE are all reported regardless of which is most flattering. This module is
the single source of truth for those numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

# Probabilities are clipped to [EPS, 1-EPS] before log-loss so log(0) is never
# evaluated. EPS = 1e-15 follows the scikit-learn default.
EPS = 1e-15


def brier_score(probs: Sequence[float], actuals: Sequence[float]) -> float:
    """Mean squared error between predicted probability and actual outcome.

    Lower is better. 0.25 is the score of always predicting 0.5.
    Range: [0, 1].
    """
    if not probs:
        raise ValueError("empty probs")
    if len(probs) != len(actuals):
        raise ValueError(f"length mismatch: {len(probs)} vs {len(actuals)}")
    return sum((p - a) ** 2 for p, a in zip(probs, actuals)) / len(probs)


def log_loss(probs: Sequence[float], actuals: Sequence[float]) -> float:
    """Negative log-likelihood per game. Lower is better.

    The §6 baseline for an uninformed predictor (p=0.5) is ln(2) ≈ 0.6931.
    Beating 0.685 represents meaningful improvement.
    """
    if not probs:
        raise ValueError("empty probs")
    if len(probs) != len(actuals):
        raise ValueError(f"length mismatch: {len(probs)} vs {len(actuals)}")
    total = 0.0
    for p, a in zip(probs, actuals):
        p_clipped = min(max(p, EPS), 1.0 - EPS)
        total += a * math.log(p_clipped) + (1.0 - a) * math.log(1.0 - p_clipped)
    return -total / len(probs)


@dataclass(frozen=True)
class CalibrationBucket:
    lo: float
    hi: float
    n: int
    mean_predicted: float
    mean_actual: float


def calibration_buckets(
    probs: Sequence[float],
    actuals: Sequence[float],
    *,
    n_buckets: int = 10,
    min_count: int = 30,
) -> list[CalibrationBucket]:
    """Bucket predictions by predicted probability and report mean predicted
    vs mean actual in each bucket.

    Buckets are equal-width over [0, 1]. Buckets with fewer than `min_count`
    predictions are returned but should be excluded from the published
    calibration plot per §9 stopping criterion #6.
    """
    if n_buckets < 1:
        raise ValueError("n_buckets must be >= 1")
    if len(probs) != len(actuals):
        raise ValueError(f"length mismatch: {len(probs)} vs {len(actuals)}")
    width = 1.0 / n_buckets
    rows: list[CalibrationBucket] = []
    for i in range(n_buckets):
        lo = i * width
        hi = (i + 1) * width if i < n_buckets - 1 else 1.0 + 1e-12
        # Inclusive on lo, exclusive on hi — except last bucket includes 1.0.
        bucket_probs = []
        bucket_actuals = []
        for p, a in zip(probs, actuals):
            if lo <= p < hi:
                bucket_probs.append(p)
                bucket_actuals.append(a)
        n = len(bucket_probs)
        mp = sum(bucket_probs) / n if n else 0.0
        ma = sum(bucket_actuals) / n if n else 0.0
        rows.append(CalibrationBucket(lo=lo, hi=min(hi, 1.0), n=n,
                                       mean_predicted=mp, mean_actual=ma))
    return rows


def expected_calibration_error(
    probs: Sequence[float],
    actuals: Sequence[float],
    *,
    n_buckets: int = 10,
) -> float:
    """Weighted mean of |mean_predicted - mean_actual| across buckets.

    Target per §6: < 0.04.
    """
    n_total = len(probs)
    if n_total == 0:
        raise ValueError("empty probs")
    buckets = calibration_buckets(probs, actuals, n_buckets=n_buckets, min_count=0)
    return sum(
        (b.n / n_total) * abs(b.mean_predicted - b.mean_actual)
        for b in buckets
        if b.n > 0
    )


# ---- Baselines per §6 ----------------------------------------------------------


def naive_baseline_probs(n: int) -> list[float]:
    """Predict 0.5 for every game. The floor; failing to beat it ends evaluation."""
    return [0.5] * n


def actuals_from_predictions(predictions) -> list[float]:
    """Map a list of backtest.Prediction objects to binary home-perspective
    actuals. Home win (any period type) = 1.0, home loss = 0.0.

    Ties are handled as 0.5 — they should never appear in validation/test
    seasons (all post-2005-06) but the function is defensive.
    """
    out: list[float] = []
    for p in predictions:
        if p.home_score > p.away_score:
            out.append(1.0)
        elif p.home_score < p.away_score:
            out.append(0.0)
        else:
            out.append(0.5)
    return out


def static_rating_probs(
    predictions,
    frozen_ratings: dict[str, float],
    *,
    home_bump: float = 0.0,
) -> list[float]:
    """Higher-rated-team baseline per §6: predict using the rating gap from a
    snapshot taken at the end of warm-up, without updating.

    `frozen_ratings` is the rating state at the END of training; every game's
    prediction uses those ratings unchanged. This isolates "does the rating
    system have signal at all?" from "does the update mechanism add value?"

    `home_bump` is the v2.0 §12 home-ice bias. For a fair baseline comparison
    the same bump used by the model is applied to the baseline — otherwise the
    baseline would be doubly penalized (no updates AND no home ice).
    """
    from .ratings import win_probability  # local import avoids circular dep

    out: list[float] = []
    for pred in predictions:
        r_home = frozen_ratings.get(pred.home_franchise, 1500.0)
        r_away = frozen_ratings.get(pred.away_franchise, 1500.0)
        out.append(win_probability(r_home, r_away, home_bump=home_bump))
    return out
