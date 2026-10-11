"""NBA rating rule (§5) and backtest invariants (§7, §8, §9 #3)."""

import math

import pytest

from app.nba import backtest, pipeline, ratings


def test_neutral_game_ignores_home_bump():
    assert ratings.win_probability(1500, 1500, home_bump=100, neutral=True) == 0.5
    assert ratings.win_probability(1500, 1500, home_bump=100, neutral=False) > 0.6


def test_mov_multiplier_matches_formula():
    # 538 form: (|MOV|+3)^0.8 / (7.5 + 0.006 D)
    assert math.isclose(ratings.mov_multiplier(10, 0.0), 13 ** 0.8 / 7.5)
    # A favorite winning big is damped relative to an underdog winning big.
    assert ratings.mov_multiplier(20, 200) < ratings.mov_multiplier(20, -200)


def test_update_is_zero_sum_and_directional():
    h, a, p = ratings.update(1500, 1500, home_score=110, away_score=100,
                             k=20, home_bump=100, neutral=False, mov=True)
    assert math.isclose(h + a, 3000.0)
    assert h > 1500 > a
    assert 0.5 < p < 1.0


def test_mov_off_is_plain_elo():
    h, _, p = ratings.update(1500, 1500, home_score=101, away_score=100,
                             k=20, home_bump=0, neutral=False, mov=False)
    assert math.isclose(h, 1500 + 20 * (1 - 0.5))


def test_bigger_margin_moves_rating_more_with_mov():
    close, _, _ = ratings.update(1500, 1500, home_score=101, away_score=100,
                                 k=20, home_bump=0, neutral=False, mov=True)
    blowout, _, _ = ratings.update(1500, 1500, home_score=130, away_score=100,
                                   k=20, home_bump=0, neutral=False, mov=True)
    assert blowout > close


needs_data = pytest.mark.skipif(not pipeline.load_manifest(), reason="NBA ingest has not run")


@needs_data
def test_backtest_starts_in_2000_01_and_rates_30_franchises():
    seasons = backtest.model_seasons(through=20172018)
    assert seasons[0] == 20002001
    res = backtest.run(seasons, ratings.Params())
    assert len(res.ratings) == 30


@needs_data
@pytest.mark.parametrize("mov", [False, True])
def test_ratings_stay_in_sanity_bounds_and_mean_holds(mov):
    """§9 #3 bounds [1100, 1900]; §8 league mean within ±1 of 1500."""
    res = backtest.run(backtest.model_seasons(through=20172018), ratings.Params(mov=mov))
    for tid, r in res.ratings.items():
        assert 1100 < r < 1900, (tid, r)
    assert abs(sum(res.ratings.values()) / len(res.ratings) - 1500) < 1.0


@needs_data
def test_bobcats_enter_at_1500_in_2004_05():
    res = backtest.run(backtest.model_seasons(through=20042005), ratings.Params(),
                       record_trajectories=True)
    assert res.trajectories[20042005][30][0].rating == 1500.0
    assert 30 not in res.trajectories[20032004]


@needs_data
def test_bubble_games_are_neutral():
    """§13 pin: every 2019-20 game played in Lake Buena Vista is neutral —
    88 seeding + 1 play-in + 83 playoff games = 172 — plus the three
    ESPN-flagged international games (Mexico City ×2, Paris) = 175.
    """
    from app.nba import espn

    rows = backtest.model_rows(20192020)
    bubble = [r for r in rows if r["venue_city"] == espn.BUBBLE_CITY]
    assert len(bubble) == 172 and all(espn.is_neutral(r) for r in bubble)
    assert sum(espn.is_neutral(r) for r in rows) == 175


@needs_data
def test_predictions_recorded_only_for_requested_seasons():
    res = backtest.run(backtest.model_seasons(through=20012002), ratings.Params(),
                       record_predictions_for={20012002})
    assert {p.season_id for p in res.predictions} == {20012002}
    reg = [p for p in res.predictions if p.season_type == pipeline.REGULAR]
    assert max(p.home_game_no for p in reg) == 82
