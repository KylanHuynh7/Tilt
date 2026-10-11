"""MLB play-by-play state reconstruction (v1.2), offline."""

from app.mlb import pbp


def _play(inning, half, outs, hs, as_, on1=None, on2=None, on3=None):
    return {"about": {"inning": inning, "halfInning": half}, "count": {"outs": outs},
            "result": {"homeScore": hs, "awayScore": as_},
            "matchup": {"postOnFirst": on1, "postOnSecond": on2, "postOnThird": on3}}


def test_state_is_before_each_plate_appearance_and_resets_each_half():
    plays = [
        _play(1, "top", 0, 0, 0, on1={"id": 1}),        # single
        _play(1, "top", 1, 0, 0, on2={"id": 1}),        # out, runner advances
        _play(1, "top", 3, 0, 0),                       # inning-ending DP
        _play(1, "bottom", 0, 1, 0),                    # leadoff HR
    ]
    s = pbp.states_from_plays(plays, ghost_runner=False)
    assert [(x["outs"], x["bases"]) for x in s] == [(0, 0), (0, 1), (1, 2), (0, 0)]
    assert s[3]["bottom"] and s[3]["home_score"] == 0     # score BEFORE the home run


def test_extra_inning_ghost_runner_only_when_flagged():
    plays = [_play(10, "top", 1, 3, 3)]
    assert pbp.states_from_plays(plays, ghost_runner=True)[0]["bases"] == 2
    assert pbp.states_from_plays(plays, ghost_runner=False)[0]["bases"] == 0
