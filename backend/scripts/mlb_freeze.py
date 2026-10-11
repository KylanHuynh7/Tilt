"""Freeze the MLB model (methodology/MLB.md §5, §8). Test seasons never loaded.

    uv run python -m scripts.mlb_freeze
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.mlb import backtest, tuner

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "mlb" / "frozen_params.json"


def main() -> int:
    if ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {ARTIFACT} exists; the MLB model is frozen (§10 #2).", file=sys.stderr)
        return 3
    t0 = time.time()
    seasons, data = tuner.load_data()
    grid = tuner.grid_search(seasons, data, progress=True)
    best = grid[0]
    _, preds = tuner.evaluate(best.params, seasons, data)
    ys = [p.outcome for p in preds]
    warm = backtest.run(tuner.WARMUP_SEASONS, best.params, data=data)
    rate = tuner.home_rate(preds)
    team_only = next(r for r in grid if r.params.c == 0)
    other_mov = next(r for r in grid if r.params.mov != best.params.mov)
    constrained = next(r for r in grid if r.params.k_playoff >= r.params.k_regular)
    by_season = {str(s): round(tuner.home_rate([p for p in preds if p.season == s]), 4) for s in tuner.VALIDATION_SEASONS}
    payload = {
        "methodology_version": "mlb-1.1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "warmup_seasons": tuner.WARMUP_SEASONS,
        "validation_seasons": tuner.VALIDATION_SEASONS,
        "test_seasons_untouched": tuner.TEST_SEASONS_DO_NOT_TOUCH,
        "winner": best.to_dict(),
        "validation_baselines": {
            "naive": tuner.score([0.5] * len(ys), ys),
            "home_rate": {**tuner.score(tuner.home_rate_probs(preds, rate), ys), "rate": round(rate, 4)},
            "static_rating": tuner.score(tuner.static_probs(preds, warm.ratings, best.params.home_bump), ys),
            "best_team_only_c0": team_only.to_dict(),
        },
        "pre_freeze_checks": {
            "home_rate_by_validation_season": by_season,
            "home_bump_in_preregistered_range_15_40": 15 <= best.params.home_bump <= 40,
            "home_bump_wiring_bug_flag_outside_0_80": not (0 <= best.params.home_bump <= 80),
            "best_with_opposite_mov": other_mov.to_dict(),
            "best_with_k_playoff_ge_k_regular": constrained.to_dict(),
        },
        "grid": [r.to_dict() for r in grid],
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, indent=2))
    m = best.model
    print(f"winner: {best.params}  ({time.time() - t0:.0f}s)")
    print(f"  validation LL {m['log_loss']:.5f} Brier {m['brier']:.5f} ECE {m['ece']:.5f} n={m['n']}")
    for k, b in payload["validation_baselines"].items():
        mm = b.get("model", b)
        print(f"  {k:<18} LL {mm['log_loss']:.5f} Brier {mm['brier']:.5f} ECE {mm['ece']:.5f}")
    print(f"  best mov={other_mov.params.mov}: LL {other_mov.model['log_loss']:.5f}")
    print(f"  best K_po>=K_reg: LL {constrained.model['log_loss']:.5f}")
    print(f"  home rate by season: {by_season}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
