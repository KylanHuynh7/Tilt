"""Validation-period hyperparameter tuner per METHODOLOGY.md §7 step 3.

Sweeps a small grid over (K_regular, K_playoff, decay_carry, home_bump), runs
the full backtest for each grid point, scores the validation-period predictions
with the §6 metrics, and returns the ranked results. The caller picks the
winner by the §6 primary metric (log-loss) and freezes those parameters.

`home_bump` is the v2.0 (§12) addition. The v1 grid was 3D with home_bump
implicitly 0.0; the v2 grid is 4D and the v1 grid is reachable as the slice
where home_bump = 0.

Scope: this tuner does NOT tune the OT/SO outcome weights. They remain at the
§5 starting values. A future weight-tuning pass would expand the grid in a
follow-up amendment.

Season splits differ between v1 and v2:
  - v1:  train 1967-2020, validation 2021-22 + 2022-23, test 2023-24 + 2024-25
  - v2:  train 1967-2020, validation 2021-22 → 2024-25, test 2025-26
The active constants below are the v2 split per §12. v1 splits are preserved
as `*_V1` constants for reference and for reproducing v1's freeze.

§10 #1 quarantine: this module imports the test-set season ids only as
constants (for documentation) and never reads them. The grid-search code
path operates strictly over training + validation seasons.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence

from . import backtest, metrics
from .ratings import DECAY_CARRY, HOME_BUMP_DEFAULT, K_PLAYOFF, K_REGULAR


# --- Season windows per §4 (v1) and §12 (v2) -----------------------------------

TRAINING_SEASONS: list[int] = [
    s for s in range(19671968, 20202021 + 10001, 10001)
    if s != 20042005  # cancelled lockout
]

# v1 split — preserved for reproducing the v1 freeze artifact byte-for-byte.
VALIDATION_SEASONS_V1: list[int] = [20212022, 20222023]
TEST_SEASONS_V1_DO_NOT_TOUCH: list[int] = [20232024, 20242025]

# v2 split per §12. The former v1 test seasons join validation because v1's
# results on them are locked at v1 values; v2 is a separate model and may
# re-score them as validation data. The new held-out test is 2025-26.
VALIDATION_SEASONS: list[int] = [20212022, 20222023, 20232024, 20242025]
TEST_SEASONS_DO_NOT_TOUCH: list[int] = [20252026]


# --- Grid + result types ------------------------------------------------------

@dataclass(frozen=True)
class GridPoint:
    k_regular: float
    k_playoff: float
    decay_carry: float
    home_bump: float = HOME_BUMP_DEFAULT  # default 0.0 reproduces v1 cells

    def to_params(self) -> backtest.BacktestParams:
        return backtest.BacktestParams(
            k_regular=self.k_regular,
            k_playoff=self.k_playoff,
            decay_carry=self.decay_carry,
            home_bump=self.home_bump,
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


# --- Default grids ------------------------------------------------------------

# v2 default: 5 × 4 × 5 × 6 = 600 cells.
DEFAULT_GRID: list[GridPoint] = [
    GridPoint(k_regular=kr, k_playoff=kp, decay_carry=dc, home_bump=hb)
    for kr in (4.0, 6.0, 8.0, 10.0, 12.0)
    for kp in (6.0, 10.0, 14.0, 18.0)
    for dc in (0.65, 0.70, 0.75, 0.80, 0.85)
    for hb in (0.0, 20.0, 40.0, 60.0, 80.0, 100.0)
]

# v1 grid (100 cells, home_bump implicitly 0). Preserved so the v1 freeze can
# be reproduced exactly from this codebase if needed.
V1_GRID: list[GridPoint] = [
    GridPoint(k_regular=kr, k_playoff=kp, decay_carry=dc, home_bump=0.0)
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
    # The static-rating baseline gets the same home_bump the model uses, so the
    # comparison isolates "ratings updating vs ratings frozen" rather than
    # mixing in "with vs without home ice."
    static_probs = metrics.static_rating_probs(
        result.predictions, frozen_ratings, home_bump=grid_point.home_bump
    )

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
                f"c={gp.decay_carry:.2f} hb={gp.home_bump:>5.1f}  "
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
