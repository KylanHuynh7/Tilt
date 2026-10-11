"""MLB rating rule + pitcher term (§5, v1.1). Offline synthetic seasons."""

import math
from datetime import date

import pytest

from app.mlb import backtest, pipeline, ratings


def test_game_score_formula():
    # 7 IP (21 outs), 8 K, 1 BB, 5 H, 2 R, 1 HR
    assert math.isclose(ratings.game_score(21, 8, 1, 5, 2, 1), 47.4 + 31.5 + 8 - 2 - 10 - 6 - 4)


def test_tie_moves_unequal_teams():
    p = ratings.win_probability(1600, 1400, home_bump=0, neutral=False)
    h, a = ratings.update(1600, 1400, home_score=3, away_score=3, k=4, p_home=p, eff_diff_home=200, mov=True)
    assert h < 1600 and a > 1400


def test_pitcher_adjustment_shifts_probability():
    base = ratings.win_probability(1500, 1500, home_bump=0, neutral=False)
    ace = ratings.win_probability(1500, 1500, a_home=40, home_bump=0, neutral=False)
    assert base == 0.5 and ace > 0.55


def _g(pk, d, h, a, hs, as_, hp=None, ap=None, gt="R"):
    return {"game_pk": pk, "season": d.year, "game_type": gt, "game_date": d, "home_id": h, "away_id": a,
            "home_score": hs, "away_score": as_, "is_final": True, "is_tie": False, "venue_id": 1,
            "neutral": False, "home_probable_id": hp, "away_probable_id": ap}


def _line(pk, side, pid, outs=18, k=6, bb=2, h=5, r=2, hr=1):
    return {"game_pk": pk, "side": side, "pitcher_id": pid, "outs": outs, "k": k, "bb": bb, "h": h, "r": r, "hr": hr}


def test_first_start_has_no_adjustment_and_ace_builds_rating():
    games = [_g(1, date(2012, 4, 1), 1, 2, 5, 1, hp=10, ap=20), _g(2, date(2012, 4, 6), 1, 2, 4, 2, hp=10, ap=21)]
    starters = {(1, "home"): _line(1, "home", 10, outs=27, k=12, bb=0, h=2, r=0, hr=0),
                (1, "away"): _line(1, "away", 20, outs=9, k=1, bb=4, h=8, r=6, hr=2),
                (2, "home"): _line(2, "home", 10), (2, "away"): _line(2, "away", 21)}
    data = {2012: backtest.SeasonData(games, starters)}
    res = backtest.run([2012], ratings.Params(c=4.7, alpha=0.5), data=data, record_predictions_for={2012})
    p1, p2 = res.predictions
    assert p1.home_pitcher_first_start and p1.away_pitcher_first_start
    assert not p2.home_pitcher_first_start          # pitcher 10 now has a rating
    assert res.pitcher_rgs[10] > res.team_rgs[1] - 1e-9   # dominant start lifted the ace above his team


def test_c_zero_is_team_only_elo():
    games = [_g(1, date(2012, 4, 1), 1, 2, 5, 1, hp=10, ap=20)]
    data = {2012: backtest.SeasonData(games, {})}
    res = backtest.run([2012], ratings.Params(c=0, home_bump=0), data=data, record_predictions_for={2012})
    assert res.predictions[0].home_win_prob == 0.5


@pytest.mark.parametrize("month,expected", [(4, "early"), (5, "early"), (7, "mid"), (9, "late"), (10, "late")])
def test_month_segments(month, expected):
    p = backtest.Prediction(2022, 1, date(2022, month, 10), "R", 1, 2, 0.5, 1.0, False, False, False)
    assert backtest.segment(p) == expected


def test_validity_rule_keeps_doubleheaders_drops_scoreless():
    ok = _g(1, date(2012, 4, 1), 1, 2, 3, 2)
    dh = _g(2, date(2012, 4, 1), 1, 2, 1, 0)
    ghost = {**_g(3, date(2012, 4, 2), 1, 2, 0, 0), "home_score": None, "away_score": None}
    assert [pipeline.is_valid_result(x) for x in (ok, dh, ghost)] == [True, True, False]
