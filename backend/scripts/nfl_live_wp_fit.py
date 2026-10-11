"""Fit the NFL v1.1 live-WP model on training seasons 2004–2014 only.

    uv run python -m scripts.nfl_live_wp_fit
"""

from __future__ import annotations

import sys
import time

from app.nfl import live_wp, pbp


def main() -> int:
    if live_wp.ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {live_wp.ARTIFACT} exists; the live model is frozen.", file=sys.stderr)
        return 3
    t0 = time.time()
    pre = live_wp.pregame_predictions(pbp.TRAIN_SEASONS)
    samples = live_wp.build_samples(pbp.TRAIN_SEASONS, pre)
    games = {s.game_id for s in samples}
    beta = live_wp.fit(samples)
    chk = live_wp.checks(beta, [pre[g].home_win_prob for g in games])
    live_wp.save(beta, {"training_seasons": pbp.TRAIN_SEASONS, "n_games": len(games),
                        "n_samples": len(samples), "checks_on_training_range": chk})
    print(f"{len(games)} games, {len(samples)} samples ({time.time() - t0:.1f}s)")
    print("  " + "  ".join(f"β{i} = {b:+.5f}" for i, b in enumerate(beta)))
    for k, v in chk.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
