"""Freeze MLB v2 (methodology/MLB.md §14): FIP pitcher rating, two-stage grid.

Stage 1: v1 team settings fixed; c × H_p × m (36 cells).
Stage 2: best pitcher settings fixed; v1's team grid without c/α (640 cells).
Validation 2015 → 2025; 2026 (test) is never loaded. Refuses to overwrite.

    uv run python -m scripts.mlb_v2_freeze
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.mlb import backtest, ratings, tuner
from app.mlb.api import load_params

ART = Path(__file__).resolve().parent.parent / "artifacts" / "mlb" / "frozen_params_v2.json"
WARMUP = list(range(2000, 2015))
VALIDATION = list(range(2015, 2026))
TEST = [2026]
PITCHER_GRID = {"c": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0], "h_p": [10.0, 20.0, 40.0], "m_ip": [20.0, 50.0]}
TEAM_KEYS = ("k_regular", "k_playoff", "carry", "home_bump", "mov")


def evaluate(params, data) -> dict:
    res = backtest.run(WARMUP + VALIDATION, params, data=data, record_predictions_for=set(VALIDATION))
    y = [p.outcome for p in res.predictions]
    return {**{k: v for k, v in params.__dict__.items()}, **tuner.score([p.home_win_prob for p in res.predictions], y)}


def key(r):
    return (r["log_loss"], r["ece"], r["brier"])


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if ART.exists() and "--force" not in argv:
        print(f"REFUSED: {ART} exists; MLB v2 is frozen.", file=sys.stderr)
        return 3
    assert not set(TEST) & set(WARMUP + VALIDATION)
    t0 = time.time()
    data = backtest.load(WARMUP + VALIDATION)
    v1 = load_params()
    v1_row = evaluate(v1, data)
    stage1 = [evaluate(ratings.Params(**{**v1.__dict__, "pitcher_model": "fip", **dict(zip(PITCHER_GRID, v))}), data)
              for v in itertools.product(*PITCHER_GRID.values())]
    p1 = min(stage1, key=key)
    print(f"stage 1 best: c={p1['c']} h_p={p1['h_p']} m_ip={p1['m_ip']} LL {p1['log_loss']:.5f} (v1 {v1_row['log_loss']:.5f})", flush=True)
    team_grid = {k: tuner.GRID[k] for k in TEAM_KEYS}
    base = {**v1.__dict__, "pitcher_model": "fip", "c": p1["c"], "h_p": p1["h_p"], "m_ip": p1["m_ip"]}
    stage2 = []
    for i, v in enumerate(itertools.product(*team_grid.values()), 1):
        stage2.append(evaluate(ratings.Params(**{**base, **dict(zip(TEAM_KEYS, v))}), data))
        if i % 160 == 0:
            print(f"  stage 2: {i}/640", flush=True)
    win = min(stage2, key=key)
    fields = ratings.Params.__dataclass_fields__
    team_only = evaluate(ratings.Params(**({k: win[k] for k in fields} | {"c": 0.0})), data)
    payload = {
        "methodology_version": "mlb-2.0", "frozen_at": datetime.now(timezone.utc).isoformat(),
        "warmup_seasons": WARMUP, "validation_seasons": VALIDATION, "test_seasons_untouched": TEST,
        "winner": win, "v1_on_v2_validation": v1_row, "team_only_at_winner": team_only,
        "expectations": {"c_in_15_40": 15 <= win["c"] <= 40},
        "stage1": stage1, "stage2": stage2, "wall_seconds": round(time.time() - t0, 1),
    }
    ART.write_text(json.dumps(payload, indent=2, default=str))
    print(f"winner: { {k: win[k] for k in ('k_regular','k_playoff','carry','home_bump','mov','c','h_p','m_ip')} }")
    print(f"validation LL {win['log_loss']:.5f} ECE {win['ece']:.4f} | v1 {v1_row['log_loss']:.5f} | team-only {team_only['log_loss']:.5f}")
    print(f"wrote {ART} ({payload['wall_seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
