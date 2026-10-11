"""NBA endpoint contracts (offline; /nba/games/today hits ESPN and is
exercised in the manual smoke run, like the NHL today endpoint).
"""

import pytest
from fastapi.testclient import TestClient

from app.nba import api as nba_api, pipeline


@pytest.fixture(scope="module")
def client():
    if not pipeline.load_manifest() or not nba_api.ARTIFACT.exists():
        pytest.skip("requires NBA ingest + freeze")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_sports_lists_nba_live(client):
    by_id = {s["id"]: s for s in client.get("/sports").json()["sports"]}
    assert by_id["nba"]["status"] == "live"


def test_seasons_start_at_first_model_season(client):
    body = client.get("/nba/seasons").json()
    ids = [s["season_id"] for s in body["seasons"]]
    assert ids == sorted(ids, reverse=True)
    assert ids[-1] == pipeline.first_model_season()


def test_current_ratings_cover_30_franchises(client):
    teams = client.get("/nba/ratings/current").json()["teams"]
    assert len(teams) == 30
    assert all(t["color"].startswith("#") for t in teams)
    assert abs(sum(t["rating"] for t in teams) / 30 - 1500) < 1.0


def test_history_uses_era_codes_and_finds_champion(client):
    body = client.get("/nba/ratings/history/20052006").json()
    codes = {t["franchise_id"]: t["team"] for t in body["teams"]}
    assert codes["25"] == "SEA" and codes["17"] == "NJN"
    assert body["cup_winner"] == "MIA"  # 2006 Finals
    assert body["cup_winner_franchise"] == "14"


def test_history_unknown_season_404(client):
    assert client.get("/nba/ratings/history/19951996").status_code == 404


def test_calibration_matches_locked_results(client):
    body = client.get("/nba/calibration/current").json()
    assert body["test_seasons"] == [20242025, 20252026]
    assert set(body["metrics"]) >= {"model", "naive_baseline", "static_rating_baseline", "home_rate_baseline"}
    assert body["frozen_params"]["decay_carry"] == body["frozen_params"]["carry"]


def test_live_block_adds_live_wp():
    from app.nba import live_wp
    if not live_wp.ARTIFACT.exists():
        pytest.skip("live model not fitted")
    row = {"n_periods": 4, "home_score": 100, "away_score": 80, "clock_s": 60.0}
    out = nba_api.live_block(row, p_home=0.5)
    assert out["live_state"]["period"] == 4 and out["live_state"]["time_remaining_s"] == 60
    assert out["live_wp"]["home_win_prob"] > 0.99
    tied = nba_api.live_block({**row, "home_score": 90, "away_score": 90, "clock_s": 720.0}, 0.5)
    assert 0.4 < tied["live_wp"]["home_win_prob"] < 0.7
