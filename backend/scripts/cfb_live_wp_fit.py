"""Fit the CFB v1.1 live model on 2004–2013 FBS-vs-FBS play-by-play only.

    uv run python -m scripts.cfb_live_wp_fit
"""

from __future__ import annotations

import sys
import time

from app.cfb import live_wp, pbp


def main() -> int:
    if live_wp.ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {live_wp.ARTIFACT} exists; the live model is frozen.", file=sys.stderr)
        return 3
    t0 = time.time()
    pre = live_wp.pregame(pbp.TRAIN_SEASONS)
    xs, ys, meta = live_wp.build_samples(pbp.TRAIN_SEASONS, pre)
    beta = live_wp.fit(xs, ys)
    games = {m[0] for m in meta}
    chk = live_wp.checks(beta, [pre[g].home_win_prob for g in games])
    live_wp.save(beta, {"training_seasons": pbp.TRAIN_SEASONS, "n_games": len(games), "n_samples": len(xs),
                        "checks_on_training_range": chk})
    print(f"{len(games)} games, {len(xs)} plays ({time.time() - t0:.0f}s)")
    print("  " + "  ".join(f"β{i} {b:+.5f}" for i, b in enumerate(beta)))
    for k, v in chk.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
