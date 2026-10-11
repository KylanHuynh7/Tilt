"""§10 #1 guardrails on the NFL evaluator (never replays the test seasons)."""

from pathlib import Path

from scripts import nfl_evaluate


def test_refuses_without_confirm(tmp_path: Path):
    assert nfl_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    assert not (tmp_path / "x.json").exists()


def test_refuses_to_overwrite(tmp_path: Path):
    out = tmp_path / "r.json"
    out.write_text("{}")
    assert nfl_evaluate.main(["--confirm", "--out", str(out)]) == 3
    assert out.read_text() == "{}"


def test_verdict_rules():
    v = nfl_evaluate.verdict({"log_loss": 0.65, "brier": 0.23, "ece": 0.049}, home_rate_ll=0.69)
    assert set(v.values()) == {"PASS"}
    v = nfl_evaluate.verdict({"log_loss": 0.67, "brier": 0.24, "ece": 0.06}, home_rate_ll=0.66)
    assert set(v.values()) == {"FAIL"}
