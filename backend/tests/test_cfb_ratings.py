"""College football engine: pooled FCS, entrants, leavers (v1.2)."""

from app.cfb import backtest, ratings
from app.cfb.ratings import FCS


def _g(gid, h, a, hs, as_, date="2010-09-04", post=False):
    return {"game_id": gid, "game_date": date, "home_id": h, "away_id": a, "home_score": hs, "away_score": as_,
            "season_type": 3 if post else 2, "week": 0 if post else 1, "neutral": post, "conference_game": False,
            "completed": True}


def test_fcs_games_use_pool_and_are_flagged():
    data = {2010: ([_g(1, 1, 99, 45, 3), _g(2, 1, 2, 20, 17)], {1, 2})}
    res = backtest.run([2010], ratings.Params(fcs_init=1200), data=data, record_predictions_for={2010})
    p1, p2 = res.predictions
    assert p1.away == FCS and p1.fcs_game and not p2.fcs_game
    assert res.ratings[FCS] < 1200          # the pool lost a game


def test_entrant_starts_at_pool_and_leaver_drops_out():
    data = {
        2010: ([_g(1, 1, 2, 30, 10)], {1, 2}),
        2011: ([_g(2, 1, 3, 30, 10, date="2011-09-03")], {1, 3}),   # 3 enters FBS, 2 leaves
    }
    res = backtest.run([2010, 2011], ratings.Params(fcs_init=1200, carry=0.5), data=data, record_trajectories=True)
    assert 2 not in res.ratings
    entrant_start = res.trajectories[2011][3][0].rating
    assert entrant_start < 1300               # pool value (~1200 regressed), not 1500


def test_first_season_programs_start_at_1500():
    data = {2001: ([_g(1, 1, 2, 21, 14)], {1, 2})}
    res = backtest.run([2001], ratings.Params(), data=data, record_trajectories=True)
    assert res.trajectories[2001][1][0].rating == 1500.0


def test_segments():
    mk = lambda w, post=False: backtest.Prediction(2022, 1, w, post, 1, 2, .6, 1, False, True, False)  # noqa: E731
    assert [backtest.segment(mk(w)) for w in (1, 4, 5, 10, 11)] == ["early", "early", "mid", "mid", "late"]
    assert backtest.segment(mk(0, True)) == "postseason"
