"""NHL skater projections: walk-forward discipline and guardrails, offline."""

import math

import pytest

from app import projections as pj


def _rows(n_games=30):
    rows = []
    for g in range(n_games):
        gid = 2010020000 + g
        for pid, team, opp, home, pts in ((1, "AAA", "BBB", True, g % 2), (2, "BBB", "AAA", False, 0)):
            rows.append(pj.Row(20102011, gid, pid, team, opp, home, "F", 15.0, pts, 0))
    return rows


def test_predictions_use_only_past_games():
    rows = _rows()
    pri = pj.priors_for(rows)
    params = dict(H=40, m=1, H_toi=10, gamma=0.0, home=1.0)
    full = pj.replay(rows, "points", params, pri, {20102011})
    # Changing the LAST game's outcome cannot change any prediction.
    last = rows[-2]
    rows2 = rows[:-2] + [pj.Row(last.season, last.game_id, last.player_id, last.team, last.opponent,
                                last.is_home, last.pos, last.toi_min, 5, 5), rows[-1]]
    alt = pj.replay(rows2, "points", params, pj.priors_for(rows), {20102011})
    assert [p.p for p in full] == [p.p for p in alt]


def test_scorer_rated_above_non_scorer_and_probabilities_valid():
    rows = _rows()
    preds = pj.replay(rows, "points", dict(H=40, m=1, H_toi=10, gamma=0.0, home=1.0), pj.priors_for(rows), {20102011})
    last = {p.player_id: p.p for p in preds[-2:]}
    assert last[1] > last[2] and all(0 < p.p < 1 for p in preds)


def test_baseline_b_uses_position_rate_until_ten_games():
    rows = _rows()
    pri = pj.priors_for(rows)
    a, b = pj.baselines(rows, "points", pri, {20102011})
    assert b[:20] == a[:20]                       # first 10 games per player
    assert b[-2] == pytest.approx(1 - math.exp(-0.5), abs=0.06)


def test_splits_disjoint_and_grid_size():
    assert not set(pj.TEST_DO_NOT_TOUCH) & set(pj.WARMUP + pj.VALIDATION)
    assert len(pj.GRID) == 540


def test_evaluator_guardrails(tmp_path):
    from scripts import players_evaluate
    assert players_evaluate.main(["--out", str(tmp_path / "x.json")]) == 2
    f = tmp_path / "r.json"
    f.write_text("{}")
    assert players_evaluate.main(["--confirm", "--out", str(f)]) == 3
