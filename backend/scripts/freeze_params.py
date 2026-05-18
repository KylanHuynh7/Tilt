"""Phase C freeze script — runs the validation-period grid search and writes
the frozen-parameters artifact at backend/artifacts/frozen_params.json.

Usage:
    uv run python -m scripts.freeze_params [--out PATH]

What this does and does not do:
  - Runs the §6 metrics on training + validation seasons only. No test-set
    season is read at any point. The freeze is determined entirely by
    validation performance, in line with §10 #1.
  - Selects the winning grid point by lowest log-loss (§6 primary metric),
    with ECE then Brier as deterministic tiebreakers.
  - Writes the complete grid (all rows) into the artifact so the freeze is
    reproducible and reviewable.
  - Records the methodology version, the frozen-at timestamp, and the
    training / validation season lists used.

This script is safe to re-run during model development; each run overwrites
the artifact atomically. Once development is complete and `evaluate.py` has
been run against the test set, re-running this script and changing the
params would invalidate the evaluation per §10 #2 — at that point treat
the artifact as immutable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app import tuner

METHODOLOGY_VERSION = "2.0"

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
DEFAULT_OUT = ARTIFACTS_DIR / "frozen_params.json"
V2_SNAPSHOT = ARTIFACTS_DIR / "frozen_params_v2.json"
V1_SNAPSHOT = ARTIFACTS_DIR / "frozen_params_v1.json"


def _row_to_dict(row: tuner.TuneRow) -> dict:
    d = asdict(row)
    # flatten grid_point for nicer JSON
    gp = d.pop("grid_point")
    d["k_regular"] = gp["k_regular"]
    d["k_playoff"] = gp["k_playoff"]
    d["decay_carry"] = gp["decay_carry"]
    d["home_bump"] = gp["home_bump"]
    return d


def _pick_constrained_winner(rows: list[tuner.TuneRow]) -> tuner.TuneRow:
    """Apply the §5 constraint K_playoff >= K_regular, then select by the
    same rule the unconstrained tuner uses (lowest log-loss, tiebreak ECE
    then Brier). This honors §5's pre-registered claim that playoff games
    carry more information than regular-season games.
    """
    constrained = [
        r for r in rows
        if r.grid_point.k_playoff >= r.grid_point.k_regular
    ]
    if not constrained:
        raise ValueError("no grid points satisfy K_playoff >= K_regular constraint")
    return min(constrained, key=lambda r: (r.log_loss, r.ece, r.brier))


def write_artifact(
    report: tuner.TuneReport,
    out_path: Path,
    *,
    constrain_playoff_k: bool = True,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if constrain_playoff_k:
        winner = _pick_constrained_winner(report.rows)
        constraint_note = (
            "K_playoff >= K_regular enforced per §5 (pre-registered claim "
            "that playoff games carry more information than regular-season "
            "games). The unconstrained winner is also reported below for "
            "transparency."
        )
    else:
        winner = report.best
        constraint_note = "No constraint applied; winner is the unconstrained log-loss minimum."

    payload = {
        "methodology_version": METHODOLOGY_VERSION,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "training_seasons": tuner.TRAINING_SEASONS,
        "validation_seasons": tuner.VALIDATION_SEASONS,
        "test_seasons_do_not_touch": tuner.TEST_SEASONS_DO_NOT_TOUCH,
        "grid_size": report.grid_size,
        "wall_seconds": round(report.wall_seconds, 2),
        "constraint": constraint_note,
        "winner": {
            "k_regular": winner.grid_point.k_regular,
            "k_playoff": winner.grid_point.k_playoff,
            "decay_carry": winner.grid_point.decay_carry,
            "home_bump": winner.grid_point.home_bump,
            "validation_metrics": {
                "n_predictions": winner.n_predictions,
                "brier": winner.brier,
                "log_loss": winner.log_loss,
                "ece": winner.ece,
            },
            "static_baseline_on_validation": {
                "brier": winner.static_baseline_brier,
                "log_loss": winner.static_baseline_log_loss,
                "ece": winner.static_baseline_ece,
            },
        },
        "unconstrained_winner_for_reference": {
            "k_regular": report.best.grid_point.k_regular,
            "k_playoff": report.best.grid_point.k_playoff,
            "decay_carry": report.best.grid_point.decay_carry,
            "home_bump": report.best.grid_point.home_bump,
            "log_loss": report.best.log_loss,
            "brier": report.best.brier,
            "ece": report.best.ece,
        },
        "grid": [_row_to_dict(r) for r in report.rows],
        "selection_rule": "lowest log_loss; ties broken by lower ECE then lower Brier",
        "notes": [
            "OT/SO outcome weights were not tuned in this freeze; they remain at the §5 starting values.",
            f"Test seasons ({tuner.TEST_SEASONS_DO_NOT_TOUCH}) were not touched during the freeze per §10 #1.",
            "home_bump is the v2.0 §12 home-ice tunable; 0.0 = v1-equivalent behavior.",
        ],
    }
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, out_path)


def _snapshot_v1_if_needed() -> bool:
    """Copy the existing v1 frozen_params.json to frozen_params_v1.json if the
    snapshot doesn't already exist. Returns True if a snapshot was made.

    The current frozen_params.json on disk before any v2 freeze runs IS the
    v1 artifact, so this preserves it as the immutable v1 record per §10 #2.
    """
    if V1_SNAPSHOT.exists():
        return False
    if not DEFAULT_OUT.exists():
        return False
    payload = json.loads(DEFAULT_OUT.read_text())
    version = str(payload.get("methodology_version", ""))
    if not version.startswith("1"):
        # Already a v2+ artifact; not a v1 to snapshot.
        return False
    V1_SNAPSHOT.write_text(DEFAULT_OUT.read_text())
    print(f"snapshotted v1 frozen artifact → {V1_SNAPSHOT}")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.freeze_params", description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"output path for the active artifact (default: {DEFAULT_OUT})")
    p.add_argument("--quiet", action="store_true",
                   help="suppress per-cell progress output")
    p.add_argument("--unconstrained", action="store_true",
                   help="skip the §5 K_playoff >= K_regular constraint")
    p.add_argument("--no-snapshot", action="store_true",
                   help="don't write frozen_params_v2.json alongside the active artifact")
    args = p.parse_args(argv)

    _snapshot_v1_if_needed()

    print(f"freezing parameters; grid size = {len(tuner.DEFAULT_GRID)} cells")
    print(f"training:   {len(tuner.TRAINING_SEASONS)} seasons "
          f"({tuner.TRAINING_SEASONS[0]} → {tuner.TRAINING_SEASONS[-1]})")
    print(f"validation: {len(tuner.VALIDATION_SEASONS)} seasons "
          f"({tuner.VALIDATION_SEASONS[0]} → {tuner.VALIDATION_SEASONS[-1]})")
    print(f"test (untouched): {tuner.TEST_SEASONS_DO_NOT_TOUCH}")
    constrain = not args.unconstrained
    print(f"§5 K_playoff>=K_regular constraint: {'ON' if constrain else 'OFF'}")
    print()
    report = tuner.grid_search(verbose=not args.quiet)
    print()
    print(f"done in {report.wall_seconds:.1f}s")
    print()

    print("top 5 unconstrained by log-loss:")
    for row in sorted(report.rows, key=lambda r: r.log_loss)[:5]:
        gp = row.grid_point
        flag = "  " if gp.k_playoff >= gp.k_regular else "⚠ "
        print(f"  {flag}K={gp.k_regular:>4.1f}/{gp.k_playoff:>4.1f}  c={gp.decay_carry:.2f}  "
              f"hb={gp.home_bump:>5.1f}  "
              f"LL={row.log_loss:.5f}  B={row.brier:.5f}  ECE={row.ece:.4f}")
    print()

    winner = _pick_constrained_winner(report.rows) if constrain else report.best
    label = "WINNER (constrained)" if constrain else "WINNER (unconstrained)"
    gp = winner.grid_point
    print(f"{label}: K_regular={gp.k_regular}, K_playoff={gp.k_playoff}, "
          f"decay_carry={gp.decay_carry}, home_bump={gp.home_bump}")
    print(f"   validation log-loss={winner.log_loss:.5f}  "
          f"Brier={winner.brier:.5f}  ECE={winner.ece:.4f}")
    print(f"   static-rating baseline on validation: "
          f"LL={winner.static_baseline_log_loss:.5f}  "
          f"B={winner.static_baseline_brier:.5f}  "
          f"ECE={winner.static_baseline_ece:.4f}")
    if constrain and winner is not report.best:
        gp0 = report.best.grid_point
        print()
        print(f"(unconstrained winner K={gp0.k_regular}/{gp0.k_playoff} "
              f"c={gp0.decay_carry} hb={gp0.home_bump} "
              f"LL={report.best.log_loss:.5f} — recorded in artifact for transparency)")

    write_artifact(report, args.out, constrain_playoff_k=constrain)
    print(f"\nactive artifact written: {args.out}")
    if not args.no_snapshot and args.out == DEFAULT_OUT:
        write_artifact(report, V2_SNAPSHOT, constrain_playoff_k=constrain)
        print(f"versioned snapshot written: {V2_SNAPSHOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
