"""Walk-forward rating engine over the Parquet-cached history.

Loads season Parquets in chronological order, applies the between-season decay
rule at every season boundary, joins each game row to its franchise lineage,
seeds expansion franchises at 1500 on first sight, and produces:
  - the rating state for every franchise after every game
  - a flat list of pre-game predictions (predicted home win prob + actual
    weighted outcome) suitable for downstream scoring in Phase C

Phase B scope: the engine runs end-to-end and is correct. Phase C drives it
with different parameter grids during validation. Phase C also adds the
held-out test-set evaluation, which is segregated into its own script so
this module remains evaluation-blind.

Game filter:
  - Only NHL games are processed. game_type 2 (regular) and 3 (playoff) are
    included. Preseason (1), all-star (4), and special events (19/20 — e.g.
    the 4 Nations Face-Off) are dropped because they don't reflect team
    strength under the same conditions as official games.
  - Games involving a team code not in the franchise lineage table are
    dropped (e.g. international or PCHA codes that the historical /v1/score
    payload mixes in). The dropped count is exposed for sanity checks.

Per METHODOLOGY.md §10 #1, this module is not allowed to look at evaluation
metrics on the held-out test seasons. Use it for training and validation only;
the test-set evaluation script imports it but is invoked exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as pq

from . import franchises, pipeline, ratings
from .ratings import (
    DECAY_CARRY,
    HOME_BUMP_DEFAULT,
    INITIAL_RATING,
    K_PLAYOFF,
    K_REGULAR,
    OUTCOME_WEIGHTS,
    Outcome,
    apply_decay,
    apply_game,
    classify_outcome,
    win_probability,
)

REGULAR = 2
PLAYOFF = 3


@dataclass(frozen=True)
class Prediction:
    """One pre-game prediction recorded during a backtest run."""

    game_id: int
    season_id: int
    game_date: date
    home_franchise: str
    away_franchise: str
    home_rating_before: float
    away_rating_before: float
    home_win_prob: float
    home_outcome: Outcome
    away_outcome: Outcome
    home_score: int
    away_score: int
    is_playoff: bool


@dataclass(frozen=True)
class Snapshot:
    """One rating value after a game's update — for trajectory charts."""

    game_id: int
    season_id: int
    game_date: date
    franchise_id: str
    rating: float


@dataclass
class BacktestParams:
    """The tunable knobs (frozen pre-test per §7).

    `home_bump` is the v2.0 addition (§12). Default 0.0 reproduces v1 behavior
    so any caller that doesn't know about home ice gets the locked v1 model.
    """

    k_regular: float = K_REGULAR
    k_playoff: float = K_PLAYOFF
    decay_carry: float = DECAY_CARRY
    home_bump: float = HOME_BUMP_DEFAULT
    outcome_weights: dict[Outcome, float] = field(
        default_factory=lambda: dict(OUTCOME_WEIGHTS)
    )


@dataclass
class BacktestResult:
    ratings: dict[str, float]
    predictions: list[Prediction]
    snapshots: list[Snapshot]
    games_processed: int
    games_dropped_unknown_team: int
    games_dropped_non_nhl_type: int
    seasons_processed: list[int]


# ---- Loading -------------------------------------------------------------------


def _load_season_rows(season_id: int) -> list[dict]:
    """Read one season's Parquet as a list of dicts in chronological order.

    Reading via Arrow then converting to Python dicts is cheap at this volume
    (~1.5k rows per modern season). Keeps the engine independent of pandas.
    """
    path = pipeline.RAW_DIR / f"{season_id}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"missing parquet for season {season_id}; run `pipeline ingest --season {season_id}`"
        )
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows.sort(key=lambda r: (r["game_date"], r["game_id"]))
    return rows


# ---- Apply one game ------------------------------------------------------------


def _weighted_outcome(out: Outcome, weights: dict[Outcome, float]) -> float:
    return weights[out]


