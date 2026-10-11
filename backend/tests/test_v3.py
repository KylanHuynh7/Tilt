"""NHL v3 roster-shock boost (§17/§20 V3-1..V3-3) and series context (§18)."""

from datetime import date, timedelta

import pytest

from app import backtest, roster_moves


def _row(gid, d, team, pid, gt=2):
    return {"game_id": gid, "season_id": 20102011, "game_date": d, "game_type": gt, "team": team,
            "player_id": pid, "name": "X"}


def test_move_needs_ten_games_with_old_team():
    d0 = date(2010, 10, 1)
    rows = [_row(100 + i, d0 + timedelta(days=2 * i), "AAA", 1) for i in range(10)]
    rows += [_row(200, d0 + timedelta(days=30), "BBB", 1), _row(201, d0 + timedelta(days=31), "AAA", 2)]
    moves, events = roster_moves.detect(rows)
    assert len(moves) == 1 and moves[0].from_team == "AAA" and moves[0].games_with_old == 10
    assert events == {(200, "BBB"), (201, "AAA")}      # old team: first game on/after the move date
    # Nine games with the old team: not a move.
    moves, events = roster_moves.detect(rows[1:])
    assert moves == [] and events == set()


def test_boost_decays_linearly_and_ends_at_window():
    p = backtest.BacktestParams(boost_window=10, boost_amount=0.5)
    assert backtest._boost(10, 0, p) == pytest.approx(15)
    assert backtest._boost(10, 5, p) == pytest.approx(12.5)
    assert backtest._boost(10, 10, p) == 10 and backtest._boost(10, None, p) == 10
    assert backtest._boost(10, 0, backtest.BacktestParams(boost_window=10, boost_amount=0)) == 10


def test_playoff_k_by_round_and_elimination():
    p = backtest.BacktestParams(k_playoff=10, round_scale=0.1, elim_bump=0.2)
    v3 = backtest._V3State()
    gid = 2022030417            # round 4 (Final), series 1, game 7
    key = backtest.series_key(gid)
    v3.wins_needed[key] = 4
    v3.series_wins[key] = {"AAA": 3, "BBB": 3}
    assert backtest._playoff_k({"game_id": gid}, p, v3) == pytest.approx(10 * (1 + 0.3 + 0.2))
    v3.series_wins[key] = {"AAA": 1}
    assert backtest._playoff_k({"game_id": 2022030112}, p, v3) == pytest.approx(10)      # R1, not facing
    assert backtest._playoff_k({"game_id": 2019030001}, p, v3) == 10                     # 2020 qualifier


def test_zero_v3_params_reproduce_v2_exactly():
    seasons = [20182019, 20192020]
    base = backtest.BacktestParams(k_regular=10, k_playoff=10, decay_carry=0.85, home_bump=40)
    v2 = backtest.run(seasons, params=base)
    zero = backtest.BacktestParams(k_regular=10, k_playoff=10, decay_carry=0.85, home_bump=40,
                                   boost_window=10, boost_amount=0.0)
    v3 = backtest.run(seasons, params=zero, roster_events={(2018020001, "WSH")})
    assert [p.home_win_prob for p in v2.predictions] == [p.home_win_prob for p in v3.predictions]


def test_boost_requires_events():
    with pytest.raises(ValueError):
        backtest.run([20182019], params=backtest.BacktestParams(boost_window=10, boost_amount=0.5))


def test_event_boosts_only_the_flagged_team():
    seasons = [20182019]
    first = backtest._load_season_rows(20182019)
    g = next(r for r in first if r["game_type"] == 2)
    p = backtest.BacktestParams(k_regular=10, k_playoff=10, boost_window=10, boost_amount=1.0)
    plain = backtest.run(seasons, params=backtest.BacktestParams(k_regular=10, k_playoff=10), record_snapshots=True)
    boosted = backtest.run(seasons, params=p, roster_events={(g["game_id"], g["home"])}, record_snapshots=True)
    a = {(s.game_id, s.franchise_id): s.rating for s in plain.snapshots if s.game_id == g["game_id"]}
    b = {(s.game_id, s.franchise_id): s.rating for s in boosted.snapshots if s.game_id == g["game_id"]}
    moved = [k for k in a if a[k] != b[k]]
    assert len(moved) == 1          # only the home team's update doubled


def test_freeze_refuses_test_season_and_existing_artifact(tmp_path, monkeypatch):
    from app import tuner_v3
    from scripts import freeze_v3
    with pytest.raises(RuntimeError):
        tuner_v3.check_quarantine([20252026, 20262027])
    f = tmp_path / "v3.json"
    f.write_text("{}")
    monkeypatch.setattr(freeze_v3, "OUT", f)
    assert freeze_v3.main([]) == 3


def test_grid_sizes_match_methodology():
    from app import tuner_v3
    assert len(tuner_v3.V30_GRID) == 12_000 and len(tuner_v3.V31_SUBGRID) == 24
