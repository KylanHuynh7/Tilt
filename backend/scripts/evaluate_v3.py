"""NHL v3 one-shot test evaluation on 2026-27 (METHODOLOGY.md §17, §18, §20 V3-5, V3-7).

Runs ONCE, after the 2027 Stanley Cup Final. Refuses earlier (the season's
playoffs must be decided), refuses without --confirm, and never overwrites.
Reports v3 against the §6 targets (LL ≤ 0.685, Brier 0.235–0.245, ECE ≤ 0.04),
v3.1 vs v3.0 on the same games, and v2's frozen params for reference.

    uv run python -m scripts.evaluate_v3 --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import backtest, metrics, roster_moves, tuner_v3

ROOT = Path(__file__).resolve().parent.parent
V3 = ROOT / "artifacts" / "frozen_params_v3.json"
V2 = ROOT / "artifacts" / "frozen_params_v2.json"
OUT = ROOT / "results" / "test_evaluation_v3.json"
TEST = tuner_v3.TEST_SEASONS_DO_NOT_TOUCH        # [20262027]
KEYS = ("k_regular", "k_playoff", "decay_carry", "home_bump", "boost_window", "boost_amount", "round_scale", "elim_bump")


def cup_final_decided(season: int) -> bool:
    rows = backtest._load_season_rows(season)
    final = [r for r in rows if r["game_type"] == backtest.PLAYOFF and backtest.playoff_round(r["game_id"]) == 4
             and r.get("state") in backtest.FINAL_STATES]
    wins: dict[str, int] = {}
    for r in final:
        w = r["home"] if r["home_score"] > r["away_score"] else r["away"]
        wins[w] = wins.get(w, 0) + 1
    return any(v >= 4 for v in wins.values())


def score(params: dict, events) -> dict:
    p = backtest.BacktestParams(**{k: float(params.get(k, 0.0)) for k in KEYS})
    res = backtest.run(tuner_v3.TRAINING_SEASONS + tuner_v3.VALIDATION_SEASONS + TEST, params=p,
                       record_predictions_for=set(TEST), roster_events=events)
    probs = [x.home_win_prob for x in res.predictions]
    y = metrics.actuals_from_predictions(res.predictions)
    return {"n": len(probs), "log_loss": metrics.log_loss(probs, y), "brier": metrics.brier_score(probs, y),
            "ece": metrics.expected_calibration_error(probs, y)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scripts.evaluate_v3")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the v3 test season 2026-27 (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists():
        print(f"REFUSED: results already exist at {a.out} (§10 #2).", file=sys.stderr)
        return 3
    if not cup_final_decided(TEST[0]):
        print("REFUSED: the 2027 Stanley Cup Final is not decided in the ingested data (§20 V3-5).", file=sys.stderr)
        return 4
    v3 = json.loads(V3.read_text())
    events = roster_moves.events_for(tuner_v3.TRAINING_SEASONS + tuner_v3.VALIDATION_SEASONS + TEST)
    m31, m30 = score(v3["winner"], events), score(v3["v30_winner"], events)
    m2 = score(json.loads(V2.read_text())["winner"], events)
    verdict = {"log_loss_le_0_685": m31["log_loss"] <= 0.685,
               "brier_in_0_235_0_245": 0.235 <= m31["brier"] <= 0.245,
               "ece_le_0_04": m31["ece"] <= 0.04}
    payload = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "test_seasons": TEST,
               "v31_model": m31, "v30_model": m30, "v2_params_reference": m2,
               "verdict": {k: "PASS" if v else "FAIL" for k, v in verdict.items()}}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
