"""Phase C test-set evaluation script — METHODOLOGY.md §10 #1 quarantined.

This is the ONLY code path in the project that reads outcomes from the held-out
test seasons (2023-24 and 2024-25). Per §10 #1 it can be run **exactly once**
during model development. Re-running after the first invocation requires
explicit re-evaluation justification and almost certainly invalidates the
evaluation per §10 #2.

Usage:
    uv run python -m scripts.evaluate --confirm                # default run
    uv run python -m scripts.evaluate --confirm --force        # overwrite existing
    uv run python -m scripts.evaluate --confirm --out path.json

Guardrails:
  - Refuses to run without --confirm (forces the operator to type the flag).
  - Refuses to overwrite existing results file without --force.
  - Loads parameters strictly from backend/artifacts/frozen_params.json; will
    not run if that artifact is missing.
  - Prints a banner before doing any test-season work, naming the season ids
    being touched and the file that will be written. The operator can ^C
    before the first test-season prediction lands.

Outputs (results/test_evaluation.json):
  - Per §6: log-loss, Brier, ECE for the model AND both baselines (naive 50%
    and static-rating from end-of-validation), plus calibration buckets for
    the model and a per-season breakdown.
  - All numbers are reported. No selective omission per §10 #5.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app import backtest, metrics, tuner
from app.ratings import K_PLAYOFF, K_REGULAR

ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "frozen_params.json"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
DEFAULT_OUT = RESULTS_DIR / "test_evaluation.json"
V1_RESULTS_SNAPSHOT = RESULTS_DIR / "test_evaluation_v1.json"


def _load_frozen_params() -> tuple[backtest.BacktestParams, dict]:
    if not ARTIFACT_PATH.exists():
        raise SystemExit(
            f"ERROR: no frozen-params artifact at {ARTIFACT_PATH}.\n"
            f"Run `uv run python -m scripts.freeze_params` first."
        )
    artifact = json.loads(ARTIFACT_PATH.read_text())
    w = artifact["winner"]
    # home_bump defaults to 0.0 for v1 artifacts that predate v2.0 (§12).
    params = backtest.BacktestParams(
        k_regular=float(w["k_regular"]),
        k_playoff=float(w["k_playoff"]),
        decay_carry=float(w["decay_carry"]),
        home_bump=float(w.get("home_bump", 0.0)),
    )
    return params, artifact


def _snapshot_v1_results_if_needed() -> bool:
    """If the active results file at DEFAULT_OUT is a v1 evaluation and no v1
    snapshot exists yet, copy it to test_evaluation_v1.json so the v1 record
    is preserved when v2 evaluation overwrites the active file.
    """
    if V1_RESULTS_SNAPSHOT.exists():
        return False
    if not DEFAULT_OUT.exists():
        return False
    payload = json.loads(DEFAULT_OUT.read_text())
    version = str(payload.get("methodology_version", ""))
    if not version.startswith("1"):
        return False
    V1_RESULTS_SNAPSHOT.write_text(DEFAULT_OUT.read_text())
    return True


def _score_predictions(predictions, frozen_ratings):
    probs = [p.home_win_prob for p in predictions]
    actuals = metrics.actuals_from_predictions(predictions)

    naive_probs = metrics.naive_baseline_probs(len(probs))
    static_probs = metrics.static_rating_probs(predictions, frozen_ratings)

    return {
        "model": {
            "n": len(probs),
            "brier": metrics.brier_score(probs, actuals),
            "log_loss": metrics.log_loss(probs, actuals),
            "ece": metrics.expected_calibration_error(probs, actuals),
        },
        "naive_baseline": {
            "n": len(probs),
            "brier": metrics.brier_score(naive_probs, actuals),
            "log_loss": metrics.log_loss(naive_probs, actuals),
            "ece": metrics.expected_calibration_error(naive_probs, actuals),
        },
        "static_rating_baseline": {
            "n": len(probs),
            "brier": metrics.brier_score(static_probs, actuals),
            "log_loss": metrics.log_loss(static_probs, actuals),
            "ece": metrics.expected_calibration_error(static_probs, actuals),
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.evaluate", description=__doc__.split("\n")[0])
    p.add_argument("--confirm", action="store_true",
                   help="REQUIRED — explicit acknowledgement of §10 #1")
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing results file (re-evaluation)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"results path (default: {DEFAULT_OUT})")
    args = p.parse_args(argv)

    if not args.confirm:
        print("REFUSED: this script reads the held-out test seasons (§10 #1).", file=sys.stderr)
        print("Re-run with --confirm to acknowledge.", file=sys.stderr)
        return 2

    if args.out.exists() and not args.force:
        print(f"REFUSED: results file already exists at {args.out}", file=sys.stderr)
        print("Re-run with --force only if you have a documented justification "
              "for re-evaluation (§10 #2).", file=sys.stderr)
        return 3

    # If the active results are a v1 evaluation, snapshot them before this
    # v2+ run overwrites the active file. v1 results are immutable per §10 #2.
    if _snapshot_v1_results_if_needed():
        print(f"snapshotted v1 results → {V1_RESULTS_SNAPSHOT}")

    params, artifact = _load_frozen_params()

    test_seasons = list(tuner.TEST_SEASONS_DO_NOT_TOUCH)
    warmup_seasons = list(tuner.TRAINING_SEASONS) + list(tuner.VALIDATION_SEASONS)

    print("=" * 72)
    print("TEST-SET EVALUATION — §10 #1 quarantine")
    print("=" * 72)
    print(f"Frozen artifact:    {ARTIFACT_PATH}")
    print(f"Frozen params:      K_regular={params.k_regular}, "
          f"K_playoff={params.k_playoff}, decay_carry={params.decay_carry}")
    print(f"Warm-up seasons:    {len(warmup_seasons)} "
          f"({warmup_seasons[0]} → {warmup_seasons[-1]})")
    print(f"TEST seasons (read once): {test_seasons}")
    print(f"Output:             {args.out}")
    print("=" * 72)
    print()

    # Replay warm-up + test in one walk-forward pass so the chronology is
    # natural and no test-season information leaks backwards.
    full_run = backtest.run(
        warmup_seasons + test_seasons,
        params=params,
        record_predictions_for=set(test_seasons),
    )

    # Static-rating baseline: ratings frozen at end of warm-up (end of last
    # validation season, i.e. after 2022-23). Run training+validation only
    # to capture that snapshot.
    warmup_only = backtest.run(
        warmup_seasons,
        params=params,
        record_predictions_for=set(),
    )
    frozen_state = dict(warmup_only.ratings)

    scores = _score_predictions(full_run.predictions, frozen_state)

    # Per-season breakdown so any single-season miscalibration is visible.
    per_season: dict[str, dict] = {}
    for sid in test_seasons:
        sid_preds = [p for p in full_run.predictions if p.season_id == sid]
        per_season[str(sid)] = _score_predictions(sid_preds, frozen_state)

    # Calibration buckets for the model — published per §9 stopping criterion #6.
    probs = [p.home_win_prob for p in full_run.predictions]
    actuals = metrics.actuals_from_predictions(full_run.predictions)
    buckets = [
        asdict(b) for b in metrics.calibration_buckets(probs, actuals, n_buckets=10)
    ]

    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": artifact.get("methodology_version"),
        "frozen_artifact_path": str(ARTIFACT_PATH),
        "frozen_at": artifact.get("frozen_at"),
        "frozen_params": {
            "k_regular": params.k_regular,
            "k_playoff": params.k_playoff,
            "decay_carry": params.decay_carry,
        },
        "warmup_seasons": warmup_seasons,
        "test_seasons": test_seasons,
        "n_test_predictions": len(probs),
        "metrics": scores,
        "per_season": per_season,
        "calibration_buckets": buckets,
        "section_6_targets": {
            "log_loss_max": 0.685,
            "brier_band": [0.235, 0.245],
            "ece_max": 0.04,
        },
        "notes": [
            "Per §10 #5, all metrics are reported regardless of which is most flattering.",
            "Per §10 #1, this script reads the test seasons exactly once.",
            "Re-running with --force after this point invalidates the evaluation unless a documented re-evaluation justification exists.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, args.out)

    print("RESULTS (test set, model vs baselines):")
    for name in ("model", "naive_baseline", "static_rating_baseline"):
        m = scores[name]
        print(f"  {name:24s}  LL={m['log_loss']:.5f}  Brier={m['brier']:.5f}  ECE={m['ece']:.4f}  n={m['n']}")

    print()
    print("§6 PASS/FAIL:")
    mm = scores["model"]
    targets = payload["section_6_targets"]
    print(f"  log-loss < 0.685:     {'PASS' if mm['log_loss'] < targets['log_loss_max'] else 'FAIL'}  ({mm['log_loss']:.5f})")
    print(f"  Brier in [0.235,0.245]:  {'PASS' if targets['brier_band'][0] <= mm['brier'] <= targets['brier_band'][1] else 'FAIL'}  ({mm['brier']:.5f})")
    print(f"  ECE < 0.04:           {'PASS' if mm['ece'] < targets['ece_max'] else 'FAIL'}  ({mm['ece']:.4f})")

    print(f"\nresults written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
