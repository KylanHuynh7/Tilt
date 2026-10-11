"""MLB v1.1 live-WP one-shot test evaluation (methodology/MLB.md §12, DECISION 6).

Targets: beat the pre-game-held baseline on LL in every third of the game
(innings 1–3, 4–6, 7+); overall ECE < 0.03; first pitch within 0.02 of
pre-game; monotone in d; away leading by 5 with 2 out in the bottom of the
9th ≥ 0.97.

    uv run python -m scripts.mlb_live_wp_evaluate --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.logistic import sigmoid
from app.mlb import live_wp, pbp, tuner

OUT = Path(__file__).resolve().parent.parent / "results" / "mlb" / "live_wp_test_evaluation.json"
THIRDS = {"innings_1_3": range(1, 4), "innings_4_6": range(4, 7), "innings_7_plus": range(7, 30)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scripts.mlb_live_wp_evaluate")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the held-out MLB test seasons (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists() and not a.force:
        print(f"REFUSED: results already exist at {a.out} (§10 #2).", file=sys.stderr)
        return 3
    beta, re = live_wp.load()
    seasons = pbp.TEST_SEASONS
    pre = live_wp.pregame(seasons)
    xs, ys, meta = live_wp.build_samples(seasons, pre, re)
    held = [pre[m[0]].home_win_prob for m in meta]
    live = [sigmoid(sum(b * v for b, v in zip(beta, x))) for x in xs]

    def blk(idx):
        if not idx:
            return {"n": 0}
        y = [ys[i] for i in idx]
        return {"n": len(idx), "n_games": len({meta[i][0] for i in idx}),
                "live_model": tuner.score([live[i] for i in idx], y),
                "pregame_held_baseline": tuner.score([held[i] for i in idx], y),
                "naive_baseline": tuner.score([0.5] * len(idx), y)}

    allidx = list(range(len(xs)))
    overall = blk(allidx)
    by_third = {k: blk([i for i in allidx if meta[i][1] in r]) for k, r in THIRDS.items()}
    season_of = {g: pr.season for g, pr in pre.items()}
    by_season = {str(s): blk([i for i in allidx if season_of[meta[i][0]] == s]) for s in seasons}
    chk = live_wp.checks(beta, re, [pre[g].home_win_prob for g in {m[0] for m in meta}])
    beats = {k: b["live_model"]["log_loss"] < b["pregame_held_baseline"]["log_loss"] for k, b in by_third.items()}
    verdict = {
        "beats_pregame_held_every_third": "PASS" if all(beats.values()) else "FAIL",
        "overall_ece_below_0_03": "PASS" if overall["live_model"]["ece"] < 0.03 else "FAIL",
        "first_pitch_within_0_02": "PASS" if chk["first_pitch_within_0_02"] else "FAIL",
        "monotone_in_score_diff": "PASS" if chk["monotone_in_score_diff"] else "FAIL",
        "leader_by_5_bottom_9_ge_0_97": "PASS" if chk["leader_by_5_bottom_9_two_outs_ge_0_97"] else "FAIL",
    }
    payload = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "coefficients": dict(zip(["b0", "b1", "b2"], beta)),
               "test_seasons": seasons, "overall": overall, "by_third": by_third, "by_season": by_season,
               "beats_pregame_by_third": beats, "checks_on_test_range": chk, "verdict": verdict,
               "notes": ["Per §10 #1 this script reads the test seasons exactly once."]}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    for name, b in {"overall": overall, **by_third, **by_season}.items():
        if b.get("n"):
            m, h = b["live_model"], b["pregame_held_baseline"]
            print(f"  {name:<15} n={b['n']:<7} live LL {m['log_loss']:.5f} ECE {m['ece']:.4f} | held LL {h['log_loss']:.5f} ECE {h['ece']:.4f}")
    print("verdict:", verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
