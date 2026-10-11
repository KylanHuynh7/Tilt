"""Freeze the NFL model (methodology/NFL.md §5, §8, §9).

Runs the 1,440-cell validation grid, prints the §8 pre-freeze checks, and
writes artifacts/nfl/frozen_params.json. Test seasons are never loaded.

    uv run python -m scripts.nfl_freeze
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.nfl import tuner

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "nfl" / "frozen_params.json"


def main() -> int:
    if ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {ARTIFACT} exists; the NFL model is frozen (§10 #2).", file=sys.stderr)
        return 3
    rows = tuner.load_rows()
    grid = tuner.grid_search(rows)
    best = grid[0]
    _, preds = tuner.evaluate(best.params, rows)
    actuals = [p.outcome for p in preds]
    rate = tuner.home_rate(preds)
    by_season = {str(s): round(tuner.home_rate([p for p in preds if p.season == s]), 4)
                 for s in tuner.VALIDATION_SEASONS}
    other_mov = next(r for r in grid if r.params.mov != best.params.mov)
    constrained = next(r for r in grid if r.params.k_playoff >= r.params.k_regular)
    payload = {
        "methodology_version": "nfl-1.0",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "warmup_seasons": tuner.WARMUP_SEASONS,
        "validation_seasons": tuner.VALIDATION_SEASONS,
        "test_seasons_untouched": tuner.TEST_SEASONS_DO_NOT_TOUCH,
        "winner": best.to_dict(),
        "validation_baselines": {
            "naive": tuner.score([0.5] * len(preds), actuals),
            "home_rate": {**tuner.score(tuner.home_rate_probs(preds, rate), actuals), "rate": round(rate, 4)},
            "static_rating": best.static,
        },
        "pre_freeze_checks": {
            "home_rate_by_validation_season": by_season,
            "home_bump_in_preregistered_range_20_60": 20 <= best.params.home_bump <= 60,
            "home_bump_wiring_bug_flag_outside_0_120": not (0 <= best.params.home_bump <= 120),
            "best_with_opposite_mov": other_mov.to_dict(),
            "best_with_k_playoff_ge_k_regular": constrained.to_dict(),
        },
        "grid": [r.to_dict() for r in grid],
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, indent=2))
    m = best.model
    print(f"winner: {best.params}")
    print(f"  validation LL {m['log_loss']:.5f}  Brier {m['brier']:.5f}  ECE {m['ece']:.5f}  n={m['n']}")
    for k, b in payload["validation_baselines"].items():
        print(f"  {k:<14} LL {b['log_loss']:.5f}  Brier {b['brier']:.5f}  ECE {b['ece']:.5f}")
    print(f"  best mov={other_mov.params.mov}: LL {other_mov.model['log_loss']:.5f} ({other_mov.params})")
    print(f"  best K_po>=K_reg: LL {constrained.model['log_loss']:.5f} ({constrained.params})")
    print(f"  home rate by season: {by_season}")
    print(f"wrote {ARTIFACT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
