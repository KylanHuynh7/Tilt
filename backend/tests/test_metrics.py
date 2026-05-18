"""Tests for the §6 scoring metrics. Boundary cases matter more than typical
values because the metrics' numeric correctness drives every downstream
methodology claim.
"""

import math

import pytest

from app import metrics


# ---- brier ---------------------------------------------------------------------

def test_brier_perfect_predictor_is_zero():
    assert metrics.brier_score([1.0, 0.0, 1.0, 0.0], [1, 0, 1, 0]) == 0.0


def test_brier_worst_predictor_is_one():
    assert metrics.brier_score([0.0, 1.0], [1, 0]) == 1.0


def test_brier_naive_50_50_on_random_outcomes_is_0_25():
    probs = [0.5] * 100
    actuals = [1.0 if i % 2 == 0 else 0.0 for i in range(100)]
    assert metrics.brier_score(probs, actuals) == 0.25


def test_brier_length_mismatch_raises():
    with pytest.raises(ValueError):
        metrics.brier_score([0.5], [0, 1])


def test_brier_empty_raises():
    with pytest.raises(ValueError):
        metrics.brier_score([], [])


# ---- log loss ------------------------------------------------------------------

def test_log_loss_naive_baseline_is_ln_2():
    probs = [0.5] * 50
    actuals = [1.0] * 25 + [0.0] * 25
    assert math.isclose(metrics.log_loss(probs, actuals), math.log(2.0), abs_tol=1e-12)


def test_log_loss_perfect_predictor_is_zero_after_clipping():
    # Perfect probability of 1 on actual=1 collapses to ~0 after clip.
    result = metrics.log_loss([1.0, 0.0], [1, 0])
    assert result < 1e-13


def test_log_loss_clips_extreme_values_safely():
    # No log(0) error — clipping keeps us finite even at the boundaries.
    result = metrics.log_loss([1.0, 0.0], [0, 1])
    assert math.isfinite(result)
    assert result > 30  # ~ -log(EPS)


def test_log_loss_handles_known_pair():
    # Predicted p=0.7 on actual=1, and p=0.3 on actual=0.
    # Loss = -(log(0.7) + log(0.7)) / 2 = -log(0.7)
    result = metrics.log_loss([0.7, 0.3], [1, 0])
    assert math.isclose(result, -math.log(0.7), abs_tol=1e-12)


# ---- ECE ----------------------------------------------------------------------

def test_ece_perfect_calibration_is_zero():
    # If predicted probability matches actual rate within each bucket.
    probs = [0.1] * 100 + [0.9] * 100
    actuals = [0.0] * 90 + [1.0] * 10 + [0.0] * 10 + [1.0] * 90
    assert metrics.expected_calibration_error(probs, actuals) < 0.01


def test_ece_perfectly_miscalibrated_high():
    # Predict 0.9, actual rate 0.1 → bucket ECE ≈ 0.8 weighted by 100%.
    probs = [0.9] * 100
    actuals = [1.0] * 10 + [0.0] * 90
    ece = metrics.expected_calibration_error(probs, actuals)
    assert math.isclose(ece, 0.8, abs_tol=1e-6)


def test_calibration_buckets_partition_correctly():
    probs = [0.05, 0.15, 0.95]
    actuals = [0, 0, 1]
    buckets = metrics.calibration_buckets(probs, actuals, n_buckets=10, min_count=0)
    assert len(buckets) == 10
    # 0.05 → bucket 0, 0.15 → bucket 1, 0.95 → bucket 9
    assert buckets[0].n == 1
    assert buckets[1].n == 1
    assert buckets[9].n == 1
    # Empty buckets in between.
    assert sum(b.n for b in buckets) == 3


def test_calibration_bucket_at_exactly_one():
    # The last bucket must include probability == 1.0 (edge case).
    buckets = metrics.calibration_buckets([1.0], [1], n_buckets=10, min_count=0)
    assert buckets[9].n == 1


# ---- baselines -----------------------------------------------------------------

def test_naive_baseline_is_all_halves():
    assert metrics.naive_baseline_probs(5) == [0.5, 0.5, 0.5, 0.5, 0.5]


def test_actuals_from_predictions_maps_scores():
    # Use minimal struct duck-typed via a dataclass; Prediction lives in backtest.
    from app.backtest import Prediction
    from datetime import date

    p_home_won = Prediction(
        game_id=1, season_id=20212022, game_date=date(2021, 10, 12),
        home_franchise="boston_bruins", away_franchise="montreal_canadiens",
        home_rating_before=1500.0, away_rating_before=1500.0,
        home_win_prob=0.5,
        home_outcome="REG_WIN", away_outcome="REG_LOSS",
        home_score=3, away_score=2, is_playoff=False,
    )
    p_away_won = Prediction(
        game_id=2, season_id=20212022, game_date=date(2021, 10, 13),
        home_franchise="x", away_franchise="y",
        home_rating_before=1500.0, away_rating_before=1500.0,
        home_win_prob=0.5,
        home_outcome="REG_LOSS", away_outcome="REG_WIN",
        home_score=1, away_score=4, is_playoff=False,
    )
    actuals = metrics.actuals_from_predictions([p_home_won, p_away_won])
    assert actuals == [1.0, 0.0]


def test_static_rating_probs_uses_frozen_state_not_in_prediction():
    from app.backtest import Prediction
    from datetime import date
    pred = Prediction(
        game_id=1, season_id=20212022, game_date=date(2021, 10, 12),
        home_franchise="strong", away_franchise="weak",
        home_rating_before=1400.0,  # whatever was in the live prediction
        away_rating_before=1600.0,
        home_win_prob=0.10,  # live prediction said home loses
        home_outcome="REG_LOSS", away_outcome="REG_WIN",
        home_score=1, away_score=4, is_playoff=False,
    )
    # But our FROZEN end-of-training state has the strong team much higher.
    frozen = {"strong": 1650.0, "weak": 1450.0}
    probs = metrics.static_rating_probs([pred], frozen)
    assert probs[0] > 0.5  # static prediction says strong wins
