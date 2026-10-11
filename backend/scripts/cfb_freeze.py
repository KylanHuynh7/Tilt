"""Freeze the college football model (methodology/CFB.md §5, §8). Test seasons never loaded.

    uv run python -m scripts.cfb_freeze
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.cfb import backtest, tuner

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "cfb" / "frozen_params.json"


def main() -> int:
    if ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {ARTIFACT} exists; the CFB model is frozen (§10 #2).", file=sys.stderr)
        return 3
    seasons, data = tuner.load_data()
    grid = tuner.grid_search(seasons, data)
    best = grid[0]
    _, preds, res = tuner.evaluate(best.params, seasons, data)
    ys = [p.outcome for p in preds]
    rate = tuner.home_rate(preds)
    warm = backtest.run(tuner.WARMUP_SEASONS, best.params, data=data)
    fbs_vals = [v for k, v in res.ratings.items() if k != "FCS"]
    other_mov = next(r for r in grid if r.params.mov != best.params.mov)
    constrained = next(r for r in grid if r.params.k_post >= r.params.k_regular)
    by_season = {str(s): round(tuner.home_rate([p for p in preds if p.season == s]), 4) for s in tuner.VALIDATION_SEASONS}
    payload = {
        "methodology_version": "cfb-1.2", "frozen_at": datetime.now(timezone.utc).isoformat(),
        "warmup_seasons": tuner.WARMUP_SEASONS, "validation_seasons": tuner.VALIDATION_SEASONS,
        "test_seasons_untouched": tuner.TEST_SEASONS_DO_NOT_TOUCH, "winner": best.to_dict(),
        "validation_baselines": {
            "naive": tuner.score([0.5] * len(ys), ys),
            "home_rate": {**tuner.score(tuner.home_rate_probs(preds, rate), ys), "rate": round(rate, 4)},
            "static_rating": tuner.score(tuner.static_probs(preds, warm.ratings, best.params), ys),
        },
        "pre_freeze_checks": {
            "home_rate_by_validation_season": by_season,
            "home_bump_in_preregistered_range_40_100": 40 <= best.params.home_bump <= 100,
            "home_bump_wiring_bug_flag_outside_0_160": not (0 <= best.params.home_bump <= 160),
            "fbs_rating_range_end_of_validation": [round(min(fbs_vals), 1), round(max(fbs_vals), 1)],
            "fbs_ratings_inside_1100_1900": min(fbs_vals) > 1100 and max(fbs_vals) < 1900,
            "fcs_pool_end_of_validation": round(res.ratings["FCS"], 1),
            "best_with_opposite_mov": other_mov.to_dict(),
            "best_with_k_post_ge_k_regular": constrained.to_dict(),
        },
        "grid": [r.to_dict() for r in grid],
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, indent=2))
    m = best.model
    print(f"winner: {best.params}")
    print(f"  validation LL {m['log_loss']:.5f} Brier {m['brier']:.5f} ECE {m['ece']:.5f} n={m['n']}")
    for k, b in payload["validation_baselines"].items():
        print(f"  {k:<14} LL {b['log_loss']:.5f} Brier {b['brier']:.5f} ECE {b['ece']:.5f}")
    for k, v in payload["pre_freeze_checks"].items():
        print(f"  {k}: {v['model']['log_loss'] if isinstance(v, dict) and 'model' in v else v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
