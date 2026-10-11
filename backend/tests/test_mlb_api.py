"""MLB API pieces that don't need the network."""

import pytest
from fastapi.testclient import TestClient

from app.mlb import api as mlb_api, ratings


def test_normalize_player_two_way_and_career():
    payload = {"people": [{"primaryPosition": {"abbreviation": "TWP"}, "stats": [
        {"type": {"displayName": "yearByYear"}, "group": {"displayName": "hitting"},
         "splits": [{"season": "2025", "team": {"id": 119}, "stat": {"homeRuns": 55, "avg": ".282"}},
                    {"season": "2026", "team": {"id": 119}, "stat": {"homeRuns": 40, "avg": ".290"}}]},
        {"type": {"displayName": "career"}, "group": {"displayName": "hitting"}, "splits": [{"stat": {"homeRuns": 300}}]},
        {"type": {"displayName": "yearByYear"}, "group": {"displayName": "pitching"},
         "splits": [{"season": "2026", "team": {"id": 119}, "stat": {"era": "2.10"}}]},
    ]}]}
    out = mlb_api.normalize_player(payload)
    names = [c["name"] for c in out["categories"]]
    assert names == ["pitching", "hitting"]             # two-way: pitching listed first
    hitting = out["categories"][1]
    assert hitting["seasons"][0]["season"] == "2026" and hitting["seasons"][0]["team"] == "LAD"
    hr = hitting["labels"].index("HR")
    assert hitting["career"][hr] == "300"


def test_pitching_side_adjustment_and_first_start():
    c = mlb_api.Cache(params=ratings.Params(c=3.0), seasons=[], trajectories={}, era_abbrs={}, champions={},
                      current={}, pitcher_rgs={7: 60.0}, team_rgs={119: 52.0})
    ace = mlb_api.pitching_side(c, 119, {"id": 7, "fullName": "Ace"})
    assert ace["adjustment_elo"] == pytest.approx(24.0) and not ace["first_start"]
    rookie = mlb_api.pitching_side(c, 119, {"id": 8, "fullName": "Rookie"})
    assert rookie["adjustment_elo"] == 0.0 and rookie["first_start"]
    tbd = mlb_api.pitching_side(c, 119, None)
    assert tbd["adjustment_elo"] == 0.0 and not tbd["first_start"]


def test_live_label():
    assert mlb_api._live_label({"inningHalf": "Top", "currentInning": 7, "outs": 2}) == "Top 7 · 2 out"


@pytest.fixture(scope="module")
def client():
    if not mlb_api.ARTIFACT.exists():
        pytest.skip("MLB model not frozen")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_mlb_live_and_history(client):
    assert {s["id"]: s["status"] for s in client.get("/sports").json()["sports"]}["mlb"] == "live"
    h = client.get("/mlb/ratings/history/2024").json()
    assert h["cup_winner"] == "LAD" and h["n_franchises"] == 30
    cal = client.get("/mlb/calibration/current").json()
    assert cal["test_seasons"] == [2022, 2023, 2024, 2025]


def test_live_block_uses_bases_outs_and_score():
    from app.mlb import live_wp
    if not live_wp.ARTIFACT.exists():
        pytest.skip("live model not fitted")
    ls = {"currentInning": 9, "inningHalf": "Bottom", "outs": 2, "offense": {}}
    late_lead_away = mlb_api.live_block(ls, 2, 7, 0.5)["live_wp"]["home_win_prob"]
    assert late_lead_away < 0.03
    loaded = mlb_api.live_block({**ls, "outs": 0, "offense": {"first": {}, "second": {}, "third": {}}}, 3, 4, 0.5)
    empty = mlb_api.live_block({**ls, "outs": 2, "offense": {}}, 3, 4, 0.5)
    assert loaded["live_wp"]["home_win_prob"] > empty["live_wp"]["home_win_prob"]
