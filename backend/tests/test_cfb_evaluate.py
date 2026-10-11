"""CFB evaluator guardrails + grid shape."""

from pathlib import Path

from app.cfb import tuner
from scripts import cfb_evaluate


def test_guardrails(tmp_path: Path):
    assert cfb_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    f = tmp_path / "r.json"
    f.write_text("{}")
    assert cfb_evaluate.main(["--confirm", "--out", str(f)]) == 3


def test_grid_and_splits():
    assert len(tuner.grid_points()) == 2304
    assert tuner.WARMUP_SEASONS + tuner.VALIDATION_SEASONS + tuner.TEST_SEASONS_DO_NOT_TOUCH == list(range(2001, 2026))
