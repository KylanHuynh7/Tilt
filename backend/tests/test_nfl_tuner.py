"""NFL tuner: grid shape, test quarantine, frozen artifact integrity."""

import json
from pathlib import Path

import pytest

from app.nfl import pipeline, tuner

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "nfl" / "frozen_params.json"


def test_grid_is_the_preregistered_1440_cells():
    pts = tuner.grid_points()
    assert len(pts) == len(set(pts)) == 1440


def test_splits_are_disjoint_and_contiguous():
    w, v, t = tuner.WARMUP_SEASONS, tuner.VALIDATION_SEASONS, tuner.TEST_SEASONS_DO_NOT_TOUCH
    assert w + v + t == list(range(1999, 2026))


@pytest.mark.skipif(not pipeline.GAMES_PATH.exists(), reason="NFL ingest has not run")
def test_load_rows_never_includes_test_seasons():
    rows = tuner.load_rows()
    assert max(rows) == tuner.LAST_VALIDATION


@pytest.mark.skipif(not ARTIFACT.exists(), reason="NFL model not frozen")
def test_frozen_winner_is_grid_minimum():
    a = json.loads(ARTIFACT.read_text())
    assert len(a["grid"]) == 1440 and a["winner"] == a["grid"][0]
    assert a["winner"]["model"]["log_loss"] == min(r["model"]["log_loss"] for r in a["grid"])


def test_freeze_refuses_to_overwrite(monkeypatch, tmp_path):
    from scripts import nfl_freeze
    existing = tmp_path / "f.json"
    existing.write_text("{}")
    monkeypatch.setattr(nfl_freeze, "ARTIFACT", existing)
    monkeypatch.setattr("sys.argv", ["nfl_freeze"])
    assert nfl_freeze.main() == 3 and existing.read_text() == "{}"
