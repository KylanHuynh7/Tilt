"""Smoke tests for the tuner. Full grid-search isn't tested here — its
correctness is the §6 metrics + the backtest engine, both covered in their
own tests. We just verify the wiring: a one-cell grid runs end-to-end and
produces sane numbers.
"""

import math

import pytest

from app import pipeline, tuner


pytestmark = pytest.mark.skipif(
    not (pipeline.RAW_DIR / "19671968.parquet").exists(),
    reason="requires Phase A ingest to have run",
)


def test_evaluate_one_runs_and_returns_finite_metrics():
    gp = tuner.GridPoint(k_regular=6.0, k_playoff=10.0, decay_carry=0.75)
    row = tuner.evaluate_one(gp)

    assert row.grid_point == gp
    assert row.n_predictions > 1000  # validation = 2 full seasons
    assert math.isfinite(row.brier)
    assert math.isfinite(row.log_loss)
    assert math.isfinite(row.ece)
    # Sanity bands: anything wildly outside these means a wiring bug.
    assert 0.10 < row.brier < 0.30
    assert 0.45 < row.log_loss < 0.80
    assert 0.0 <= row.ece < 0.20

    # Static baseline should also be finite.
    assert math.isfinite(row.static_baseline_brier)
    assert math.isfinite(row.static_baseline_log_loss)


def test_grid_search_two_cells_picks_better_log_loss():
    grid = [
        tuner.GridPoint(k_regular=6.0, k_playoff=10.0, decay_carry=0.75),
        tuner.GridPoint(k_regular=20.0, k_playoff=30.0, decay_carry=0.10),
    ]
    report = tuner.grid_search(grid, verbose=False)
    assert len(report.rows) == 2
    # Winner must be the row with the lowest log-loss.
    assert report.best.log_loss == min(r.log_loss for r in report.rows)


def test_default_grid_has_expected_shape():
    # 5 × 4 × 5 = 100 cells (K_regular × K_playoff × decay_carry).
    assert len(tuner.DEFAULT_GRID) == 100


def test_test_seasons_constant_is_documented_not_referenced():
    # §10 #1 quarantine: the test seasons exist as a list for documentation
    # but the public API surface never accepts them as input.
    assert tuner.TEST_SEASONS_DO_NOT_TOUCH == [20232024, 20242025]
    assert 20232024 not in tuner.TRAINING_SEASONS
    assert 20232024 not in tuner.VALIDATION_SEASONS
    assert 20242025 not in tuner.TRAINING_SEASONS
    assert 20242025 not in tuner.VALIDATION_SEASONS
