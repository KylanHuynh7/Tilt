"""NHL v3 validation tuner (METHODOLOGY.md §17, §18, §20).

v3.0: the §17 6-D grid with BOOST_AMOUNT 0 added (§20 V3-4) → 12,000 cells
(BOOST_AMOUNT = 0 cells are computed once per (K, carry, home) and shared
across windows, since the window is inert there). v3.1: the §18 24-cell
sub-grid on top of the locked v3.0 parameters (§20 V3-7).

`round_scale` is the per-round increment of §18's ROUND_WEIGHTS: round r gets
round_scale × (r − 1), so the pre-registered starting weights [0, .1, .2, .3]
are round_scale = 0.10.

Cells run in parallel (one process per core); results are deterministic and
the selection rule is unchanged: lowest log-loss, then ECE, then Brier, with
the §5 constraint K_playoff ≥ K_regular.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass

from . import backtest, metrics, roster_moves, tuner

TRAINING_SEASONS: list[int] = list(tuner.TRAINING_SEASONS)               # 1967-68 → 2020-21
VALIDATION_SEASONS: list[int] = [20212022, 20222023, 20232024, 20242025, 20252026]
TEST_SEASONS_DO_NOT_TOUCH: list[int] = [20262027]
LAST_ALLOWED = 20252026

V30_GRID = [
    dict(k_regular=kr, k_playoff=kp, decay_carry=dc, home_bump=hb, boost_window=bw, boost_amount=ba)
    for kr in (4.0, 6.0, 8.0, 10.0, 12.0)
    for kp in (6.0, 10.0, 14.0, 18.0)
    for dc in (0.65, 0.70, 0.75, 0.80, 0.85)
    for hb in (0.0, 20.0, 40.0, 60.0, 80.0, 100.0)
    for bw in (5.0, 10.0, 15.0, 20.0)
    for ba in (0.0, 0.25, 0.50, 0.75, 1.00)
]
V31_SUBGRID = [dict(round_scale=rs, elim_bump=eb)
               for rs in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30) for eb in (0.0, 0.10, 0.20, 0.30)]


def check_quarantine(seasons) -> None:
    bad = [s for s in seasons if s > LAST_ALLOWED]
    if bad:
        raise RuntimeError(f"v3 test quarantine (§20 V3-5): refusing to replay {bad}")


_EVENTS: set[tuple[int, str]] | None = None


def _init(events) -> None:
    global _EVENTS
    _EVENTS = events


def evaluate_cell(cell: dict) -> dict:
    params = backtest.BacktestParams(**cell)
    seasons = TRAINING_SEASONS + VALIDATION_SEASONS
    check_quarantine(seasons)
    res = backtest.run(seasons, params=params, record_predictions_for=set(VALIDATION_SEASONS),
                       roster_events=_EVENTS)
    train = backtest.run(TRAINING_SEASONS, params=params, record_predictions_for=set(), roster_events=_EVENTS)
    probs = [p.home_win_prob for p in res.predictions]
    y = metrics.actuals_from_predictions(res.predictions)
    static = metrics.static_rating_probs(res.predictions, dict(train.ratings), home_bump=cell["home_bump"])
    return {**cell, "n_predictions": len(probs),
            "log_loss": metrics.log_loss(probs, y), "brier": metrics.brier_score(probs, y),
            "ece": metrics.expected_calibration_error(probs, y),
            "static_baseline_log_loss": metrics.log_loss(static, y)}


def _key(r: dict):
    return (r["log_loss"], r["ece"], r["brier"])


def pick(rows: list[dict]) -> tuple[dict, dict]:
    """(§5-constrained winner, unconstrained winner)."""
    ok = [r for r in rows if r["k_playoff"] >= r["k_regular"]]
    return min(ok, key=_key), min(rows, key=_key)


def run_grid(cells: list[dict], events, workers: int | None = None, log=print) -> list[dict]:
    workers = workers or os.cpu_count() or 4
    t0 = time.time()
    out: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(events,)) as ex:
        for i, r in enumerate(ex.map(evaluate_cell, cells, chunksize=4)):
            out.append(r)
            if (i + 1) % 250 == 0 or i + 1 == len(cells):
                best = min(out, key=_key)
                log(f"  {i + 1}/{len(cells)} cells · {time.time() - t0:.0f}s · best LL so far {best['log_loss']:.5f}")
    return out


def v30(events, workers=None, log=print) -> list[dict]:
    """The 12,000-cell v3.0 grid; BOOST_AMOUNT 0 cells computed once per window-free key."""
    unique, seen = [], set()
    for c in V30_GRID:
        key = (c["k_regular"], c["k_playoff"], c["decay_carry"], c["home_bump"],
               c["boost_window"] if c["boost_amount"] else None, c["boost_amount"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    rows = run_grid(unique, events, workers, log)
    by_key = {(r["k_regular"], r["k_playoff"], r["decay_carry"], r["home_bump"],
               r["boost_window"] if r["boost_amount"] else None, r["boost_amount"]): r for r in rows}
    return [{**by_key[(c["k_regular"], c["k_playoff"], c["decay_carry"], c["home_bump"],
                       c["boost_window"] if c["boost_amount"] else None, c["boost_amount"])], **c} for c in V30_GRID]


def v31(base: dict, events, workers=None, log=print) -> list[dict]:
    keep = ("k_regular", "k_playoff", "decay_carry", "home_bump", "boost_window", "boost_amount")
    return run_grid([{**{k: base[k] for k in keep}, **sub} for sub in V31_SUBGRID], events, workers, log)


def all_events() -> set[tuple[int, str]]:
    check_quarantine(TRAINING_SEASONS + VALIDATION_SEASONS)
    return roster_moves.all_events(TRAINING_SEASONS + VALIDATION_SEASONS)
