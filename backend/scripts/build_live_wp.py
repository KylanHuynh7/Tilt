"""Build the v2.2 empirical live-WP lookup table from ingested play-by-play data.

Usage:
    uv run python -m scripts.build_live_wp [--out PATH] [--season SEASON ...]

Default: trains on every season in the v2.2 training window per §15
(2010-11 → 2024-25). The 2025-26 season is held out and never read.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from app import live_wp, pbp_pipeline


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.build_live_wp",
                                description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path, default=live_wp.DEFAULT_ARTIFACT,
                   help=f"output JSON path (default: {live_wp.DEFAULT_ARTIFACT})")
    p.add_argument("--season", type=int, action="append",
                   help="optional: train on only these seasons (default: full §15 window)")
    args = p.parse_args(argv)

    seasons = args.season if args.season else pbp_pipeline.TRAINING_SEASONS
    print(f"building live-WP model from {len(seasons)} season(s): "
          f"{seasons[0]} → {seasons[-1]}")
    t0 = time.time()
    model = live_wp.build(training_seasons=seasons)
    dt = time.time() - t0
    print(f"  built in {dt:.1f}s: {model.n_games} games, "
          f"{model.n_samples} samples, {len(model.bins)} bins")

    live_wp.write_artifact(model, args.out)
    print(f"  artifact written: {args.out}")

    # Quick sanity print
    sample_states = [
        ("game start",        1, 19, 0),
        ("P3 1-goal lead",    3, 19,  1),
        ("P3 trailing 1",     3, 19, -1),
        ("P3 1 min, tied",    3,  0,  0),
        ("P3 1 min, up 1",    3,  0,  1),
        ("P3 1 min, up 3",    3,  0,  3),
        ("OT, tied",          4,  4,  0),
    ]
    print("\nspot checks:")
    for label, period, mins, sd in sample_states:
        r = live_wp.query(model, period=period,
                          time_remaining_s=mins * 60 + 30, score_diff=sd)
        flag = "(smoothed)" if r.smoothed else ""
        print(f"  {label:<22s}  WP={r.home_win_prob:.3f}  n={r.n:>5}  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
