"""NFL rating rule (§5) and backtest invariants (§7–§9)."""

import math

import pytest

from app.nfl import backtest, pipeline, ratings


def test_tie_moves_unequal_teams_toward_each_other():
    h, a, p = ratings.update(1600, 1400, home_score=20, away_score=20,
                             k=20, home_bump=0, neutral=False, mov=True)
    assert h < 1600 and a > 1400            # M = 1 for ties, not ln(1) = 0
    assert math.isclose(h + a, 3000)


def test_mov_multiplier_matches_538_nfl_form():
    assert math.isclose(ratings.mov_multiplier(7, 0.0), math.log(8))
    assert ratings.mov_multiplier(21, 200) < ratings.mov_multiplier(21, -200)


def test_neutral_site_has_no_bump():
    assert ratings.win_probability(1500, 1500, home_bump=50, neutral=True) == 0.5


def test_outcomes():
    assert ratings.outcome(24, 17) == 1.0 and ratings.outcome(17, 24) == 0.0 and ratings.outcome(20, 20) == 0.5


def _pred(season, week, gtype="REG"):
    return backtest.Prediction(season, "x", None, gtype, week, "KC", "BUF", 0.6, 1.0, False)


@pytest.mark.parametrize("season,week,expected", [
    (2020, 4, "early"), (2020, 15, "mid"), (2020, 16, "late"), (2020, 17, "late"),
    (2024, 16, "mid"), (2024, 17, "late"), (2024, 18, "late"), (2024, 5, "mid"),
])
def test_week_segments(season, week, expected):
    assert backtest.segment(_pred(season, week)) == expected


def test_playoff_segment():
    assert backtest.segment(_pred(2024, 19, "WC")) == "postseason"


needs_data = pytest.mark.skipif(not pipeline.GAMES_PATH.exists(), reason="NFL ingest has not run")


@needs_data
def test_backtest_bounds_mean_and_expansion():
    rows = backtest.rows_by_season(through=2014)
    seasons = backtest.model_seasons(rows)
    assert seasons[0] == 1999
    for mov in (False, True):
        res = backtest.run(seasons, ratings.Params(mov=mov), rows=rows, record_trajectories=True)
        assert len(res.ratings) == 32
        assert all(1100 < r < 1900 for r in res.ratings.values())
        assert abs(sum(res.ratings.values()) / 32 - 1500) < 1.0
    assert "HOU" not in res.trajectories[2001]
    assert res.trajectories[2002]["HOU"][0].rating == 1500.0


@needs_data
def test_relocated_franchises_are_continuous():
    rows = backtest.rows_by_season(through=2020)
    res = backtest.run(backtest.model_seasons(rows), ratings.Params(), rows=rows, record_trajectories=True)
    for code in ("LA", "LAC", "LV"):
        assert all(code in res.trajectories[s] for s in range(1999, 2021))
