"""Frozen-parameter historical engine — Phase D backbone.

Replaces the milestone-1 slice engine. Responsibilities:

  - Load the frozen parameters written by `scripts/freeze_params.py`. These
    parameters are methodologically immutable post-test-eval per §10 #2.
  - Replay every Parquet season the pipeline has ingested, in chronological
    order, using the frozen params. Apply between-season decay and the
    OAK/CGS/CLE → MNS merger per §4 v1.2. Record every snapshot.
  - Group snapshots by season → franchise → ordered points, so the API can
    serve `/ratings/history/{season}` for any season without recomputing.
  - For the current (live) season, expose a refresh hook so newly-ingested
    games land in the trajectory without restarting the app. The current
    season's replay always re-runs from the end-of-prior-season state, so
    new games can only push the trajectory forward.
  - Expose the end-of-everything rating state for `/games/today`, with the
    `frozen_params: true` flag the methodology requires (§5 v1.1).

§10 quarantine: this module reads test-season Parquets the same way it reads
training and validation Parquets — that's a data-loading operation, not a
metric computation. No §6 numbers are evaluated here; those live in
`results/test_evaluation.json` produced by `scripts/evaluate.py`.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import backtest, pipeline, seasons
from .franchises import current_code

ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "frozen_params.json"


@dataclass(frozen=True)
class FrozenParams:
    k_regular: float
    k_playoff: float
    decay_carry: float
    home_bump: float  # v2.0 §12; defaults to 0.0 when loading a v1 artifact
    frozen_at: str | None
    methodology_version: str | None

    def to_backtest_params(self) -> backtest.BacktestParams:
        return backtest.BacktestParams(
            k_regular=self.k_regular,
            k_playoff=self.k_playoff,
            decay_carry=self.decay_carry,
            home_bump=self.home_bump,
        )


def load_frozen_params(path: Path = ARTIFACT_PATH) -> FrozenParams:
    if not path.exists():
        raise FileNotFoundError(
            f"no frozen-params artifact at {path}; "
            f"run `uv run python -m scripts.freeze_params` first"
        )
    payload = json.loads(path.read_text())
    w = payload["winner"]
    # Backwards-compat: v1 artifacts have no home_bump field — treat as 0.0
    # so the v1 model loads and runs identically post-v2.0 code changes.
    return FrozenParams(
        k_regular=float(w["k_regular"]),
        k_playoff=float(w["k_playoff"]),
        decay_carry=float(w["decay_carry"]),
        home_bump=float(w.get("home_bump", 0.0)),
        frozen_at=payload.get("frozen_at"),
        methodology_version=payload.get("methodology_version"),
    )


# ---- Trajectory cache ---------------------------------------------------------

@dataclass(frozen=True)
class TrajectoryPoint:
    game_id: int
    date: str  # ISO date
    rating: float


@dataclass
class HistoricalCache:
    params: FrozenParams
    # season_id -> franchise_id -> list of TrajectoryPoint
    trajectories: dict[int, dict[str, list[TrajectoryPoint]]] = field(default_factory=dict)
    # End-of-everything rating state — used by /games/today.
    current_ratings: dict[str, float] = field(default_factory=dict)
    seasons_replayed: list[int] = field(default_factory=list)
    last_built_at: datetime | None = None


def _ingested_season_ids() -> list[int]:
    """Every season with a Parquet file on disk."""
    if not pipeline.RAW_DIR.exists():
        return []
    ids = sorted(int(p.stem) for p in pipeline.RAW_DIR.glob("*.parquet"))
    return ids


def _build_cache(params: FrozenParams) -> HistoricalCache:
    """Replay every ingested season with the frozen params, recording snapshots.

    The single backtest run handles cross-season decay and the 1978 merger.
    We then bucket the resulting snapshot list by (season, franchise).
    """
    season_ids = _ingested_season_ids()
    result = backtest.run(
        season_ids,
        params=params.to_backtest_params(),
        record_predictions_for=set(),  # no need for predictions here
        record_snapshots=True,
    )
    trajectories: dict[int, dict[str, list[TrajectoryPoint]]] = {}
    for snap in result.snapshots:
        sid = snap.season_id
        season_bucket = trajectories.setdefault(sid, {})
        franchise_bucket = season_bucket.setdefault(snap.franchise_id, [])
        franchise_bucket.append(TrajectoryPoint(
            game_id=snap.game_id,
            date=snap.game_date.isoformat(),
            rating=snap.rating,
        ))
    return HistoricalCache(
        params=params,
        trajectories=trajectories,
        current_ratings=dict(result.ratings),
        seasons_replayed=result.seasons_processed,
        last_built_at=datetime.now(timezone.utc),
    )


# ---- Module-level singleton with thread-safe refresh --------------------------

_cache: HistoricalCache | None = None
_cache_lock = threading.Lock()


def initialize(path: Path = ARTIFACT_PATH) -> HistoricalCache:
    """Build the cache from scratch. Idempotent."""
    global _cache
    with _cache_lock:
        params = load_frozen_params(path)
        _cache = _build_cache(params)
        return _cache


def get_cache() -> HistoricalCache:
    if _cache is None:
        return initialize()
    return _cache


def refresh() -> HistoricalCache:
    """Re-read parquet files from disk and rebuild the cache. Call after the
    daily pipeline has ingested new current-season games.
    """
    return initialize()


# ---- Lookup helpers used by the API ------------------------------------------

def season_trajectory(season_id: int) -> dict[str, list[TrajectoryPoint]]:
    """All franchises' rating points for one season. Empty franchises dropped.
    Includes a synthetic "season start" point at the league mean (1500) for
    every franchise that played that season — gives the chart a clean origin.
    """
    cache = get_cache()
    bucket = cache.trajectories.get(season_id, {})
    return bucket


def is_pre_1967(season_id: int) -> bool:
    return seasons.parse(season_id).is_pre_1967


def available_seasons() -> list[int]:
    """Sorted list of season ids the API can serve. Today this is the union
    of (ingested seasons) and (seasons that produced any snapshot)."""
    cache = get_cache()
    return sorted(set(cache.trajectories.keys()))


def current_ratings_by_franchise() -> dict[str, float]:
    return dict(get_cache().current_ratings)


def current_active_ratings_with_codes() -> list[tuple[str, str, float]]:
    """List of (team_code, franchise_id, rating) for the 32 active franchises,
    sorted by rating desc.
    """
    cache = get_cache()
    out: list[tuple[str, str, float]] = []
    for fid, rating in cache.current_ratings.items():
        code = current_code(fid)
        if code is None:
            continue  # defunct franchise, hidden from the active list
        out.append((code, fid, rating))
    out.sort(key=lambda r: -r[2])
    return out


def franchise_for_active_code(team_code: str) -> str | None:
    """Reverse lookup: which currently-active franchise uses this team code?"""
    for fid in current_ratings_by_franchise():
        if current_code(fid) == team_code:
            return fid
    return None
