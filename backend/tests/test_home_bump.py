"""Tests for the v2.0 §12 home-ice bump.

These cover the small, sharp behaviors:
  - The default value (0.0) makes v2 win_probability identical to v1.
  - A positive bump shifts P(home wins) upward by a known amount.
  - The bump flows through BacktestParams into the engine's predictions.
  - Loading a v1 artifact (no home_bump field) defaults to 0.0.
"""

import json
import math
from pathlib import Path

import pytest

from app import backtest, historical, pipeline
from app.ratings import HOME_BUMP_DEFAULT, win_probability


def test_default_home_bump_is_zero():
    assert HOME_BUMP_DEFAULT == 0.0


def test_win_probability_with_zero_bump_matches_v1():
    # Reproduces the v1 reg test exactly: 400-pt gap → 10/11 win prob.
    assert math.isclose(win_probability(1900.0, 1500.0), 10.0 / 11.0, rel_tol=1e-6)
    # And the equal-rating case is still 0.5 with no bump.
    assert win_probability(1500.0, 1500.0) == 0.5


def test_positive_bump_favors_home_at_equal_ratings():
    p = win_probability(1500.0, 1500.0, home_bump=40.0)
    assert p > 0.5
    expected = 1.0 / (1.0 + 10.0 ** (-40.0 / 400.0))
    assert math.isclose(p, expected, rel_tol=1e-12)


def test_backtest_params_default_home_bump_is_zero():
    p = backtest.BacktestParams()
    assert p.home_bump == 0.0


def test_backtest_params_accepts_home_bump():
    p = backtest.BacktestParams(home_bump=50.0)
    assert p.home_bump == 50.0


@pytest.mark.skipif(
    not (pipeline.RAW_DIR / "20242025.parquet").exists(),
    reason="requires Phase A ingest",
)
def test_backtest_with_home_bump_shifts_predictions_toward_home():
    """End-to-end: run a recent season with and without a home bump; the
    average home-team win probability should be higher with the bump.
    """
    no_bump = backtest.run(
        [20242025],
        params=backtest.BacktestParams(home_bump=0.0),
        record_predictions_for={20242025},
    )
    with_bump = backtest.run(
        [20242025],
        params=backtest.BacktestParams(home_bump=50.0),
        record_predictions_for={20242025},
    )
    assert len(no_bump.predictions) == len(with_bump.predictions)
    avg_no = sum(p.home_win_prob for p in no_bump.predictions) / len(no_bump.predictions)
    avg_yes = sum(p.home_win_prob for p in with_bump.predictions) / len(with_bump.predictions)
    assert avg_no < avg_yes
    # +50 bump ≈ 7% absolute home-WP shift on average.
    assert 0.04 < (avg_yes - avg_no) < 0.10


def test_historical_load_v1_artifact_defaults_home_bump_to_zero(tmp_path: Path):
    v1_artifact = {
        "methodology_version": "1.2",
        "frozen_at": "2026-05-18T03:36:59Z",
        "winner": {
            "k_regular": 10.0,
            "k_playoff": 10.0,
            "decay_carry": 0.85,
        },
    }
    path = tmp_path / "frozen_params.json"
    path.write_text(json.dumps(v1_artifact))
    params = historical.load_frozen_params(path)
    assert params.home_bump == 0.0
    assert params.k_regular == 10.0


def test_historical_load_v2_artifact_honors_home_bump(tmp_path: Path):
    v2_artifact = {
        "methodology_version": "2.0",
        "frozen_at": "2026-05-18T20:00:00Z",
        "winner": {
            "k_regular": 10.0,
            "k_playoff": 10.0,
            "decay_carry": 0.85,
            "home_bump": 40.0,
        },
    }
    path = tmp_path / "frozen_params.json"
    path.write_text(json.dumps(v2_artifact))
    params = historical.load_frozen_params(path)
    assert params.home_bump == 40.0
