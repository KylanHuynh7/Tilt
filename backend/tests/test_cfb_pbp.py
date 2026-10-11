"""College play-by-play sample checks (v1.3), offline."""

from app.cfb import pbp


def _pl(down, y, team, q=1, clock="10:00", hs=0, as_=0):
    return {"period": {"number": q}, "clock": {"displayValue": clock}, "homeScore": hs, "awayScore": as_,
            "start": {"down": down, "yardsToEndzone": y, "team": {"id": team}}}


def test_only_valid_plays_become_samples():
    plays = [_pl(1, 75, "1"), _pl(0, 65, "1"), _pl(2, 0, "2"), _pl(3, 40, "9"), _pl(4, 12, "2", q=5, clock="0:00")]
    s, total = pbp.samples_from_plays(plays, "1", "2")
    assert total == 5 and len(s) == 2
    assert s[0]["home_poss"] == 1 and s[0]["clock_s"] == 600
    assert s[1]["home_poss"] == -1 and s[1]["qtr"] == 5     # OT kept (τ = 0 applied later)


def test_clock_parsing():
    assert pbp.parse_clock("14:47") == 887 and pbp.parse_clock("0:58") == 58 and pbp.parse_clock(None) == 0
