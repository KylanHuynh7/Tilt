"""MLB v2 one-shot test on the 2026 season (methodology/MLB.md §14, MLB-v2-2).

Pass (all): v1 §6 thresholds (LL < 0.685, Brier 0.235–0.248, ECE < 0.03,
beats home-rate); LL ≥ 0.001 below frozen v1 on the same games; pitcher term
≥ 0.002 LL better than team-only. Refuses until the 2026 World Series is decided.

    uv run python -m scripts.mlb_v2_evaluate --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.mlb import backtest, ratings, tuner
from app.mlb.api import load_params
from scripts.postseason_evaluate import season_complete

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "artifacts" / "mlb" / "frozen_params_v2.json"
OUT = ROOT / "results" / "mlb" / "test_evaluation_v2.json"
SEASONS = list(range(2000, 2027))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scripts.mlb_v2_evaluate")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the MLB v2 test season (2026). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists():
        print(f"REFUSED: {a.out} exists (one-shot).", file=sys.stderr)
        return 3
    if not season_complete("mlb", 2026):
        print("REFUSED: the 2026 World Series is not decided in the ingested data.", file=sys.stderr)
        return 4
    w = json.loads(V2.read_text())["winner"]
    fields = ratings.Params.__dataclass_fields__
    v2 = ratings.Params(**{k: w[k] for k in fields})
    data = backtest.load(SEASONS)

    def run(p):
        res = backtest.run(SEASONS, p, data=data, record_predictions_for={2026})
        return res.predictions

    p2, p1 = run(v2), run(load_params())
    pt = run(ratings.Params(**({k: w[k] for k in fields} | {"c": 0.0})))
    y = [x.outcome for x in p2]
    s2, s1, st = (tuner.score([x.home_win_prob for x in ps], y) for ps in (p2, p1, pt))
    rate = tuner.home_rate(p2)
    shr = tuner.score(tuner.home_rate_probs(p2, rate), y)
    v = {"ll_below_0_685": s2["log_loss"] < 0.685, "brier_0_235_0_248": 0.235 <= s2["brier"] <= 0.248,
         "ece_below_0_03": s2["ece"] < 0.03, "beats_home_rate": s2["log_loss"] < shr["log_loss"],
         "beats_v1_by_0_001": s1["log_loss"] - s2["log_loss"] >= 0.001,
         "pitcher_term_gain_ge_0_002": st["log_loss"] - s2["log_loss"] >= 0.002}
    payload = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "test_season": 2026,
               "v2": s2, "v1": s1, "v2_team_only": st, "home_rate_baseline": shr,
               "verdict": {k: "PASS" if ok else "FAIL" for k, ok in v.items()}, "all_pass": all(v.values())}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
