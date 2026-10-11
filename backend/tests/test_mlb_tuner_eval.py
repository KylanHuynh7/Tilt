"""MLB grid shape, quarantine, and evaluator guardrails (offline)."""

from pathlib import Path

from app.mlb import tuner
from scripts import mlb_evaluate, mlb_freeze


def test_grid_is_5120_cells():
    assert len(tuner.grid_points()) == 5120


def test_splits_disjoint_and_contiguous():
    assert tuner.WARMUP_SEASONS + tuner.VALIDATION_SEASONS + tuner.TEST_SEASONS_DO_NOT_TOUCH == list(range(2000, 2026))


def test_evaluator_guardrails(tmp_path: Path):
    assert mlb_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    out = tmp_path / "r.json"
    out.write_text("{}")
    assert mlb_evaluate.main(["--confirm", "--out", str(out)]) == 3


def test_freeze_refuses_overwrite(monkeypatch, tmp_path):
    f = tmp_path / "f.json"
    f.write_text("{}")
    monkeypatch.setattr(mlb_freeze, "ARTIFACT", f)
    monkeypatch.setattr("sys.argv", ["mlb_freeze"])
    assert mlb_freeze.main() == 3


def test_verdict():
    assert set(mlb_evaluate.verdict({"log_loss": 0.68, "brier": 0.24, "ece": 0.02}, 0.69).values()) == {"PASS"}
