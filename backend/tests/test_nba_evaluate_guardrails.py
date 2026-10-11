"""§10 #1 guardrails on the NBA test evaluator, plus its segment rule.
These never replay the test seasons.
"""

from datetime import date
from pathlib import Path

import pytest

from app.nba import backtest
from scripts import nba_evaluate


def test_refuses_without_confirm(tmp_path: Path, capsys):
    assert nba_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert not (tmp_path / "x.json").exists()


def test_refuses_to_overwrite_without_force(tmp_path: Path, capsys):
    out = tmp_path / "test_evaluation.json"
    out.write_text("{}")
    assert nba_evaluate.main(["--confirm", "--out", str(out)]) == 3
    assert out.read_text() == "{}"


def _pred(home_no, away_no, length=82):
    return backtest.Prediction(
        season_id=20242025, game_id=1, game_date=date(2025, 1, 1), season_type=2,
        home_team_id=1, away_team_id=2, home_win_prob=0.6, home_won=True, neutral=False,
        home_game_no=home_no, away_game_no=away_no, season_length=length,
    )


@pytest.mark.parametrize("h,a,length,expected", [
    (15, 15, 82, "early"), (16, 16, 82, "mid"), (65, 65, 82, "mid"), (66, 66, 82, "late"),
    (10, 22, 82, "mid"),      # mean 16
    (9, 9, 50, "early"),      # 1998-99-style short season: early ≤ round(15·50/82) = 9
    (41, 41, 50, "late"),     # late > round(65·50/82) = 40
])
def test_segment_rule(h, a, length, expected):
    assert nba_evaluate.segment(_pred(h, a, length)) == expected


def test_postseason_segment():
    p = _pred(None, None)
    assert nba_evaluate.segment(p) == "postseason"
