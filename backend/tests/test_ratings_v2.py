"""Tests for the new Phase B primitives in ratings.py: apply_decay and
classify_outcome. The original §5 update primitives are covered in
test_ratings.py.
"""

import math

import pytest

from app.ratings import (
    DECAY_CARRY,
    INITIAL_RATING,
    LEAGUE_MEAN,
    OUTCOME_WEIGHTS,
    TIE_ERA_END,
    apply_decay,
    classify_outcome,
)


# ---- apply_decay ---------------------------------------------------------------

def test_decay_at_mean_is_no_op():
    assert apply_decay(LEAGUE_MEAN) == LEAGUE_MEAN


def test_decay_pulls_high_ratings_back():
    r = apply_decay(1700.0)
    expected = LEAGUE_MEAN + DECAY_CARRY * (1700.0 - LEAGUE_MEAN)
    assert math.isclose(r, expected)
    assert r < 1700.0


def test_decay_pulls_low_ratings_up():
    r = apply_decay(1300.0)
    assert r > 1300.0
    assert r < LEAGUE_MEAN


def test_decay_custom_carry_zero_full_regression():
    assert apply_decay(1800.0, carry=0.0) == LEAGUE_MEAN


def test_decay_custom_carry_one_no_regression():
    assert apply_decay(1800.0, carry=1.0) == 1800.0


def test_decay_repeated_application_converges_to_mean():
    r = 1800.0
    for _ in range(50):
        r = apply_decay(r)
    assert abs(r - LEAGUE_MEAN) < 1.0


# ---- classify_outcome ----------------------------------------------------------

def test_classify_regulation_win_from_home_pov():
    out = classify_outcome(
        home_score=4, away_score=2, period_type="REG",
        season_id=20232024, perspective="home",
    )
    assert out == "REG_WIN"


def test_classify_regulation_loss_from_away_pov():
    out = classify_outcome(
        home_score=4, away_score=2, period_type="REG",
        season_id=20232024, perspective="away",
    )
    assert out == "REG_LOSS"


def test_classify_ot_win_and_loss():
    home = classify_outcome(home_score=3, away_score=2, period_type="OT",
                            season_id=20232024, perspective="home")
    away = classify_outcome(home_score=3, away_score=2, period_type="OT",
                            season_id=20232024, perspective="away")
    assert home == "OT_WIN"
    assert away == "OT_LOSS"


def test_classify_shootout_win_and_loss():
    home = classify_outcome(home_score=3, away_score=2, period_type="SO",
                            season_id=20232024, perspective="home")
    away = classify_outcome(home_score=3, away_score=2, period_type="SO",
                            season_id=20232024, perspective="away")
    assert home == "SO_WIN"
    assert away == "SO_LOSS"


def test_classify_tie_for_pre_2005_06_seasons():
    home = classify_outcome(home_score=2, away_score=2, period_type="REG",
                            season_id=19801981, perspective="home")
    away = classify_outcome(home_score=2, away_score=2, period_type="REG",
                            season_id=19801981, perspective="away")
    assert home == "TIE"
    assert away == "TIE"


def test_classify_tie_at_era_boundary():
    # The last tie-permitting season is 2004-05 (which was cancelled, but the
    # cutoff is the methodology's 2005-06 introduction of the shootout).
    out = classify_outcome(home_score=1, away_score=1, period_type="REG",
                           season_id=20032004, perspective="home")
    assert out == "TIE"


def test_classify_tie_post_2005_06_raises():
    # Equal regulation scores cannot exist from 2005-06 onward; if it appears
    # in the data, that's a pipeline / API bug worth surfacing loudly.
    with pytest.raises(ValueError):
        classify_outcome(home_score=2, away_score=2, period_type="REG",
                         season_id=TIE_ERA_END, perspective="home")


def test_classify_unknown_period_type_falls_back_to_regulation():
    out = classify_outcome(home_score=5, away_score=4, period_type="WAT",
                           season_id=20232024, perspective="home")
    assert out == "REG_WIN"


def test_classify_missing_period_type_treated_as_regulation():
    out = classify_outcome(home_score=5, away_score=4, period_type=None,
                           season_id=20232024, perspective="home")
    assert out == "REG_WIN"


def test_outcome_weights_for_new_tie_label():
    assert OUTCOME_WEIGHTS["TIE"] == 0.5


def test_initial_rating_is_league_mean():
    assert INITIAL_RATING == LEAGUE_MEAN
