"""Postseason calibration layer (methodology/POSTSEASON.md)."""

import pytest

from app.core import postseason as ps


def test_shrink_identity_and_direction():
    assert ps.shrink(0.8, 1.0) == pytest.approx(0.8)
    assert 0.5 < ps.shrink(0.8, 0.5) < 0.8 and 0.2 < ps.shrink(0.2, 0.5) < 0.5
    assert ps.shrink(0.5, 0.6) == pytest.approx(0.5)


def test_fit_recovers_shrink_for_overconfident_forecasts():
    # Forecasts of 0.8 that come true only 65% of the time want λ < 1.
    ps_, ys = [0.8] * 100, [1] * 65 + [0] * 35
    lam, table = ps.fit(ps_, ys)
    assert lam < 1.0 and table[lam] < table[1.0]
    # Well-calibrated forecasts keep λ = 1.
    lam, _ = ps.fit([0.8] * 100, [1] * 80 + [0] * 20)
    assert lam >= 0.95


def test_regular_season_untouched(monkeypatch):
    monkeypatch.setattr(ps, "_cache", {"mlb": {"lambda": 0.7, "active": True}})
    assert ps.apply("mlb", 0.7, False) == (0.7, None)
    p, lam = ps.apply("mlb", 0.7, True)
    assert lam == 0.7 and p < 0.7
    monkeypatch.setattr(ps, "_cache", {"mlb": {"lambda": 0.7, "active": False}})
    assert ps.apply("mlb", 0.7, True) == (0.7, None)


def test_evaluator_guards(tmp_path, monkeypatch):
    from scripts import postseason_evaluate as ev
    assert ev.main(["--sport", "mlb"]) == 2
    monkeypatch.setattr(ev, "OUT", tmp_path)
    (tmp_path / "mlb_2026.json").write_text("{}")
    assert ev.main(["--sport", "mlb", "--confirm"]) == 3
    (tmp_path / "mlb_2026.json").unlink()
    monkeypatch.setattr(ev, "season_complete", lambda s, y: False)
    assert ev.main(["--sport", "mlb", "--confirm"]) == 4


def test_mlb_v2_evaluator_guards(tmp_path):
    from scripts import mlb_v2_evaluate as ev
    assert ev.main(["--out", str(tmp_path / "x.json")]) == 2
    f = tmp_path / "r.json"
    f.write_text("{}")
    assert ev.main(["--confirm", "--out", str(f)]) == 3
    assert ev.main(["--confirm", "--out", str(tmp_path / "new.json")]) == 4     # World Series not decided yet


def test_mlb_v1_params_reproduce_v1_path():
    from app.mlb import ratings
    p = ratings.Params()
    assert p.pitcher_model == "rgs"     # v1 artifacts load onto the unchanged v1 path


def test_nfl_season_sim_invariants():
    from app.nfl import api, season_sim
    c = api.get_cache()
    r = season_sim.simulate(max(c.seasons), c.current, c.params, n=300)
    assert abs(sum(x["title"] for x in r.rows) - 1) < 1e-9
    assert abs(sum(x["playoffs"] for x in r.rows) - 14) < 1e-9
    assert abs(sum(x["division"] for x in r.rows) - 8) < 1e-9
    assert all(x["proj_wins"] >= x["wins_now"] for x in r.rows)
