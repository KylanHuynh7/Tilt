"""Fit the NBA v1.1 live-WP model (methodology/NBA.md §12, v1.2).

Training seasons only (2009-10 → 2017-18). Writes artifacts/nba/live_wp_v1.json
with the three coefficients and the §12 checks computed on the training
pre-game range. Refuses to overwrite an existing fit without --force.

    uv run python -m scripts.nba_live_wp_fit
"""

from __future__ import annotations

import sys
import time

from app.nba import live_wp, pbp


def main() -> int:
    if live_wp.ARTIFACT.exists() and "--force" not in sys.argv:
        print(f"REFUSED: {live_wp.ARTIFACT} exists; the live model is frozen.", file=sys.stderr)
        return 3
    seasons = pbp.TRAIN_SEASONS
    t0 = time.time()
    pre = live_wp.pregame_predictions(seasons)
    samples = live_wp.build_samples(seasons, pre)
    n_games = len({s.game_id for s in samples})
    print(f"training seasons {seasons[0]} → {seasons[-1]}: {n_games} games, {len(samples)} samples")
    model = live_wp.fit(samples)
    used_ps = [pre[g].home_win_prob for g in {s.game_id for s in samples}]
    chk = live_wp.checks(model, used_ps)
    live_wp.save(model, {
        "training_seasons": seasons,
        "n_games": n_games,
        "n_samples": len(samples),
        "checks_on_training_range": chk,
    })
    print(f"β0 = {model.b0:+.5f}   β1 = {model.b1:+.5f}   β2 = {model.b2:+.5f}   ({time.time() - t0:.1f}s)")
    for k, v in chk.items():
        print(f"  {k}: {v}")
    print(f"wrote {live_wp.ARTIFACT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
