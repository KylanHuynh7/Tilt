"""Tests for the v2.2 §15 empirical live-WP model.

Build-time tests use a small synthetic dataset so they don't depend on PBP
ingest. The integration tests skip when the real 2024-25 PBP parquet exists.
"""

import json
import math
from pathlib import Path

import pytest

from app import live_wp, pbp_pipeline


# ---- Pure-function tests (no IO) -----------------------------------------

def test_clamp_score_diff():
    assert live_wp._clamp_score_diff(0) == 0
    assert live_wp._clamp_score_diff(3) == 3
    assert live_wp._clamp_score_diff(7) == live_wp.SCORE_DIFF_CLAMP
    assert live_wp._clamp_score_diff(-7) == -live_wp.SCORE_DIFF_CLAMP


def test_period_bucket():
    assert live_wp._period_bucket(1, "REG") == 1
    assert live_wp._period_bucket(2, "REG") == 2
    assert live_wp._period_bucket(3, "REG") == 3
    assert live_wp._period_bucket(4, "OT") == 4
    assert live_wp._period_bucket(5, "OT") == 4
    assert live_wp._period_bucket(6, "SO") == 4


def test_bin_stats_smoothing_pulls_toward_half():
    # 5 wins / 5 games is 1.0 empirically, but with alpha=50, smoothed is
    # (5+50)/(5+100) = 55/105 ≈ 0.524 — close to 0.5 with thin data.
    s = live_wp.BinStats(n=5, home_wins=5)
    assert math.isclose(s.empirical(), 1.0)
    assert s.smoothed() < 0.6 and s.smoothed() > 0.5


def test_bin_stats_smoothing_does_not_change_with_balanced_data():
    s = live_wp.BinStats(n=200, home_wins=100)
    assert math.isclose(s.empirical(), 0.5)
    assert math.isclose(s.smoothed(), 0.5)


def test_expand_game_handles_zero_goals():
    samples = list(live_wp._expand_game_to_samples(
        game_id=1, goal_rows=[], home_won_final=True,
    ))
    # All bins are 0-0 throughout the game. 3 regulation periods × 20 mins.
    assert len(samples) == 60
    for key, won in samples:
        assert key.score_diff == 0
        assert won is True


def test_expand_game_score_changes_after_goal():
    # Single home goal at time_in_period=720s (12:00 in P1 = 8:00 remaining).
    # Bin coverage convention (per the live_wp implementation):
    #   each mins_remaining bin uses time_remaining_s = mins_remaining*60 + 59
    #   and includes goals with g.time_remaining > that bound.
    # So a goal at g.time_remaining=480 is included starting from
    # mins_remaining=7 (bound=479) downward, NOT in mins_remaining=8 (bound=539).
    goal = {
        "game_id": 1, "period": 1, "period_type": "REG",
        "time_in_period_s": 720, "time_remaining_in_period_s": 480,
        "home_score_after": 1, "away_score_after": 0,
    }
    samples = list(live_wp._expand_game_to_samples(1, [goal], home_won_final=True))
    p1_samples = {k.mins_remaining: k.score_diff for k, _ in samples if k.period == 1}
    # Before the goal: bins at mins_remaining 8..19 show 0.
    for mr in range(8, 20):
        assert p1_samples[mr] == 0, f"mins_remaining {mr} should pre-date the goal"
    # After the goal: bins at mins_remaining 0..7 show +1.
    for mr in range(0, 8):
        assert p1_samples[mr] == 1, f"mins_remaining {mr} should post-date the goal"
    # Later periods inherit the score.
    p2_samples = [k.score_diff for k, _ in samples if k.period == 2]
    assert all(sd == 1 for sd in p2_samples)
    p3_samples = [k.score_diff for k, _ in samples if k.period == 3]
    assert all(sd == 1 for sd in p3_samples)


def test_query_unknown_state_returns_05():
    empty = live_wp.WPModel()
    r = live_wp.query(empty, period=2, time_remaining_s=300, score_diff=0)
    assert r.home_win_prob == 0.5
    assert r.n == 0
    assert r.smoothed is True


def test_artifact_roundtrip(tmp_path: Path):
    # Build a tiny model, write, read back.
    model = live_wp.WPModel(training_seasons=[20242025])
    model.bins[live_wp.BinKey(period=1, mins_remaining=10, score_diff=0)] = \
        live_wp.BinStats(n=200, home_wins=110)
    model.n_games = 50
    model.n_samples = 200
    out = tmp_path / "live_wp_v2.json"
    live_wp.write_artifact(model, out)

    loaded = live_wp.load_artifact(out)
    assert loaded.n_games == 50
    assert len(loaded.bins) == 1
    bin_key = next(iter(loaded.bins))
    assert bin_key == live_wp.BinKey(1, 10, 0)
    assert loaded.bins[bin_key].n == 200
    # Empirical home_win_rate is 0.55; loaded value should be 0.55 within
    # rounding precision (we serialize 4 decimals).
    assert math.isclose(loaded.bins[bin_key].empirical(), 0.55, abs_tol=0.01)


# ---- Integration tests (require PBP data) --------------------------------

pytestmark_integration = pytest.mark.skipif(
    not (pbp_pipeline.PBP_DIR / "20242025.parquet").exists(),
    reason="requires PBP ingest for 2024-25",
)


@pytestmark_integration
def test_build_on_one_season_produces_sensible_counts():
    model = live_wp.build(training_seasons=[20242025])
    # 2024-25 had ~1398 games, ~83k samples expected.
    assert model.n_games > 1000
    assert model.n_samples > 50_000
    assert len(model.bins) > 100


@pytestmark_integration
def test_query_at_game_start_is_close_to_home_win_baseline():
    model = live_wp.build(training_seasons=[20242025])
    r = live_wp.query(model, period=1, time_remaining_s=19 * 60 + 30, score_diff=0)
    # 2024-25 home win rate is approximately 0.55-0.57. Allow a band.
    assert 0.50 <= r.home_win_prob <= 0.62


@pytestmark_integration
def test_monotonic_in_score_diff_at_mid_game_well_sampled_bins():
    """At (period 2, ~10 mins left), bins with n >= SMOOTHING_THRESHOLD should
    be monotone in score_diff.
    """
    model = live_wp.build(training_seasons=[20242025])
    last_wp = -1.0
    for sd in range(-2, 3):  # only well-sampled bins
        r = live_wp.query(model, period=2, time_remaining_s=10 * 60 + 30, score_diff=sd)
        if not r.smoothed:
            assert r.home_win_prob >= last_wp, \
                f"non-monotone: sd={sd} WP={r.home_win_prob} < {last_wp}"
            last_wp = r.home_win_prob
