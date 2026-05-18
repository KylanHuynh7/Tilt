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
