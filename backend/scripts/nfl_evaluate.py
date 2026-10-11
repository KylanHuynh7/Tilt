"""NFL one-shot test evaluation — methodology/NFL.md §6, §10 #1 quarantined.

Scores the frozen model on 2022–2025 exactly once, emitting every §6
breakdown in the same pass (per season, regular vs playoffs, week segments,
neutral site, calibration buckets) plus the §8 flags.

    uv run python -m scripts.nfl_evaluate --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import metrics
from app.nfl import backtest, pipeline, ratings, tuner

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "artifacts" / "nfl" / "frozen_params.json"
DEFAULT_OUT = ROOT / "results" / "nfl" / "test_evaluation.json"
TARGETS = {"log_loss_max": 0.660, "brier_band": [0.200, 0.235], "ece_max": 0.05}
PLAYOFF_ECE_FLAG = 0.08


def load_frozen() -> tuple[ratings.Params, dict]:
    if not ARTIFACT.exists():
        raise SystemExit(f"ERROR: no frozen NFL artifact at {ARTIFACT}")
    a = json.loads(ARTIFACT.read_text())
    w = a["winner"]
    return ratings.Params(k_regular=float(w["k_regular"]), k_playoff=float(w["k_playoff"]),
                          carry=float(w["carry"]), home_bump=float(w["home_bump"]),
                          mov=bool(w["mov"])), a


def block(preds, rate, static, home_bump) -> dict:
    if not preds:
        return {"n": 0}
    ys = [p.outcome for p in preds]
    probs = [p.home_win_prob for p in preds]
    return {
        "n": len(preds),
        "model": tuner.score(probs, ys),
        "naive_baseline": tuner.score([0.5] * len(ys), ys),
        "home_rate_baseline": tuner.score(tuner.home_rate_probs(preds, rate), ys),
        "static_rating_baseline": tuner.score(tuner.static_probs(preds, static, home_bump), ys),
        "calibration_buckets": [
            {"lo": b.lo, "hi": b.hi, "n": b.n, "mean_predicted": b.mean_predicted, "mean_actual": b.mean_actual}
            for b in metrics.calibration_buckets(probs, ys)
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
    p = argparse.ArgumentParser(prog="scripts.nfl_evaluate")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    if not args.confirm:
        print("REFUSED: reads the held-out NFL test seasons (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if args.out.exists() and not args.force:
        print(f"REFUSED: results already exist at {args.out} (§10 #2).", file=sys.stderr)
        return 3

    params, artifact = load_frozen()
    test = tuner.TEST_SEASONS_DO_NOT_TOUCH
    cov = pipeline.load_manifest()["coverage"]
    for s in test:
        if not (cov[str(s)]["passes"] and cov[str(s)]["complete"]):
            raise SystemExit(f"ERROR: test season {s} incomplete or fails coverage")

    rows = backtest.rows_by_season(through=test[-1])
    seasons = backtest.model_seasons(rows)
    print(f"NFL TEST-SET EVALUATION — §10 #1 quarantine\nFrozen: {params}\nTEST seasons (read once): {test}")
    full = backtest.run(seasons, params, rows=rows, record_predictions_for=set(test))
    static = backtest.run([s for s in seasons if s <= tuner.LAST_VALIDATION], params, rows=rows).ratings
    rate = artifact["validation_baselines"]["home_rate"]["rate"]
    preds = full.predictions

    def b(sub):
        return block(sub, rate, static, params.home_bump)

    overall = b(preds)
    bd = {
        "per_season": {str(s): b([x for x in preds if x.season == s]) for s in test},
        "regular_season": b([x for x in preds if not x.is_playoff]),
        "playoffs": b([x for x in preds if x.is_playoff]),
        "segments": {seg: b([x for x in preds if backtest.segment(x) == seg]) for seg in ("early", "mid", "late")},
        "neutral_site": b([x for x in preds if x.neutral]),
    }
    seg = bd["segments"]
    ratio = seg["late"]["model"]["ece"] / seg["mid"]["model"]["ece"] if seg["mid"]["model"]["ece"] else None
    test_home_rate = round(tuner.home_rate(preds), 4)
    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": artifact["methodology_version"],
        "frozen_at": artifact["frozen_at"],
        "frozen_params": {"k_regular": params.k_regular, "k_playoff": params.k_playoff,
                          "carry": params.carry, "home_bump": params.home_bump, "mov": params.mov},
        "test_seasons": test,
        "home_rate_baseline_constant": rate,
        "test_home_rate_observed": test_home_rate,
        "segment_rule": "weeks 1-4 / 5-16 / 17-18 (16-game seasons: 1-4 / 5-15 / 16-17); playoffs separate",
        "targets": TARGETS,
        "overall": overall,
        "verdict": verdict(overall["model"], overall["home_rate_baseline"]["log_loss"]),
        "flags": {
            "playoff_ece_above_0_08": bd["playoffs"]["model"]["ece"] > PLAYOFF_ECE_FLAG,
            "late_segment_ece_over_2x_mid": bool(ratio and ratio > 2.0),
            "late_over_mid_ece_ratio": ratio,
        },
        "breakdowns": bd,
        "notes": ["Per §10 #1 this script reads the test seasons exactly once."],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    for name in ("model", "naive_baseline", "home_rate_baseline", "static_rating_baseline"):
        m = overall[name]
        print(f"  {name:<24} LL={m['log_loss']:.5f}  Brier={m['brier']:.5f}  ECE={m['ece']:.4f}  n={m['n']}")
    print("§6 verdict:", payload["verdict"])
    print("flags:", payload["flags"], "| observed test home rate:", test_home_rate)
    for k in ("regular_season", "playoffs", "neutral_site"):
        m = bd[k]["model"]
        print(f"  {k:<16} n={m['n']:<5} LL={m['log_loss']:.5f} ECE={m['ece']:.4f}")
    for k, blk in {**bd["per_season"], **bd["segments"]}.items():
        m = blk["model"]
        print(f"  {k:<16} n={m['n']:<5} LL={m['log_loss']:.5f} ECE={m['ece']:.4f}")
    print(f"results written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