def _apply_one_game(
    row: dict,
    state: dict[str, float],
    params: BacktestParams,
    record_predictions: bool,
    predictions_out: list[Prediction],
    snapshots_out: list[Snapshot] | None,
) -> bool:
    """Apply one game's update to `state` in place. Returns True if applied,
    False if the game was filtered out.
    """
    season_id = row["season_id"]
    home_code = row["home"]
    away_code = row["away"]
    home_fid = franchises.franchise_for(home_code, season_id)
    away_fid = franchises.franchise_for(away_code, season_id)
    if home_fid is None or away_fid is None:
        return False

    # Seed expansion franchises on first appearance, no decay applied (§4 v1.1).
    if home_fid not in state:
        state[home_fid] = INITIAL_RATING
    if away_fid not in state:
        state[away_fid] = INITIAL_RATING

    r_home = state[home_fid]
    r_away = state[away_fid]

    home_score = row["home_score"]
    away_score = row["away_score"]
    if home_score is None or away_score is None:
        return False  # unfinished game — nothing to update

    is_playoff = row["game_type"] == PLAYOFF
    period_type = row["period_type"]

    home_outcome = classify_outcome(
        home_score=home_score,
        away_score=away_score,
        period_type=period_type,
        season_id=season_id,
        perspective="home",
    )
    away_outcome = classify_outcome(
        home_score=home_score,
        away_score=away_score,
        period_type=period_type,
        season_id=season_id,
        perspective="away",
    )

    # Win probability includes the v2.0 home-ice bump (§12). r_home is the
    # first argument and gets the bump; symmetry of P_home + P_away = 1 is
    # preserved by computing P_away as (1 - P_home).
    p_home = win_probability(r_home, r_away, home_bump=params.home_bump)
    w_home = _weighted_outcome(home_outcome, params.outcome_weights)
    w_away = _weighted_outcome(away_outcome, params.outcome_weights)
    k = params.k_playoff if is_playoff else params.k_regular

    new_home = r_home + k * (w_home - p_home)
    new_away = r_away + k * (w_away - (1.0 - p_home))

    if record_predictions:
        predictions_out.append(Prediction(
            game_id=row["game_id"],
            season_id=season_id,
            game_date=row["game_date"],
            home_franchise=home_fid,
            away_franchise=away_fid,
            home_rating_before=r_home,
            away_rating_before=r_away,
            home_win_prob=p_home,
            home_outcome=home_outcome,
            away_outcome=away_outcome,
            home_score=home_score,
            away_score=away_score,
            is_playoff=is_playoff,
        ))

    state[home_fid] = new_home
    state[away_fid] = new_away

    if snapshots_out is not None:
        snapshots_out.append(Snapshot(row["game_id"], season_id, row["game_date"], home_fid, new_home))
        snapshots_out.append(Snapshot(row["game_id"], season_id, row["game_date"], away_fid, new_away))

    return True


# ---- Top-level orchestration ---------------------------------------------------


def run(
    season_ids: Iterable[int],
    *,
    params: BacktestParams | None = None,
    initial_state: dict[str, float] | None = None,
    record_predictions_for: set[int] | None = None,
    record_snapshots: bool = False,
) -> BacktestResult:
    """Replay games season-by-season.

    Args:
      season_ids: chronological list of seasons to process.
      params: tunable parameters (defaults to the §5 starting values).
      initial_state: optional warm-start ratings (franchise_id -> rating).
        Used to chain a training warm-up into a validation phase without
        re-replaying training.
      record_predictions_for: only record predictions for these seasons. None
        means record for all. The §7 warm-up phase passes the empty set so no
        predictions are kept during the 1967→2020 training replay.
      record_snapshots: when True, record one Snapshot per (team, game) for
        the trajectory chart. Off by default to keep memory bounded for
        large training runs.
    """
    params = params or BacktestParams()
    state: dict[str, float] = dict(initial_state or {})
    predictions: list[Prediction] = []
    snapshots: list[Snapshot] | None = [] if record_snapshots else None
    processed = 0
    dropped_unknown = 0
    dropped_non_nhl = 0
    seasons_processed: list[int] = []

    sorted_seasons = sorted(season_ids)
    for i, season_id in enumerate(sorted_seasons):
        if i > 0:
            # Mergers fire first at the boundary (§4 v1.2 — simple average rule),
            # then the standard between-season decay applies to all surviving
            # franchises (§4, §7). The two operations commute mathematically
            # for linear decay; merging first reads more naturally.
            for merger in franchises.mergers_at_boundary(season_id):
                if (
                    merger.absorbed_id in state
                    and merger.surviving_id in state
                ):
                    averaged = 0.5 * (state[merger.absorbed_id] + state[merger.surviving_id])
                    state[merger.surviving_id] = averaged
                    del state[merger.absorbed_id]
                elif merger.absorbed_id in state and merger.surviving_id not in state:
                    # Surviving franchise has never played yet — hand them the
                    # absorbed rating outright (degenerate edge case, doesn't
                    # apply to the 1978 merger but kept defensive).
                    state[merger.surviving_id] = state[merger.absorbed_id]
                    del state[merger.absorbed_id]
                # If only the surviving franchise has a rating, the merger is a
                # no-op. If neither does, also a no-op.

            for fid in state:
                state[fid] = apply_decay(state[fid], carry=params.decay_carry)

        rows = _load_season_rows(season_id)
        record = (
            record_predictions_for is None
            or season_id in record_predictions_for
        )
        for row in rows:
            if row["game_type"] not in (REGULAR, PLAYOFF):
                dropped_non_nhl += 1
                continue
            applied = _apply_one_game(row, state, params, record, predictions, snapshots)
            if applied:
                processed += 1
            else:
                dropped_unknown += 1
        seasons_processed.append(season_id)

    return BacktestResult(
        ratings=state,
        predictions=predictions,
        snapshots=snapshots or [],
        games_processed=processed,
        games_dropped_unknown_team=dropped_unknown,
        games_dropped_non_nhl_type=dropped_non_nhl,
        seasons_processed=seasons_processed,
    )
