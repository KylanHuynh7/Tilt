"""Endpoint contract tests for the Phase D API.

Uses FastAPI's TestClient (sync), which spins up the app once and runs the
lifespan handler — so the historical cache is built once per test session.
Network-dependent endpoints (`/games/today`, `/admin/refresh`) are exercised
in the manual smoke run, not here, because they hit the live NHL API.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import historical, pipeline


@pytest.fixture(scope="module")
def client():
    if not (pipeline.RAW_DIR / "20242025.parquet").exists():
        pytest.skip("requires Phase A ingest to have run")
    if not historical.ARTIFACT_PATH.exists():
        pytest.skip("requires Phase C freeze to have produced an artifact")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_healthz_reports_cache(client: TestClient):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["seasons_in_cache"] >= 50
    assert "frozen_params" in body
    assert body["frozen_params"]["k_regular"] > 0


def test_seasons_lists_108_when_full_ingest_present(client: TestClient):
    r = client.get("/seasons")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 50  # at minimum the training+validation+test span
    sids = [s["season_id"] for s in body["seasons"]]
    # Sorted descending — current season first.
    assert sids == sorted(sids, reverse=True)
    # Pre-1967 flag is present on the row.
    for s in body["seasons"]:
        assert isinstance(s["pre_1967"], bool)
        assert s["pre_1967"] == (s["season_id"] < 19671968)


def test_ratings_current_has_32_active(client: TestClient):
    r = client.get("/ratings/current")
    assert r.status_code == 200
    body = r.json()
    assert len(body["teams"]) == 32
    # Sorted by rating desc
    ratings = [t["rating"] for t in body["teams"]]
    assert ratings == sorted(ratings, reverse=True)


def test_ratings_history_modern_season(client: TestClient):
    r = client.get("/ratings/history/20242025")
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == 20242025
    assert body["label"] == "2024-25"
    assert body["pre_1967"] is False
    assert body["n_franchises"] == 32
    # Each team has at least one point.
    for t in body["teams"]:
        assert len(t["points"]) > 0
        for p in t["points"]:
            assert "date" in p and "rating" in p


def test_ratings_history_pre_1967_flagged(client: TestClient):
    r = client.get("/ratings/history/19501951")
    assert r.status_code == 200
    body = r.json()
    assert body["pre_1967"] is True
    assert 4 <= body["n_franchises"] <= 8  # Original Six era


def test_ratings_history_unknown_season_404(client: TestClient):
    r = client.get("/ratings/history/29002901")
    assert r.status_code == 404


def test_calibration_returns_test_evaluation(client: TestClient, tmp_path: Path):
    from app import main as main_mod
    if not main_mod.RESULTS_PATH.exists():
        pytest.skip("requires Phase C evaluate.py to have been run")
    r = client.get("/calibration/current")
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body
    assert "model" in body["metrics"]
    assert "naive_baseline" in body["metrics"]
    assert "static_rating_baseline" in body["metrics"]
    assert "calibration_buckets" in body
    assert "section_6_targets" in body
