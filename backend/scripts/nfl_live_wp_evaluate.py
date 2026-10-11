"""NFL v1.1 live-WP one-shot test evaluation (methodology/NFL.md §12 + DECISION 6).

Pre-registered targets: beat the pre-game-held baseline on LL in every
quarter; overall ECE < 0.05; the three structural checks.

    uv run python -m scripts.nfl_live_wp_evaluate --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.logistic import sigmoid
from app.nfl import live_wp, pbp, tuner

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "results" / "nfl" / "live_wp_test_evaluation.json"
PERIODS = {"Q1": (1,), "Q2": (2,), "Q3": (3,), "Q4": (4,), "OT": (5, 6)}
ECE_MAX = 0.05


def block(samples, beta) -> dict:
    if not samples:
        return {"n": 0}
    ys = [s.outcome for s in samples]
    live = [sigmoid(sum(b * v for b, v in zip(beta, s.x()))) for s in samples]
    return {
        "n": len(samples), "n_games": len({s.game_id for s in samples}),
        "live_model": tuner.score(live, ys),
        "pregame_held_baseline": tuner.score([sigmoid(s.pre) for s in samples], ys),
        "naive_baseline": tuner.score([0.5] * len(ys), ys),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.nfl_live_wp_evaluate")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = p.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the held-out NFL test seasons (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists() and not a.force:
        print(f"REFUSED: results already exist at {a.out} (§10 #2).", file=sys.stderr)
        return 3
    if not live_wp.ARTIFACT.exists():
        raise SystemExit("ERROR: no fitted live model")

    beta = live_wp.load()
    pre = live_wp.pregame_predictions(pbp.TEST_SEASONS)
    samples = live_wp.build_samples(pbp.TEST_SEASONS, pre)
    overall = block(samples, beta)
    by_q = {k: block([s for s in samples if s.qtr in v], beta) for k, v in PERIODS.items()}
    season_of = {g: pr.season for g, pr in pre.items()}
    by_season = {str(y): block([s for s in samples if season_of[s.game_id] == y], beta) for y in pbp.TEST_SEASONS}
    chk = live_wp.checks(beta, [pre[g].home_win_prob for g in {s.game_id for s in samples}])
    beats = {k: b["live_model"]["log_loss"] < b["pregame_held_baseline"]["log_loss"]
             for k, b in by_q.items() if b.get("n")}
    verdict = {
        "beats_pregame_held_every_quarter": "PASS" if all(beats.values()) else "FAIL",
        "overall_ece_below_0_05": "PASS" if overall["live_model"]["ece"] < ECE_MAX else "FAIL",
        "kickoff_within_0_02": "PASS" if chk["kickoff_within_0_02"] else "FAIL",
        "monotone_in_score_diff": "PASS" if chk["monotone_in_score_diff"] else "FAIL",
        "leader_by_17_late_ge_0_97": "PASS" if chk["leader_by_17_with_2_min_left_ge_0_97"] else "FAIL",
    }
    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "coefficients": json.loads(live_wp.ARTIFACT.read_text())["coefficients"],
        "test_seasons": pbp.TEST_SEASONS, "overall": overall, "by_quarter": by_q,
        "by_season": by_season, "beats_pregame_by_quarter": beats,
        "checks_on_test_range": chk, "verdict": verdict,
        "notes": ["Per §10 #1 this script reads the test seasons exactly once."],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))

    def line(name, b):
        if b.get("n"):
            m, h = b["live_model"], b["pregame_held_baseline"]
            print(f"  {name:<8} n={b['n']:<7} live LL {m['log_loss']:.5f} ECE {m['ece']:.4f} | held LL {h['log_loss']:.5f} ECE {h['ece']:.4f}")
    line("overall", overall)
    for k, b in {**by_q, **by_season}.items():
        line(k, b)
    print("verdict:", verdict)
    print(f"results written: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
