"""Cost guards: admin endpoints and the Cup simulation's public parameters."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.mark.parametrize("path", ["/admin/refresh", "/nba/admin/refresh", "/nfl/admin/refresh",
                                  "/mlb/admin/refresh", "/cfb/admin/refresh"])
def test_refresh_disabled_without_token_config(client, monkeypatch, path):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.post(path).status_code == 403


def test_refresh_requires_matching_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    assert client.post("/nfl/admin/refresh").status_code == 401
    assert client.post("/nfl/admin/refresh", headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_is_admin():
    import os
    from app.core import admin
    os.environ.pop("ADMIN_TOKEN", None)
    assert not admin.is_admin("anything")
    os.environ["ADMIN_TOKEN"] = "t"
    try:
        assert admin.is_admin("t") and not admin.is_admin("x") and not admin.is_admin(None)
    finally:
        os.environ.pop("ADMIN_TOKEN")
