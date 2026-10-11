"""College football v1.1 live win probability (methodology/CFB.md §12, v1.3).

Same five-term form as NFL §12 (refitted on college data):
    logit P = β0 + β1·pre·(τ/3600) + β2·d/√(m+1) + β3·s·(1 − y/100)/√(m+1) + β4·s/√(m+1)
College overtime is untimed, so OT plays use τ = 0 (v1.3).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..core.logistic import fit as logistic_fit, sigmoid
from ..nfl.live_wp import features, logit  # identical feature definitions
from . import backtest, pbp, tuner
from .api import load_params

ARTIFACT = Path(__file__).resolve().parents[2] / "artifacts" / "cfb" / "live_wp_v1.json"


def tau_for(qtr: int, clock_s: float) -> float:
    return (4 - qtr) * 900 + clock_s if qtr <= 4 else 0.0


def pregame(seasons: Sequence[int]) -> dict:
    params = load_params()
    replay = list(range(2001, max(seasons) + 1))
    res = backtest.run(replay, params, data=backtest.load(replay), record_predictions_for=set(seasons))
    return {p.game_id: p for p in tuner.fbs_only(res.predictions)}


def build_samples(seasons, pre):
    xs, ys, meta = [], [], []
    for s in seasons:
        for r in pbp.read_season(s):
            p = pre.get(r["game_id"])
            if p is None:
                continue
            xs.append(features(logit(p.home_win_prob), tau_for(r["qtr"], r["clock_s"]),
                               r["home_score"] - r["away_score"], r["home_poss"], r["yards_to_ez"]))
            ys.append(p.outcome)
            meta.append((r["game_id"], r["qtr"]))
    return xs, ys, meta


def predict(beta, *, pre_game_p, qtr, clock_s, d, s=0, y=50) -> float:
    x = features(logit(pre_game_p), tau_for(qtr, clock_s), d, s, y)
    return sigmoid(sum(b * v for b, v in zip(beta, x)))


def checks(beta, pre_ps):
    lo, hi = min(pre_ps), max(pre_ps)
    grid = [lo + (hi - lo) * i / 50 for i in range(51)]
    kick = max(abs(predict(beta, pre_game_p=p, qtr=1, clock_s=900, d=0) - p) for p in grid)
    worst = 1.0
    for p in grid:
        for s in (-1, 0, 1):
            for y in range(1, 100, 2):
                worst = min(worst, predict(beta, pre_game_p=p, qtr=4, clock_s=120, d=17, s=s, y=y),
                            1 - predict(beta, pre_game_p=p, qtr=4, clock_s=120, d=-17, s=s, y=y))
    return {"pre_game_p_range": [round(lo, 4), round(hi, 4)], "kickoff_max_abs_gap_to_pregame": kick,
            "kickoff_within_0_02": kick <= 0.02, "monotone_in_score_diff": beta[2] > 0,
            "leader_by_17_with_2_min_left_min_wp": worst, "leader_by_17_with_2_min_left_ge_0_97": worst >= 0.97}


def fit(xs, ys):
    return logistic_fit(xs, ys)


def save(beta, payload):
    ARTIFACT.write_text(json.dumps({"methodology_version": "cfb-1.3", "fitted_at": datetime.now(timezone.utc).isoformat(),
                                    "coefficients": dict(zip(["b0", "b1", "b2", "b3", "b4"], beta)), **payload}, indent=2))


_beta = None


def load():
    global _beta
    if _beta is None:
        c = json.loads(ARTIFACT.read_text())["coefficients"]
        _beta = [c[k] for k in ("b0", "b1", "b2", "b3", "b4")]
    return _beta
