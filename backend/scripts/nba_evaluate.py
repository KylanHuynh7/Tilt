"""NBA one-shot test evaluation — methodology/NBA.md §6, §10 #1 quarantined.

The ONLY code path that scores predictions on the NBA test seasons (2024-25,
2025-26). Run exactly once. Every §6 breakdown is emitted in this single pass,
because a breakdown not produced now can never be added without re-touching
the test set (lesson from NHL §13.C / §13.J).

    uv run python -m scripts.nba_evaluate --confirm

Guardrails: refuses without --confirm; refuses to overwrite existing results
without --force; parameters come only from artifacts/nba/frozen_params.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import metrics
from app.nba import backtest, pipeline, ratings, tuner

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "artifacts" / "nba" / "frozen_params.json"
DEFAULT_OUT = ROOT / "results" / "nba" / "test_evaluation.json"

TARGETS = {"log_loss_max": 0.640, "brier_band": [0.200, 0.225], "ece_max": 0.04}
PLAYOFF_ECE_FLAG = 0.08


def load_frozen() -> tuple[ratings.Params, dict]:
    if not ARTIFACT.exists():
        raise SystemExit(f"ERROR: no frozen NBA artifact at {ARTIFACT}; run scripts.nba_freeze first.")
    a = json.loads(ARTIFACT.read_text())
    w = a["winner"]
    params = ratings.Params(
        k_regular=float(w["k_regular"]), k_playoff=float(w["k_playoff"]),
        carry=float(w["carry"]), home_bump=float(w["home_bump"]), mov=bool(w["mov"]),
    )
    return params, a


def segment(p: backtest.Prediction) -> str:
    """§6 segment by the mean of both teams' regular-season game numbers,
    with the 15 / 65 boundaries scaled to the season length.
    """
    if p.home_game_no is None:
        return "postseason"
    g = (p.home_game_no + p.away_game_no) / 2
    early = round(15 * p.season_length / 82)
    late = round(65 * p.season_length / 82)
    return "early" if g <= early else ("late" if g > late else "mid")


def block(preds, home_rate: float, static_ratings: dict[int, float], home_bump: float) -> dict:
    if not preds:
        return {"n": 0}
    actuals = [1.0 if p.home_won else 0.0 for p in preds]
    probs = [p.home_win_prob for p in preds]
    return {
        "n": len(preds),
        "model": tuner.score(probs, actuals),
        "naive_baseline": tuner.score([0.5] * len(preds), actuals),
        "home_rate_baseline": tuner.score(tuner.home_rate_probs(preds, home_rate), actuals),
        "static_rating_baseline": tuner.score(
            tuner.static_probs(preds, static_ratings, home_bump), actuals),
        "calibration_buckets": [
            {"lo": b.lo, "hi": b.hi, "n": b.n,
             "mean_predicted": b.mean_predicted, "mean_actual": b.mean_actual}
            for b in metrics.calibration_buckets(probs, actuals)
        ],
    }


def verdict(m: dict, home_rate_ll: float) -> dict:
    lo, hi = TARGETS["brier_band"]
    return {
        "log_loss": "PASS" if m["log_loss"] < TARGETS["log_loss_max"] else "FAIL",
        "brier": "PASS" if lo <= m["brier"] <= hi else "FAIL",
        "ece": "PASS" if m["ece"] < TARGETS["ece_max"] else "FAIL",
        "beats_home_rate_on_log_loss": "PASS" if m["log_loss"] < home_rate_ll else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.nba_evaluate")
    p.add_argument("--confirm", action="store_true", help="REQUIRED — acknowledges §10 #1")
    p.add_argument("--force", action="store_true", help="overwrite existing results (re-evaluation)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)

    if not args.confirm:
        print("REFUSED: this script reads the held-out NBA test seasons (§10 #1).", file=sys.stderr)
        print("Re-run with --confirm to acknowledge.", file=sys.stderr)
        return 2
    if args.out.exists() and not args.force:
        print(f"REFUSED: results already exist at {args.out}", file=sys.stderr)
        print("Re-run with --force only with a documented justification (§10 #2).", file=sys.stderr)
        return 3

    params, artifact = load_frozen()
    test = tuner.TEST_SEASONS_DO_NOT_TOUCH
    seasons = backtest.model_seasons(through=test[-1])
    for sid in test:
        cov = pipeline.load_manifest()[str(sid)]["coverage"]
        if not cov["passes"]:
            raise SystemExit(f"ERROR: test season {sid} fails coverage; refusing to evaluate.")

    print("=" * 72)
    print("NBA TEST-SET EVALUATION — §10 #1 quarantine")
    print("=" * 72)
    print(f"Frozen params:  {params}")
    print(f"Replay:         {seasons[0]} → {seasons[-1]}")
    print(f"TEST seasons (read once): {test}")
    print(f"Output:         {args.out}")
    print("=" * 72)

    full = backtest.run(seasons, params, record_predictions_for=set(test))
    through_val = backtest.run([s for s in seasons if s <= tuner.LAST_VALIDATION], params)
    static = through_val.ratings  # §6 static baseline: frozen at end of validation
    home_rate = artifact["validation_baselines"]["home_rate"]["rate"]
    preds = full.predictions

    def b(sub):
        return block(sub, home_rate, static, params.home_bump)

    overall = b(preds)
    postseason = [x for x in preds if x.season_type != pipeline.REGULAR]
    breakdowns = {
        "per_season": {str(s): b([x for x in preds if x.season_id == s]) for s in test},
        "regular_season": b([x for x in preds if x.season_type == pipeline.REGULAR]),
        "postseason_play_in_and_playoffs": b(postseason),
        "segments": {seg: b([x for x in preds if segment(x) == seg])
                     for seg in ("early", "mid", "late")},
        "neutral_site": b([x for x in preds if x.neutral]),
    }
    post_ece = breakdowns["postseason_play_in_and_playoffs"].get("model", {}).get("ece")
    seg = breakdowns["segments"]
    late_vs_mid = (seg["late"]["model"]["ece"] / seg["mid"]["model"]["ece"]
                   if seg["mid"]["n"] and seg["mid"]["model"]["ece"] else None)

    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": artifact["methodology_version"],
        "frozen_at": artifact["frozen_at"],
        "frozen_params": {
            "k_regular": params.k_regular, "k_playoff": params.k_playoff,
            "carry": params.carry, "home_bump": params.home_bump, "mov": params.mov,
        },
        "test_seasons": test,
        "home_rate_baseline_constant": home_rate,
        "segment_rule": "mean of both teams' regular-season game numbers; boundaries 15/65 scaled by season length / 82",
        "targets": TARGETS,
        "overall": overall,
        "verdict": verdict(overall["model"], overall["home_rate_baseline"]["log_loss"]),
        "flags": {
            "postseason_ece_above_0_08": bool(post_ece is not None and post_ece > PLAYOFF_ECE_FLAG),
            "late_segment_ece_over_2x_mid": bool(late_vs_mid is not None and late_vs_mid > 2.0),
            "late_over_mid_ece_ratio": late_vs_mid,
        },
        "breakdowns": breakdowns,
        "notes": [
            "Per §10 #1 this script reads the test seasons exactly once.",
            "Re-running with --force invalidates the evaluation unless a documented justification exists.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    print("\nRESULTS (test set):")
    for name in ("model", "naive_baseline", "home_rate_baseline", "static_rating_baseline"):
        m = overall[name]
        print(f"  {name:<24} LL={m['log_loss']:.5f}  Brier={m['brier']:.5f}  ECE={m['ece']:.4f}  n={m['n']}")
    print("\n§6 verdict:", payload["verdict"])
    print("flags:", payload["flags"])
    for key in ("regular_season", "postseason_play_in_and_playoffs", "neutral_site"):
        m = breakdowns[key].get("model")
        if m:
            print(f"  {key:<32} n={m['n']:<5} LL={m['log_loss']:.5f}  ECE={m['ece']:.4f}")
    for s, blk in {**breakdowns["per_season"], **breakdowns["segments"]}.items():
        m = blk["model"]
        print(f"  {s:<32} n={m['n']:<5} LL={m['log_loss']:.5f}  ECE={m['ece']:.4f}")
    print(f"\nresults written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
