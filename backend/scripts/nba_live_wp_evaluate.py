"""NBA v1.1 live-WP one-shot test evaluation (methodology/NBA.md §12, v1.2).

Scores the frozen live model on the test seasons (2024-25, 2025-26) exactly
once: LL / Brier / ECE overall and per quarter (Q1-Q4, OT) against the two
context baselines (pre-game probability held all game; 0.5), plus the three
§12 checks over the test pre-game range. No pass/fail targets exist (v1.2 d).

    uv run python -m scripts.nba_live_wp_evaluate --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.nba import live_wp, pbp, tuner

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "results" / "nba" / "live_wp_test_evaluation.json"
PERIODS = {"Q1": (1,), "Q2": (2,), "Q3": (3,), "Q4": (4,), "OT": tuple(range(5, 12))}


def score_block(samples, model) -> dict:
    if not samples:
        return {"n": 0}
    ys = [1.0 if s.home_won else 0.0 for s in samples]
    m = [live_wp.sigmoid(model.b0 + model.b1 * s.features()[0] + model.b2 * s.features()[1])
         for s in samples]
    pre = [live_wp.sigmoid(s.pre) for s in samples]
    return {
        "n": len(samples),
        "n_games": len({s.game_id for s in samples}),
        "live_model": tuner.score(m, ys),
        "pregame_held_baseline": tuner.score(pre, ys),
        "naive_baseline": tuner.score([0.5] * len(ys), ys),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.nba_live_wp_evaluate")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    if not args.confirm:
        print("REFUSED: reads the held-out NBA test seasons (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if args.out.exists() and not args.force:
        print(f"REFUSED: results already exist at {args.out} (§10 #2).", file=sys.stderr)
        return 3
    if not live_wp.ARTIFACT.exists():
        raise SystemExit("ERROR: no fitted live model; run scripts.nba_live_wp_fit first.")

    model = live_wp.load()
    artifact = json.loads(live_wp.ARTIFACT.read_text())
    seasons = pbp.TEST_SEASONS
    print(f"NBA LIVE-WP TEST EVALUATION — test seasons {seasons} (read once)")
    print(f"coefficients: {artifact['coefficients']}")

    pre = live_wp.pregame_predictions(seasons)
    samples = live_wp.build_samples(seasons, pre)
    overall = score_block(samples, model)
    by_period = {k: score_block([s for s in samples if s.period in v], model) for k, v in PERIODS.items()}
    by_season = {}
    game_season = {gid: pr.season_id for gid, pr in pre.items()}
    for sid in seasons:
        by_season[str(sid)] = score_block([s for s in samples if game_season[s.game_id] == sid], model)
    used = [pre[g].home_win_prob for g in {s.game_id for s in samples}]
    chk = live_wp.checks(model, used)

    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": artifact["methodology_version"],
        "coefficients": artifact["coefficients"],
        "test_seasons": seasons,
        "overall": overall,
        "by_period": by_period,
        "by_season": by_season,
        "checks_on_test_range": chk,
        "notes": ["No pass/fail targets were pre-registered for the live model (NBA v1.2 d).",
                  "Per §10 #1 this script reads the test seasons exactly once."],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    def line(name, b):
        if not b.get("n"):
            return
        m, h = b["live_model"], b["pregame_held_baseline"]
        print(f"  {name:<8} n={b['n']:<7} live LL {m['log_loss']:.5f} Brier {m['brier']:.5f} ECE {m['ece']:.4f}"
              f"   | pre-game-held LL {h['log_loss']:.5f} ECE {h['ece']:.4f}")
    line("overall", overall)
    for k, b in {**by_period, **by_season}.items():
        line(k, b)
    for k, v in chk.items():
        print(f"  {k}: {v}")
    print(f"results written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
