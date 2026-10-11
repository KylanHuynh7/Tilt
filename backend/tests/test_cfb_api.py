"""CFB API contracts (offline parts + cached history/calibration)."""

import pytest
from fastapi.testclient import TestClient

from app.cfb import api as cfb_api


def test_display_color_swaps_dark_primary_for_alternate():
    assert cfb_api.display_color("0a0a0a", "ffc72c") == "#ffc72c"     # near-black → gold alt
    assert cfb_api.display_color("bb0000", "ffffff") == "#bb0000"     # readable primary kept
    assert cfb_api.display_color("050505", "000000") == "#9aa3ad"     # no usable alt → neutral grey


@pytest.fixture(scope="module")
def client():
    if not cfb_api.ARTIFACT.exists():
        pytest.skip("CFB model not frozen")
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_history_top25_and_champion(client):
    body = client.get("/cfb/ratings/history/2023").json()
    assert body["cup_winner"] == "MICH"
    assert 25 <= len(body["teams"]) <= 26


def test_current_ratings_include_fcs_pool(client):
    body = client.get("/cfb/ratings/current").json()
    assert "fcs_pool_rating" in body and len(body["teams"]) >= 130


def test_calibration_shape(client):
    body = client.get("/cfb/calibration/current").json()
    assert body["test_seasons"] == [2022, 2023, 2024, 2025] and "fbs_vs_fcs" in body
