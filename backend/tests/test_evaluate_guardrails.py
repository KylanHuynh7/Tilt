"""Tests for the §10 #1 guardrails on the test-set evaluator.

These do NOT exercise the actual test-set replay — that's exactly what §10 #1
forbids touching during development. They only verify that the script refuses
to run without explicit acknowledgement.
"""

from pathlib import Path

import pytest

from scripts import evaluate


def test_refuses_without_confirm(capsys: pytest.CaptureFixture[str]):
    rc = evaluate.main(["--out", "/tmp/should_never_be_written.json"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err
    assert "--confirm" in captured.err


def test_refuses_when_output_exists_without_force(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    existing = tmp_path / "test_evaluation.json"
    existing.write_text("{}")
    rc = evaluate.main(["--confirm", "--out", str(existing)])
    assert rc == 3
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err
    assert "--force" in captured.err
    # Make sure the existing file is not overwritten.
    assert existing.read_text() == "{}"


def test_v1_results_do_not_block_first_v2_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A v1 results file at the default path is snapshotted, then treated as
    overwritable, so the first v2 run doesn't need --force. The run is stopped
    right after the guards by pointing the frozen-params load at a missing file.
    """
    active = tmp_path / "test_evaluation.json"
    snapshot = tmp_path / "test_evaluation_v1.json"
    active.write_text('{"methodology_version": "1.2"}')
    monkeypatch.setattr(evaluate, "DEFAULT_OUT", active)
    monkeypatch.setattr(evaluate, "V1_RESULTS_SNAPSHOT", snapshot)
    monkeypatch.setattr(evaluate, "ARTIFACT_PATH", tmp_path / "missing.json")

    with pytest.raises(SystemExit, match="no frozen-params artifact"):
        evaluate.main(["--confirm", "--out", str(active)])
    assert snapshot.read_text() == '{"methodology_version": "1.2"}'


def test_v2_results_still_block_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    active = tmp_path / "test_evaluation.json"
    active.write_text('{"methodology_version": "2.0"}')
    monkeypatch.setattr(evaluate, "DEFAULT_OUT", active)
    monkeypatch.setattr(evaluate, "V1_RESULTS_SNAPSHOT", tmp_path / "test_evaluation_v1.json")

    rc = evaluate.main(["--confirm", "--out", str(active)])
    assert rc == 3
    assert "REFUSED" in capsys.readouterr().err
    assert active.read_text() == '{"methodology_version": "2.0"}'
