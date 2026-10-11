"""Freeze the NHL skater-projection model (methodology/NHL_PLAYERS.md §4).

Tunes each event (points, goals) on validation 2010-11 → 2022-23 with the
540-cell grid. Never reads the test seasons. Refuses to overwrite the artifact.

    uv run python -m scripts.players_freeze
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from app import projections as pj

OUT = Path(__file__).resolve().parent.parent / "artifacts" / "nhl_players_v1.json"
_ROWS = _PRIORS = None


def _init():
    global _ROWS, _PRIORS
    _ROWS = pj.load_sorted(pj.WARMUP + pj.VALIDATION)
    _PRIORS = pj.priors_for(_ROWS)


def _cell(args):
    event, params = args
    preds = pj.replay(_ROWS, event, params, _PRIORS, set(pj.VALIDATION))
    s = pj.score([p.p for p in preds], [p.y for p in preds])
    return {"event": event, **params, **{k: s[k] for k in ("n", "log_loss", "brier", "ece", "top_decile_gap")}}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if OUT.exists() and "--force" not in argv:
        print(f"REFUSED: {OUT} exists; the projection model is frozen.", file=sys.stderr)
        return 3
    assert not set(pj.TEST_DO_NOT_TOUCH) & set(pj.WARMUP + pj.VALIDATION)
    t0 = time.time()
    cells = [(e, c) for e in pj.EVENTS for c in pj.GRID]
    rows = []
    with ProcessPoolExecutor(max_workers=int(os.environ.get("TILT_WORKERS", 0)) or os.cpu_count(), initializer=_init) as ex:
        for i, r in enumerate(ex.map(_cell, cells, chunksize=4)):
            rows.append(r)
            if (i + 1) % 60 == 0:
                print(f"  {i + 1}/{len(cells)} cells · {time.time() - t0:.0f}s", flush=True)
    _init()
    out = {"methodology_version": "nhl-players-0.3", "frozen_at": datetime.now(timezone.utc).isoformat(),
           "warmup": pj.WARMUP, "validation": pj.VALIDATION, "test_do_not_touch": pj.TEST_DO_NOT_TOUCH,
           "winners": {}, "validation_baselines": {}, "expectations": {}}
    for e in pj.EVENTS:
        mine = [r for r in rows if r["event"] == e]
        w = min(mine, key=lambda r: (r["log_loss"], r["ece"], r["brier"]))
        out["winners"][e] = w
        a, b = pj.baselines(_ROWS, e, _PRIORS, set(pj.VALIDATION))
        y = [p.y for p in pj.replay(_ROWS, e, {k: w[k] for k in ("H", "m", "H_toi", "gamma", "home")},
                                     _PRIORS, set(pj.VALIDATION))]
        out["validation_baselines"][e] = {"A_position_rate": pj.score(a, y), "B_last_82": pj.score(b, y)}
        out["expectations"][e] = {"H_in_40_160": 40 <= w["H"] <= 160, "gamma_positive": w["gamma"] > 0}
        print(f"{e}: winner H={w['H']} m={w['m']} H_toi={w['H_toi']} γ={w['gamma']} home={w['home']} "
              f"LL {w['log_loss']:.5f} ECE {w['ece']:.4f} | A {out['validation_baselines'][e]['A_position_rate']['log_loss']:.5f}"
              f" B {out['validation_baselines'][e]['B_last_82']['log_loss']:.5f}")
    out["grid"] = rows
    out["wall_seconds"] = round(time.time() - t0, 1)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
