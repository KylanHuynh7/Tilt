"""Freeze the NBA model (methodology/NBA.md §5, §8, §9 #4).

Runs the 1,200-cell validation grid, prints the §8 pre-freeze checks
(home-court trend across validation seasons, home bump vs the pre-registered
range, MOV on vs off), and writes artifacts/nba/frozen_params.json with the
winner and the full grid. Test seasons are never loaded.

    uv run python -m scripts.nba_freeze
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.nba import tuner

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "nba" / "frozen_params.json"
METHODOLOGY_VERSION = "nba-1.1"


def main() -> int:
    if ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {ARTIFACT} exists. The NBA model is frozen; re-freezing after "
              "test evaluation would violate §10 #2.", file=sys.stderr)
        return 3

    rows = tuner.load_rows()
    print(f"warm-up {tuner.warmup_seasons()[0]} → {tuner.warmup_seasons()[-1]}, "
          f"validation {tuner.VALIDATION_SEASONS}")
    grid = tuner.grid_search(rows, progress=True)
    best = grid[0]
    _, preds = tuner.evaluate(best.params, rows)

    # §8 pre-freeze checks (validation data only).
    per_season_home = {}
    for sid in tuner.VALIDATION_SEASONS:
        sp = [p for p in preds if p.season_id == sid]
        per_season_home[str(sid)] = round(tuner.home_rate(sp), 4)
    rate = tuner.home_rate(preds)
    actuals = [1.0 if p.home_won else 0.0 for p in preds]
    home_rate_baseline = tuner.score(tuner.home_rate_probs(preds, rate), actuals)
    naive = tuner.score([0.5] * len(preds), actuals)
    best_other_mov = next(r for r in grid if r.params.mov != best.params.mov)

    payload = {
        "methodology_version": METHODOLOGY_VERSION,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "warmup_seasons": tuner.warmup_seasons(),
        "validation_seasons": tuner.VALIDATION_SEASONS,
        "test_seasons_untouched": tuner.TEST_SEASONS_DO_NOT_TOUCH,
        "winner": best.to_dict(),
        "validation_baselines": {
            "naive": naive,
            "home_rate": {**home_rate_baseline, "rate": round(rate, 4)},
            "static_rating": best.static,
        },
        "pre_freeze_checks": {
            "home_win_rate_by_validation_season": per_season_home,
            "home_bump_in_preregistered_range_50_110": 50 <= best.params.home_bump <= 110,
            "home_bump_outside_wiring_bug_range_30_150": not (30 <= best.params.home_bump <= 150),
            "best_with_opposite_mov": best_other_mov.to_dict(),
            "k_playoff_vs_k_regular": (
                "higher" if best.params.k_playoff > best.params.k_regular
                else "equal" if best.params.k_playoff == best.params.k_regular else "lower"
            ),
        },
        "grid": [r.to_dict() for r in grid],
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, indent=2))

    m = best.model
    print(f"\nwinner: {best.params}")
    print(f"  validation  LL {m['log_loss']:.5f}  Brier {m['brier']:.5f}  ECE {m['ece']:.5f}  n={m['n']}")
    for name, b in (("naive", naive), ("home-rate", home_rate_baseline), ("static", best.static)):
        print(f"  {name:<10}  LL {b['log_loss']:.5f}  Brier {b['brier']:.5f}  ECE {b['ece']:.5f}")
    o = best_other_mov
    print(f"  best with mov={o.params.mov}: LL {o.model['log_loss']:.5f} ({o.params})")
    print(f"  home win rate by validation season: {per_season_home}")
    print(f"\nwrote {ARTIFACT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
