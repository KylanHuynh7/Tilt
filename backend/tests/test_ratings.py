"""Sanity tests for the Elo-variant rating engine per METHODOLOGY.md v1.1 §5."""

import math

from app.ratings import (
    INITIAL_RATING,
    K_PLAYOFF,
    K_REGULAR,
    OUTCOME_WEIGHTS,
    apply_game,
    win_probability,
)


def test_equal_ratings_give_50_50():
    assert win_probability(1500.0, 1500.0) == 0.5


def test_higher_rating_wins_more_often():
    assert win_probability(1600.0, 1500.0) > 0.5
    assert win_probability(1500.0, 1600.0) < 0.5


def test_400_point_gap_matches_elo_convention():
    # 400-point gap → ~10x odds → ~0.909 win prob; standard Elo invariant.
    assert math.isclose(win_probability(1900.0, 1500.0), 10 / 11, rel_tol=1e-6)


def test_outcome_weights_sum_to_one_for_opposing_results():
    # Each "team A win" weight + the symmetric "team A loss" weight must sum to 1
    # so the league mean stays at 1500 by construction.
    pairs = [
        ("REG_WIN", "REG_LOSS"),
        ("OT_WIN", "OT_LOSS"),
        ("SO_WIN", "SO_LOSS"),
    ]
    for win, loss in pairs:
        assert math.isclose(OUTCOME_WEIGHTS[win] + OUTCOME_WEIGHTS[loss], 1.0)


def test_tie_weight_is_half():
    assert OUTCOME_WEIGHTS["TIE"] == 0.5


def test_zero_sum_update():
    # The two teams' rating changes must be equal and opposite (league mean fixed).
    before_sum = INITIAL_RATING * 2
    u = apply_game(INITIAL_RATING, INITIAL_RATING, "REG_WIN")
    after_sum = u.new_rating_a + u.new_rating_b
    assert math.isclose(before_sum, after_sum, abs_tol=1e-9)


def test_regular_season_k_factor_applied():
    u = apply_game(1500.0, 1500.0, "REG_WIN")
    # Expected: K_REGULAR * (1.0 - 0.5) = 3.0 points to the winner.
    assert math.isclose(u.new_rating_a, 1500.0 + K_REGULAR * 0.5)


def test_playoff_k_factor_applied():
    u = apply_game(1500.0, 1500.0, "REG_WIN", is_playoff=True)
    assert math.isclose(u.new_rating_a, 1500.0 + K_PLAYOFF * 0.5)


def test_tie_produces_no_rating_change_when_evenly_matched():
    u = apply_game(1500.0, 1500.0, "TIE")
    assert math.isclose(u.new_rating_a, 1500.0)
    assert math.isclose(u.new_rating_b, 1500.0)


def test_tie_still_shifts_when_ratings_differ():
    # The favorite "loses" expected value in a tie → small rating drop.
    u = apply_game(1600.0, 1500.0, "TIE")
    assert u.new_rating_a < 1600.0
    assert u.new_rating_b > 1500.0
