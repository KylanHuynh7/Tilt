"""Validation-period hyperparameter tuner per METHODOLOGY.md §7 step 3.

Sweeps a small grid over (K_regular, K_playoff, decay_carry), runs the full
backtest for each grid point, scores the validation-period predictions with
the §6 metrics, and returns the ranked results. The caller picks the winner
by the §6 primary metric (log-loss) and freezes those parameters.

Scope: this tuner does NOT tune the OT/SO outcome weights. They remain at
the §5 starting values for v1. A future weight-tuning pass would expand the
grid in a follow-up amendment. This is a deliberate scope choice documented
in the freeze artifact, not an oversight.

§10 #1 quarantine: this module imports the test-set season ids only as
constants (for documentation) and never reads them. The grid-search code
path operates strictly over training + validation seasons.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence

from . import backtest, metrics
from .ratings import DECAY_CARRY, K_PLAYOFF, K_REGULAR


# --- Season windows per §4 ----------------------------------------------------

TRAINING_SEASONS: list[int] = [
    s for s in range(19671968, 20202021 + 10001, 10001)
    if s != 20042005  # cancelled lockout
]
VALIDATION_SEASONS: list[int] = [20212022, 20222023]
# Test seasons listed for documentation only — never used in this module.
TEST_SEASONS_DO_NOT_TOUCH: list[int] = [20232024, 20242025]


# --- Grid + result types ------------------------------------------------------

@dataclass(frozen=True)
class GridPoint:
    k_regular: float
    k_playoff: float
    decay_carry: float

    def to_params(self) -> backtest.BacktestParams:
        return backtest.BacktestParams(
            k_regular=self.k_regular,
            k_playoff=self.k_playoff,
            decay_carry=self.decay_carry,
        )


@dataclass(frozen=True)
class TuneRow:
    grid_point: GridPoint
    n_predictions: int
    brier: float
    log_loss: float
    ece: float
    static_baseline_brier: float
    static_baseline_log_loss: float
    static_baseline_ece: float


# --- Default v1 grid ----------------------------------------------------------

DEFAULT_GRID: list[GridPoint] = [
    GridPoint(k_regular=kr, k_playoff=kp, decay_carry=dc)
    for kr in (4.0, 6.0, 8.0, 10.0, 12.0)
    for kp in (6.0, 10.0, 14.0, 18.0)
    for dc in (0.65, 0.70, 0.75, 0.80, 0.85)
]


# --- Single evaluation --------------------------------------------------------

def evaluate_one(
    grid_point: GridPoint,
    *,
    training_seasons: Sequence[int] = TRAINING_SEASONS,
    validation_seasons: Sequence[int] = VALIDATION_SEASONS,
) -> TuneRow:
    """Run one full backtest at this grid point and score the validation
    predictions plus the static-rating baseline. Returns one TuneRow.
    """
    params = grid_point.to_params()

    # Warm-up: replay training and validation. Predictions are only recorded
    # for validation seasons (§7 step 2).
    val_set = set(validation_seasons)
    result = backtest.run(
        list(training_seasons) + list(validation_seasons),
        params=params,
        record_predictions_for=val_set,
    )

    # Separate run to capture the end-of-training rating snapshot for the
    # static baseline. The training-only state must come from the same params.
    training_only = backtest.run(
        list(training_seasons),
        params=params,
        record_predictions_for=set(),
    )
    frozen_ratings = dict(training_only.ratings)

    probs = [p.home_win_prob for p in result.predictions]
    actuals = metrics.actuals_from_predictions(result.predictions)
    static_probs = metrics.static_rating_probs(result.predictions, frozen_ratings)

    return TuneRow(
        grid_point=grid_point,
        n_predictions=len(probs),
        brier=metrics.brier_score(probs, actuals),
        log_loss=metrics.log_loss(probs, actuals),
        ece=metrics.expected_calibration_error(probs, actuals),
        static_baseline_brier=metrics.brier_score(static_probs, actuals),
        static_baseline_log_loss=metrics.log_loss(static_probs, actuals),
        static_baseline_ece=metrics.expected_calibration_error(static_probs, actuals),
    )


# --- Grid search --------------------------------------------------------------

@dataclass
class TuneReport:
    rows: list[TuneRow]
    best: TuneRow
    wall_seconds: float
    grid_size: int


def grid_search(
    grid: Sequence[GridPoint] = DEFAULT_GRID,
    *,
    training_seasons: Sequence[int] = TRAINING_SEASONS,
    validation_seasons: Sequence[int] = VALIDATION_SEASONS,
    verbose: bool = True,
) -> TuneReport:
    """Evaluate every grid point, return all rows + the winner.

    Selection rule: lowest log-loss per §6 (primary metric). Ties broken by
    lowest ECE, then lowest Brier — somewhat arbitrary but deterministic so
    the freeze artifact is reproducible.
    """
    t0 = time.time()
    rows: list[TuneRow] = []
    for i, gp in enumerate(grid):
        row = evaluate_one(
            gp,
            training_seasons=training_seasons,
            validation_seasons=validation_seasons,
        )
        rows.append(row)
        if verbose:
            print(
                f"  [{i+1:>3}/{len(grid)}] "
                f"K={gp.k_regular:>4.1f}/{gp.k_playoff:>4.1f} "
                f"c={gp.decay_carry:.2f}  "
                f"LL={row.log_loss:.5f}  B={row.brier:.5f}  ECE={row.ece:.4f}",
                flush=True,
            )

    best = min(rows, key=lambda r: (r.log_loss, r.ece, r.brier))
    return TuneReport(
        rows=rows,
        best=best,
        wall_seconds=time.time() - t0,
        grid_size=len(grid),
    )
