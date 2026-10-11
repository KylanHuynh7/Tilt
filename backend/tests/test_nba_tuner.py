"""NBA tuner: grid shape, test-set quarantine, frozen artifact integrity."""

import json
from pathlib import Path

import pytest

from app.nba import pipeline, tuner

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "nba" / "frozen_params.json"


def test_grid_is_the_preregistered_1200_cells():
    pts = tuner.grid_points()
    assert len(pts) == 1200
    assert len(set(pts)) == 1200


def test_splits_do_not_overlap():
    warm = set(tuner.warmup_seasons()) if pipeline.load_manifest() else set()
    val, test = set(tuner.VALIDATION_SEASONS), set(tuner.TEST_SEASONS_DO_NOT_TOUCH)
    assert not (val & test) and not (warm & val) and not (warm & test)


@pytest.mark.skipif(not pipeline.load_manifest(), reason="NBA ingest has not run")
def test_load_rows_never_includes_test_seasons():
    rows = tuner.load_rows()
    assert max(rows) == tuner.LAST_VALIDATION
    assert not set(rows) & set(tuner.TEST_SEASONS_DO_NOT_TOUCH)


@pytest.mark.skipif(not ARTIFACT.exists(), reason="NBA model not frozen")
def test_frozen_artifact_winner_is_grid_minimum():
    a = json.loads(ARTIFACT.read_text())
    assert len(a["grid"]) == 1200
    assert a["winner"] == a["grid"][0]
    lls = [r["model"]["log_loss"] for r in a["grid"]]
    assert a["winner"]["model"]["log_loss"] == min(lls)
    assert a["test_seasons_untouched"] == tuner.TEST_SEASONS_DO_NOT_TOUCH


def test_freeze_script_refuses_to_overwrite(monkeypatch, tmp_path, capsys):
    from scripts import nba_freeze

    existing = tmp_path / "frozen_params.json"
    existing.write_text("{}")
    monkeypatch.setattr(nba_freeze, "ARTIFACT", existing)
    monkeypatch.setattr("sys.argv", ["nba_freeze"])
    assert nba_freeze.main() == 3
    assert existing.read_text() == "{}"
