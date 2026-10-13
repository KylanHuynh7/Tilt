"""Win-probability curve helpers (no network)."""

from app.core import wp_curve


def test_swings_pick_largest_moves_in_time_order():
    pts = [{"x": 0, "wp": .5, "label": "a", "text": None}, {"x": .2, "wp": .55, "label": "b", "text": "small"},
           {"x": .4, "wp": .9, "label": "c", "text": "big"}, {"x": .6, "wp": .3, "label": "d", "text": "bigger"},
           {"x": .8, "wp": .32, "label": "e", "text": "tiny"}]
    s = wp_curve.swings(pts, k=2)
    assert [x["text"] for x in s] == ["big", "bigger"]


def test_pregame_and_future_games_get_no_curve():
    import asyncio
    assert asyncio.run(wp_curve.for_matchup("nfl", {"state": "PRE", "game_id": 1})) is None
    assert asyncio.run(wp_curve.for_matchup("nhl", {"state": "FUT", "game_id": 1})) is None


def test_mlb_third_out_moves_to_next_half_but_keeps_its_own_label():
    from app.mlb import live_wp
    if not live_wp.ARTIFACT.exists():
        return
    play = {"about": {"inning": 5, "halfInning": "bottom", "isComplete": True},
            "result": {"homeScore": 4, "awayScore": 4, "description": "K"}, "count": {"outs": 3}, "matchup": {}}
    pts = wp_curve._mlb({"allPlays": [play]}, 0.5)
    assert pts[-1]["label"].startswith("Bot 5")
