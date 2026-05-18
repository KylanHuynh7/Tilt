"""Tests for the ingest pipeline — parsing, parquet I/O, manifest."""

from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from app import pipeline


def _ok_raw():
    return {
        "id": 2023021287,
        "season": 20232024,
        "gameType": 2,
        "gameDate": "2024-04-15",
        "gameState": "OFF",
        "homeTeam": {"abbrev": "TOR", "score": 3},
        "awayTeam": {"abbrev": "MTL", "score": 4},
        "gameOutcome": {"lastPeriodType": "OT", "otPeriods": 1},
    }


def test_parse_game_happy_path():
    row = pipeline._parse_game(_ok_raw(), 20232024)
    assert row is not None
    assert row["game_id"] == 2023021287
    assert row["home"] == "TOR"
    assert row["away"] == "MTL"
    assert row["home_score"] == 3
    assert row["away_score"] == 4
    assert row["period_type"] == "OT"
    assert row["state"] == "OFF"
    assert row["game_type"] == 2
    assert row["pre_1967"] is False
    assert row["game_date"] == date(2024, 4, 15)


def test_parse_game_flags_pre_1967():
    raw = _ok_raw()
    raw["season"] = 19601961
    raw["gameDate"] = "1961-01-15"
    row = pipeline._parse_game(raw, 19601961)
    assert row is not None
    assert row["pre_1967"] is True


def test_parse_game_returns_none_on_missing_teams():
    raw = _ok_raw()
    del raw["homeTeam"]
    assert pipeline._parse_game(raw, 20232024) is None


def test_parse_game_handles_unscored_future_game():
    raw = _ok_raw()
    raw["homeTeam"]["score"] = None
    raw["awayTeam"]["score"] = None
    raw["gameState"] = "FUT"
    raw["gameOutcome"] = None
    row = pipeline._parse_game(raw, 20232024)
    assert row is not None
    assert row["home_score"] is None
    assert row["away_score"] is None
    assert row["period_type"] is None
    assert row["state"] == "FUT"


def test_parquet_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline, "RAW_DIR", tmp_path)
    rows = [pipeline._parse_game(_ok_raw(), 20232024)]
    out = pipeline.write_season(20232024, rows)
    assert out.exists()
    table = pq.read_table(out)
    assert table.num_rows == 1
    assert table.column("home").to_pylist() == ["TOR"]
    assert table.column("away").to_pylist() == ["MTL"]
    assert table.column("game_date").to_pylist() == [date(2024, 4, 15)]


def test_write_empty_season_produces_valid_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline, "RAW_DIR", tmp_path)
    out = pipeline.write_season(19181919, [])
    table = pq.read_table(out)
    assert table.num_rows == 0
    assert table.schema.equals(pipeline.SCHEMA)


def test_manifest_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pipeline, "DATA_CACHE", tmp_path)
    monkeypatch.setattr(pipeline, "MANIFEST_PATH", tmp_path / "manifest.json")
    assert pipeline.load_manifest() == {}
    pipeline._update_manifest(20232024, 1312)
    pipeline._update_manifest(20242025, 1400)
    loaded = pipeline.load_manifest()
    assert set(loaded.keys()) == {"20232024", "20242025"}
    assert loaded["20232024"]["rows"] == 1312
    assert "pulled_at" in loaded["20242025"]
