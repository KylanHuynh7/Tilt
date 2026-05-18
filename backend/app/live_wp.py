"""Empirical state-aware win-probability lookup — v2.2 §15.

Builds and queries a `P(home wins | period, mins_remaining, score_diff)` table
from the goal-event parquets produced by `pbp_pipeline`. The model is
intentionally non-parametric: no regression, no neural net, just bin-and-count.

Trained on the 2010-11 → 2024-25 seasons (the §15 training window — 2025-26 is
held out for v2 evaluation). Stored as a JSON artifact at
`backend/artifacts/live_wp_v2.json` so the runtime can load it once and look
up bins in O(1).

Pre-registered expectations from §15:
  - The (period=1, mins_remaining=19, score_diff=0) bin (game start) should
    be close to 0.5.
  - WP monotone in score_diff at fixed (period, mins_remaining).
  - WP at score_diff +5 ≥ 0.95 in any period.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pyarrow.compute as pc
import pyarrow.parquet as pq

from . import pbp_pipeline, pipeline as score_pipeline

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
DEFAULT_ARTIFACT = ARTIFACTS_DIR / "live_wp_v2.json"

# Bin bounds
SCORE_DIFF_CLAMP = 5  # bin labels run -5 .. +5
PERIODS = {1, 2, 3, 4}  # 4 = OT (any OT period is bucketed as 4)
SMOOTHING_ALPHA = 50  # Bayesian shrink toward 0.5 with strength 100 total
SMOOTHING_THRESHOLD = 100  # bins below this n use smoothed estimate
REGULATION_PERIOD_SECONDS = 20 * 60
OT_REG_PERIOD_SECONDS = 5 * 60
OT_PLAYOFF_PERIOD_SECONDS = 20 * 60


@dataclass(frozen=True)
class BinKey:
    period: int
    mins_remaining: int
    score_diff: int


@dataclass
class BinStats:
    n: int = 0
    home_wins: int = 0

    def add(self, home_won: bool) -> None:
        self.n += 1
        if home_won:
            self.home_wins += 1

    def empirical(self) -> float:
        return self.home_wins / self.n if self.n else 0.5

    def smoothed(self) -> float:
        # Bayesian shrinkage toward 0.5 with effective sample size 2*ALPHA.
        return (self.home_wins + SMOOTHING_ALPHA) / (self.n + 2 * SMOOTHING_ALPHA)


def _clamp_score_diff(d: int) -> int:
    if d >= SCORE_DIFF_CLAMP:
        return SCORE_DIFF_CLAMP
    if d <= -SCORE_DIFF_CLAMP:
        return -SCORE_DIFF_CLAMP
    return d


def _period_bucket(period: int, period_type: str) -> int:
    """Bucket period: 1, 2, 3 stay as themselves; OT/SO collapse to 4."""
    if period_type in ("OT", "SO"):
        return 4
    if period in (1, 2, 3):
        return period
    return 4  # anything else (e.g., multi-OT period numbers) → 4


# ---- Game outcomes from the score parquet ---------------------------------

def _home_won_by_game_id(season_ids: Iterable[int]) -> dict[int, bool]:
    """For every completed regular-season / playoff game across the seasons,
    return a {game_id: home_won_final} dict.

    A "home win" is any final score where home_score > away_score, regardless
    of period_type (REG / OT / SO). Ties (pre-2005-06) are excluded — the
    training window starts in 2010-11 so no ties appear.
    """
    out: dict[int, bool] = {}
    for sid in season_ids:
        path = score_pipeline.RAW_DIR / f"{sid}.parquet"
        if not path.exists():
            continue
        t = pq.read_table(path, columns=[
            "game_id", "game_type", "state", "home_score", "away_score",
        ])
        keep = pc.and_(
            pc.or_(pc.equal(t.column("game_type"), 2), pc.equal(t.column("game_type"), 3)),
            pc.or_(pc.equal(t.column("state"), "OFF"), pc.equal(t.column("state"), "FINAL")),
        )
        for r in t.filter(keep).to_pylist():
            if r["home_score"] is None or r["away_score"] is None:
                continue
            out[r["game_id"]] = r["home_score"] > r["away_score"]
    return out


# ---- Sample expansion -----------------------------------------------------

def _expand_game_to_samples(
    game_id: int,
    goal_rows: list[dict],
    home_won_final: bool,
) -> Iterable[tuple[BinKey, bool]]:
    """Walk a game minute by minute. For each minute the game passed through,
    yield (BinKey, home_won_final).

    Algorithm: process goals in chronological order, advancing a current
    (period_bucket, seconds_remaining_in_period, score_diff) cursor. At each
    minute boundary the cursor crosses, emit a sample at that bin.
    """
    # Sort by (period, time_in_period_s) — earliest first
    goals = sorted(goal_rows, key=lambda g: (g["period"], g["time_in_period_s"]))

    # Every NHL game plays all three regulation periods (a forfeit / cancelled
    # game never reaches the PBP feed). Bucket 4 (OT) is only added if the
    # game actually went to OT/SO.
    periods_reached: set[int] = {1, 2, 3}
    for g in goals:
        if g["period"] > 3 or g["period_type"] in ("OT", "SO"):
            periods_reached.add(4)
            break

    samples: list[tuple[BinKey, bool]] = []
    for period_bucket in sorted(periods_reached):
        # Total seconds in this period:
        if period_bucket == 4:
            # OT bucket. We use 5 minutes (regular-season OT) as the bound;
            # playoff OT periods are 20 mins but binning beyond 5 mins gets
            # very sparse and isn't actionable for the dashboard surface.
            period_seconds = OT_REG_PERIOD_SECONDS
        else:
            period_seconds = REGULATION_PERIOD_SECONDS

        # At each minute mark (mins_remaining from period_seconds/60 - 1 down to 0):
        for mins_remaining in range(period_seconds // 60 - 1, -1, -1):
            # Compute score_diff at this exact instant by including all goals
            # that occurred at or before this time in the period.
            time_remaining_s = mins_remaining * 60 + 59  # we sample at the START of this minute, ~the moment just after the prior tick
            score_diff_here = 0
            for g in goals:
                g_period = _period_bucket(g["period"], g["period_type"])
                if g_period > period_bucket:
                    continue
                if g_period < period_bucket:
                    score_diff_here = g["home_score_after"] - g["away_score_after"]
                    continue
                # Same period: include goal if its time_remaining > our sample time_remaining
                # (i.e., goal happened earlier in this period than our snapshot).
                if g["time_remaining_in_period_s"] > time_remaining_s:
                    score_diff_here = g["home_score_after"] - g["away_score_after"]
            samples.append((
                BinKey(period=period_bucket,
                       mins_remaining=mins_remaining,
                       score_diff=_clamp_score_diff(score_diff_here)),
                home_won_final,
            ))
    return samples


# ---- Build the table ------------------------------------------------------

@dataclass
class WPModel:
    bins: dict[BinKey, BinStats] = field(default_factory=dict)
    n_games: int = 0
    n_samples: int = 0
    training_seasons: list[int] = field(default_factory=list)

    def add_sample(self, key: BinKey, home_won: bool) -> None:
        stats = self.bins.setdefault(key, BinStats())
        stats.add(home_won)
        self.n_samples += 1


def build(training_seasons: Iterable[int] | None = None) -> WPModel:
    """Build the WP model from all goal-event parquets for the given seasons.

    Defaults to the full v2.2 training window from §15.
    """
    seasons = list(training_seasons) if training_seasons is not None else list(pbp_pipeline.TRAINING_SEASONS)
    home_won = _home_won_by_game_id(seasons)
    model = WPModel(training_seasons=seasons)

    for sid in seasons:
        path = pbp_pipeline.PBP_DIR / f"{sid}.parquet"
        if not path.exists():
            continue
        t = pq.read_table(path)
        # Group goals by game_id for cheap per-game iteration.
        by_game: dict[int, list[dict]] = {}
        for row in t.to_pylist():
            by_game.setdefault(row["game_id"], []).append(row)
        for gid, goals in by_game.items():
            if gid not in home_won:
                continue  # data inconsistency; skip
            model.n_games += 1
            for key, won in _expand_game_to_samples(gid, goals, home_won[gid]):
                model.add_sample(key, won)
    return model


# ---- Query ----------------------------------------------------------------

@dataclass(frozen=True)
class WPLookupResult:
    home_win_prob: float
    n: int
    smoothed: bool
    bin: BinKey


def query(
    model: WPModel,
    *,
    period: int,
    time_remaining_s: int,
    score_diff: int,
) -> WPLookupResult:
    """Look up `P(home wins | state)` for the given state.

    `period` ∈ {1,2,3,4} (4 = OT). `time_remaining_s` is seconds remaining in
    the current period. `score_diff` is home - away score; clamped to ±5.
    """
    mins_remaining = max(0, time_remaining_s // 60)
    key = BinKey(
        period=period,
        mins_remaining=mins_remaining,
        score_diff=_clamp_score_diff(score_diff),
    )
    stats = model.bins.get(key)
    if stats is None or stats.n == 0:
        return WPLookupResult(home_win_prob=0.5, n=0, smoothed=True, bin=key)
    if stats.n < SMOOTHING_THRESHOLD:
        return WPLookupResult(
            home_win_prob=round(stats.smoothed(), 4),
            n=stats.n, smoothed=True, bin=key,
        )
    return WPLookupResult(
        home_win_prob=round(stats.empirical(), 4),
        n=stats.n, smoothed=False, bin=key,
    )


# ---- Artifact I/O ---------------------------------------------------------

def write_artifact(model: WPModel, path: Path = DEFAULT_ARTIFACT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bins_payload = []
    for key, stats in sorted(
        model.bins.items(),
        key=lambda kv: (kv[0].period, -kv[0].mins_remaining, kv[0].score_diff),
    ):
        smoothed = stats.n < SMOOTHING_THRESHOLD
        bins_payload.append({
            "period": key.period,
            "mins_remaining": key.mins_remaining,
            "score_diff": key.score_diff,
            "n": stats.n,
            "home_win_rate": round(
                stats.smoothed() if smoothed else stats.empirical(), 4
            ),
            "smoothed": smoothed,
        })
    payload = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": "2.2",
        "training_seasons": list(model.training_seasons),
        "n_games": model.n_games,
        "n_samples": model.n_samples,
        "n_bins": len(model.bins),
        "smoothing_alpha": SMOOTHING_ALPHA,
        "smoothing_threshold": SMOOTHING_THRESHOLD,
        "bins": bins_payload,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)


_cached_model: WPModel | None = None


def get_model(path: Path = DEFAULT_ARTIFACT) -> WPModel:
    """Lazily load and cache the WP model at module level.

    Use this from request paths that want the model without re-reading the
    artifact every call. Raises FileNotFoundError if the artifact is missing.
    """
    global _cached_model
    if _cached_model is None:
        _cached_model = load_artifact(path)
    return _cached_model


def clear_cache() -> None:
    """Reset the cached model (after a re-build, for example)."""
    global _cached_model
    _cached_model = None


def load_artifact(path: Path = DEFAULT_ARTIFACT) -> WPModel:
    payload = json.loads(path.read_text())
    model = WPModel(training_seasons=payload.get("training_seasons", []))
    for b in payload["bins"]:
        key = BinKey(period=b["period"],
                     mins_remaining=b["mins_remaining"],
                     score_diff=b["score_diff"])
        stats = BinStats(n=b["n"])
        # We stored the rate, not raw wins; reconstruct integer wins.
        # For smoothed bins we recompute from the empirical rate.
        # This loses the original `home_win_rate` to rounding (4 decimals);
        # acceptable for runtime use because the rate is what we publish.
        rate = b["home_win_rate"]
        if b.get("smoothed"):
            # Invert smoothed formula: (wins + α) / (n + 2α) = rate
            wins = round(rate * (stats.n + 2 * SMOOTHING_ALPHA) - SMOOTHING_ALPHA)
        else:
            wins = round(rate * stats.n)
        stats.home_wins = max(0, min(stats.n, wins))
        model.bins[key] = stats
        model.n_samples += stats.n
    model.n_games = payload.get("n_games", 0)
    return model
