"""Fit the MLB v1.1 live model on training seasons 2010–2014 only.

    uv run python -m scripts.mlb_live_wp_fit
"""

from __future__ import annotations

import sys
import time

from app.mlb import live_wp, pbp


def main() -> int:
    if live_wp.ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {live_wp.ARTIFACT} exists; the live model is frozen.", file=sys.stderr)
        return 3
    t0 = time.time()
    seasons = pbp.TRAIN_SEASONS
    re = live_wp.run_expectancy(seasons)
    pre = live_wp.pregame(seasons)
    xs, ys, meta = live_wp.build_samples(seasons, pre, re)
    beta = live_wp.fit(xs, ys)
    games = {m[0] for m in meta}
    chk = live_wp.checks(beta, re, [pre[g].home_win_prob for g in games])
    live_wp.save(beta, re, {"training_seasons": seasons, "n_games": len(games), "n_samples": len(xs),
                            "checks_on_training_range": chk})
    print(f"{len(games)} games, {len(xs)} PAs ({time.time() - t0:.0f}s)")
    print(f"  β0 {beta[0]:+.5f}  β1 {beta[1]:+.5f}  β2 {beta[2]:+.5f}")
    print("  RE (0 out, empty) {:.3f}  (0 out, loaded) {:.3f}  (2 out, empty) {:.3f}".format(
        re[(0, 0)], re[(0, 7)], re[(2, 0)]))
    for k, v in chk.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
