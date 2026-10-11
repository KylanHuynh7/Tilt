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


def test_outs_remaining_formula():
    from app.mlb import live_wp
    assert live_wp.outs_remaining(1, False, 0) == 54      # first pitch
    assert live_wp.outs_remaining(9, True, 2) == 1        # bottom 9th, 2 out
    assert live_wp.outs_remaining(9, False, 0) == 6
    assert live_wp.outs_remaining(11, False, 1) == 5      # extras: current inning only
    assert live_wp.outs_remaining(11, True, 1) == 2


def test_live_evaluator_guardrails(tmp_path):
    from scripts import mlb_live_wp_evaluate
    assert mlb_live_wp_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    f = tmp_path / "r.json"
    f.write_text("{}")
    assert mlb_live_wp_evaluate.main(["--confirm", "--out", str(f)]) == 3
