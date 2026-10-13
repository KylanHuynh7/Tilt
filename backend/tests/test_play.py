"""Play page: matchup machine, watch-tonight scoring, swing labelling (no network)."""

from fastapi.testclient import TestClient


def test_matchup_current_and_cross_era():
    from app.main import app
    c = TestClient(app)
    r = c.get("/play/matchup", params={"sport": "nfl", "home": "SEA", "away": "SF"}).json()
    assert 0 < r["home_win_prob"] < 1 and "For fun" not in r["note"]
    r = c.get("/play/matchup", params={"sport": "nhl", "home": "EDM", "away": "VGK", "neutral": True,
                                        "home_season": 19841985, "away_season": 20222023}).json()
    assert 0 < r["home_win_prob"] < 1 and "For fun" in r["note"]
    assert c.get("/play/matchup", params={"sport": "nfl", "home": "XXX", "away": "SF"}).status_code == 404


def test_watch_score_prefers_close_games_between_good_teams(monkeypatch):
    from app import play
    monkeypatch.setattr(play, "_teams_and_seasons", lambda s: {"teams": [{"code": "A"}, {"code": "B"}],
                                                              "rating": lambda code, season: {"A": 1400, "B": 1600}[code]})
    rows = [{"sport": "nfl", "home_rating": 1600, "away_rating": 1600, "home_win_prob": 0.52},   # good + close
            {"sport": "nfl", "home_rating": 1400, "away_rating": 1400, "home_win_prob": 0.50},   # close, weak
            {"sport": "nfl", "home_rating": 1600, "away_rating": 1400, "home_win_prob": 0.85}]   # lopsided
    play._watch_scores(rows)
    assert rows[0]["watch_score"] > rows[1]["watch_score"] > rows[2]["watch_score"]
    assert rows[0]["watch_strong"] and not rows[1]["watch_strong"]


def test_swings_skip_period_markers():
    from app.core import wp_curve
    pts = [{"x": 0, "wp": .5, "label": "a", "text": None}, {"x": .5, "wp": .95, "label": "b", "text": "END QUARTER 4"},
           {"x": .6, "wp": .7, "label": "c", "text": "Touchdown"}]
    assert [s["text"] for s in wp_curve.swings(pts)] == ["Touchdown"]
