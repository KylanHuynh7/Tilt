"""Shared game-detail builder + live history + roster parsing (offline)."""

import asyncio

import pytest

from app.core import detail, live_history, rosters

GAMES = [
    {"date": "2026-01-01", "home": "BOS", "away": "NYR", "home_score": 3, "away_score": 1},
    {"date": "2026-01-03", "home": "NYR", "away": "BOS", "home_score": 2, "away_score": 2},
    {"date": "2026-01-05", "home": "TOR", "away": "BOS", "home_score": 4, "away_score": 2},
]


def test_team_form_most_recent_first_with_results():
    f = detail.team_form("BOS", GAMES)
    assert [x["result"] for x in f] == ["L", "T", "W"]
    assert f[0]["opponent"] == "TOR" and f[0]["at_home"] is False


def test_head_to_head_either_venue():
    assert len(detail.head_to_head("BOS", "NYR", GAMES)) == 2


def test_probability_breakdown_neutral_has_no_home_edge():
    b = detail.probability_breakdown(1550, 1500, home_bump=40, neutral=True, p_home=0.5715)
    assert b["home_edge_elo"] == 0 and b["home_edge_prob_points"] == 0
    b2 = detail.probability_breakdown(1500, 1500, home_bump=40, neutral=False, p_home=0.5573)
    assert b2["rating_gap"] == 0 and b2["home_edge_prob_points"] > 0.05


def test_calibration_context_picks_bucket():
    buckets = [{"lo": 0.5, "hi": 0.6, "n": 10, "mean_predicted": 0.55, "mean_actual": 0.6},
               {"lo": 0.6, "hi": 1.0, "n": 0, "mean_predicted": 0, "mean_actual": 0}]
    assert detail.calibration_context(0.57, buckets, "x")["home_win_rate"] == 0.6
    assert detail.calibration_context(0.65, buckets, "x") is None   # empty bucket → no claim


def test_live_history_dedupes_identical_states():
    st = {"period": 2, "time_remaining_s": 300, "home_score": 1, "away_score": 0}
    live_history.record("test", 1, st, 0.6)
    live_history.record("test", 1, st, 0.61)
    live_history.record("test", 1, {**st, "time_remaining_s": 240}, 0.62)
    assert [p["home_wp"] for p in live_history.get("test", 1)] == [0.6, 0.62]


def test_roster_splits_available_and_ruled_out():
    flat = rosters.parse({"athletes": [
        {"displayName": "A", "injuries": [{"status": "Out"}]},
        {"displayName": "B", "injuries": [{"status": "Questionable"}]},
        {"displayName": "C"},
    ]})
    assert [p["name"] for p in flat["available"][0]["players"]] == ["B", "C"]
    assert flat["available"][0]["players"][0]["status"] == "Questionable"   # game-time decision tagged
    assert [(p["name"], p["reason"]) for p in flat["ruled_out"]] == [("A", "Out")]


def test_roster_groups_ir_suspended_and_practice_squad():
    r = rosters.parse({"athletes": [
        {"position": "offense", "items": [{"displayName": "QB1"}]},
        {"position": "injuredReserveOrOut", "items": [{"displayName": "IR1"}]},
        {"position": "suspended", "items": [{"displayName": "S1"}]},
        {"position": "practiceSquad", "items": [{"displayName": "PS1"}]},
    ]})
    assert [g["group"] for g in r["available"]] == ["offense"]
    assert {p["name"]: p["reason"] for p in r["ruled_out"]} == {"IR1": "Out / IR", "S1": "Suspended"}
    assert "PS1" not in str(r)


def test_nba_detail_endpoint_with_stubbed_slate(monkeypatch):
    from app.nba import api as nba_api
    if not nba_api.ARTIFACT.exists():
        pytest.skip("NBA model not frozen")

    async def fake_today():
        return {"matchups": [{
            "game_id": 99, "state": "PRE", "home": "BOS", "away": "LAL", "home_color": "#0f0",
            "away_color": "#80f", "neutral": False, "home_rating": 1600.0, "away_rating": 1550.0,
            "home_win_prob": 0.62, "away_win_prob": 0.38, "home_score": None, "away_score": None}]}

    async def fake_roster(client, path, team):
        return {"loaded": True, "available": [], "ruled_out": [], "source": "ESPN"}

    monkeypatch.setattr(nba_api, "games_today", fake_today)
    monkeypatch.setattr(rosters, "fetch", fake_roster)
    d = asyncio.run(nba_api.game_detail(99))
    assert d["home"]["code"] == "BOS" and d["projections"] is None
    assert d["probability"]["rating_gap"] == 50.0
    assert len(d["home"]["form"]) == 10


def test_player_stats_normalize_maps_teams_and_sorts_newest_first():
    from app.core import players
    payload = {
        "teams": {"los-angeles-lakers": {"id": "13", "abbreviation": "LAL"},
                  "cleveland-cavaliers": {"id": "5", "abbreviation": "CLE"}},
        "categories": [{"name": "averages", "displayName": "Regular Season Averages", "labels": ["GP", "PTS"],
                        "statistics": [
                            {"teamId": "5", "season": {"year": 2004, "displayName": "2003-04"}, "stats": ["79", "20.9"]},
                            {"teamSlug": "los-angeles-lakers", "season": {"year": 2026, "displayName": "2025-26"}, "stats": ["60", "25.1"]},
                        ],
                        "totals": ["1622", "26.9"]}],
    }
    out = players.normalize(payload)
    seasons = out["categories"][0]["seasons"]
    assert [(r["season"], r["team"]) for r in seasons] == [("2025-26", "LAL"), ("2003-04", "CLE")]
    assert out["categories"][0]["career"] == ["1622", "26.9"]


def test_roster_player_carries_id_and_headshot():
    r = rosters.parse({"athletes": [{"id": "1966", "displayName": "X", "headshot": {"href": "https://h/x.png"}}]})
    p = r["available"][0]["players"][0]
    assert p["id"] == "1966" and p["headshot"] == "https://h/x.png"


def test_player_without_stats_is_an_empty_card_not_an_error(monkeypatch):
    import httpx
    from app.core import players

    class Resp:
        status_code = 404
        def raise_for_status(self):
            raise httpx.HTTPStatusError("404", request=None, response=None)

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return Resp()

    monkeypatch.setattr(players.httpx, "AsyncClient", Client)
    players._cache.clear()
    out = asyncio.run(players.fetch("nfl", "123"))
    assert out["categories"] == []
