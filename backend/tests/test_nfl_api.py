"""NFL endpoint contracts (offline; /nfl/games/today hits ESPN)."""

import pytest
from fastapi.testclient import TestClient

from app.nfl import api as nfl_api, espn, pipeline


@pytest.fixture(scope="module")
def client():
    if not pipeline.GAMES_PATH.exists() or not nfl_api.ARTIFACT.exists():
        pytest.skip("requires NFL ingest + freeze")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_sports_lists_nfl_live(client):
    by_id = {s["id"]: s for s in client.get("/sports").json()["sports"]}
    assert by_id["nfl"]["status"] == "live"


def test_current_ratings_cover_32_teams(client):
    teams = client.get("/nfl/ratings/current").json()["teams"]
    assert len(teams) == 32
    assert abs(sum(t["rating"] for t in teams) / 32 - 1500) < 1.0


def test_history_uses_era_codes_and_super_bowl_winner(client):
    body = client.get("/nfl/ratings/history/2005").json()
    codes = {t["franchise_id"]: t["team"] for t in body["teams"]}
    assert (codes["LA"], codes["LAC"], codes["LV"]) == ("STL", "SD", "OAK")
    assert body["cup_winner"] == "PIT"   # Super Bowl XL
    assert "HOU" in codes                # entered 2002


def test_calibration_matches_locked_results(client):
    body = client.get("/nfl/calibration/current").json()
    assert body["test_seasons"] == [2022, 2023, 2024, 2025]
    assert "home_rate_baseline" in body["metrics"]


def _event(state="in", possession="12"):
    return {
        "id": "401", "date": "2026-10-11T17:00Z", "season": {"type": 2}, "week": {"number": 6},
        "competitions": [{
            "neutralSite": False,
            "status": {"period": 3, "clock": 431.0, "type": {"state": state, "completed": False}},
            "situation": {"possession": possession, "yardsToEndzone": 35, "down": 2, "distance": 7},
            "competitors": [
                {"homeAway": "home", "team": {"id": "12", "abbreviation": "KC"}, "score": "17"},
                {"homeAway": "away", "team": {"id": "14", "abbreviation": "LAR"}, "score": "13"},
            ],
        }],
    }


def test_espn_parse_maps_codes_and_situation():
    g = espn.parse_event(_event())
    assert (g["home"], g["away"]) == ("KC", "LA")   # LAR → LA
    assert g["possession"] == "home" and g["yardline_100"] == 35 and g["down"] == 2
    assert nfl_api.live_block(g)["live_state"]["period"] == 3


def test_espn_parse_schema_change_raises():
    e = _event()
    del e["competitions"]
    with pytest.raises(espn.SchemaError):
        espn.parse_event(e)


def test_live_block_adds_live_wp_with_possession():
    from app.nfl import live_wp
    if not live_wp.ARTIFACT.exists():
        pytest.skip("live model not fitted")
    g = espn.parse_event(_event())                    # home leads 17-13, Q3, home ball at opp 35
    wp = nfl_api.live_block(g, 0.5)["live_wp"]["home_win_prob"]
    g_away = {**g, "possession": "away"}
    assert wp > nfl_api.live_block(g_away, 0.5)["live_wp"]["home_win_prob"]
    assert 0.6 < wp < 0.95
