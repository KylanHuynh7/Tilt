"""CFB v1.1 live-WP one-shot test evaluation (methodology/CFB.md §12, DECISION 6 = NFL's).

Targets: beat the pre-game-held baseline on LL in every quarter (OT reported,
not required); overall ECE < 0.05; kickoff within 0.02; monotone in d; 17+
point lead with 2 min left ≥ 0.97.

    uv run python -m scripts.cfb_live_wp_evaluate --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.logistic import sigmoid
from app.cfb import live_wp, pbp, tuner

OUT = Path(__file__).resolve().parent.parent / "results" / "cfb" / "live_wp_test_evaluation.json"
QUARTERS = {"Q1": (1,), "Q2": (2,), "Q3": (3,), "Q4": (4,), "OT": tuple(range(5, 20))}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scripts.cfb_live_wp_evaluate")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the held-out CFB test seasons (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists() and not a.force:
        print(f"REFUSED: results already exist at {a.out} (§10 #2).", file=sys.stderr)
        return 3
    beta = live_wp.load()
    pre = live_wp.pregame(pbp.TEST_SEASONS)
    xs, ys, meta = live_wp.build_samples(pbp.TEST_SEASONS, pre)
    live = [sigmoid(sum(b * v for b, v in zip(beta, x))) for x in xs]
    held = [pre[m[0]].home_win_prob for m in meta]

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
    by_q = {k: blk([i for i in allidx if meta[i][1] in v]) for k, v in QUARTERS.items()}
    season_of = {g: pr.season for g, pr in pre.items()}
    by_season = {str(s): blk([i for i in allidx if season_of[meta[i][0]] == s]) for s in pbp.TEST_SEASONS}
    chk = live_wp.checks(beta, [pre[g].home_win_prob for g in {m[0] for m in meta}])
    beats = {k: b["live_model"]["log_loss"] < b["pregame_held_baseline"]["log_loss"]
             for k, b in by_q.items() if k != "OT" and b.get("n")}
    verdict = {"beats_pregame_held_every_quarter": "PASS" if all(beats.values()) else "FAIL",
               "overall_ece_below_0_05": "PASS" if overall["live_model"]["ece"] < 0.05 else "FAIL",
               "kickoff_within_0_02": "PASS" if chk["kickoff_within_0_02"] else "FAIL",
               "monotone_in_score_diff": "PASS" if chk["monotone_in_score_diff"] else "FAIL",
               "leader_by_17_late_ge_0_97": "PASS" if chk["leader_by_17_with_2_min_left_ge_0_97"] else "FAIL"}
    payload = {"evaluated_at": datetime.now(timezone.utc).isoformat(),
               "coefficients": json.loads(live_wp.ARTIFACT.read_text())["coefficients"],
               "test_seasons": pbp.TEST_SEASONS, "overall": overall, "by_quarter": by_q, "by_season": by_season,
               "beats_pregame_by_quarter": beats, "checks_on_test_range": chk, "verdict": verdict,
               "notes": ["FBS-vs-FBS only.", "Per §10 #1 this script reads the test seasons exactly once."]}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    for name, b in {"overall": overall, **by_q, **by_season}.items():
        if b.get("n"):
            m, h = b["live_model"], b["pregame_held_baseline"]
            print(f"  {name:<8} n={b['n']:<7} live LL {m['log_loss']:.5f} ECE {m['ece']:.4f} | held LL {h['log_loss']:.5f} ECE {h['ece']:.4f}")
    print("verdict:", verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
