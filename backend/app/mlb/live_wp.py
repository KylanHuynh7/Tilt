"""MLB v1.1 live win probability (methodology/MLB.md §12, v1.2).

    logit P(home) = β0 + β1 · pre · (o / 54) + β2 · (d + s · RE(bases, outs)) / sqrt(o / 3 + 1)

    pre = logit of the frozen pre-game P(home);  d = home − away runs
    s   = +1 home batting (bottom), −1 away batting (top)
    o   = outs remaining (v1.2 formula; extras count only the current inning)
    RE  = mean runs from this base-out state to the end of the half-inning,
          computed once from the training seasons (24 cells)
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..core.logistic import fit as logistic_fit, sigmoid
from . import backtest, pbp, pipeline, ratings
from .api import load_params

ARTIFACT = Path(__file__).resolve().parents[2] / "artifacts" / "mlb" / "live_wp_v1.json"


def outs_remaining(inning: int, bottom: bool, outs: int) -> int:
    left = 3 - outs
    if inning <= 9:
        return left + (0 if bottom else 3) + 6 * (9 - inning)
    return left + (0 if bottom else 3)


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def features(pre: float, o: int, d: int, s: int, re: float) -> list[float]:
    return [1.0, pre * o / 54.0, (d + s * re) / math.sqrt(o / 3.0 + 1.0)]


def run_expectancy(seasons: Sequence[int]) -> dict[tuple[int, int], float]:
    """RE[(outs, bases)] = mean runs scored from that state to the end of the
    half-inning, over every training plate appearance.
    """
    finals = {}
    for s in seasons:
        for g in pipeline.read_games(s):
            if pipeline.is_valid_result(g):
                finals[g["game_pk"]] = (g["home_score"], g["away_score"])
    tot: dict[tuple[int, int], float] = defaultdict(float)
    n: dict[tuple[int, int], int] = defaultdict(int)
    for s in seasons:
        by_game: dict[int, list[dict]] = defaultdict(list)
        for r in pbp.read_season(s):
            by_game[r["game_pk"]].append(r)
        for pk, rows in by_game.items():
            rows.sort(key=lambda r: r["seq"])
            halves: dict[tuple[int, bool], list[dict]] = defaultdict(list)
            for r in rows:
                halves[(r["inning"], r["bottom"])].append(r)
            order = sorted(halves, key=lambda k: (k[0], k[1]))
            for i, key in enumerate(order):
                bat = "home_score" if key[1] else "away_score"
                if i + 1 < len(order):
                    end = halves[order[i + 1]][0][bat]
                else:
                    end = finals[pk][0 if key[1] else 1]
                for r in halves[key]:
                    cell = (r["outs"], r["bases"])
                    tot[cell] += end - r[bat]
                    n[cell] += 1
    return {cell: tot[cell] / n[cell] for cell in n}


def pregame(seasons: Sequence[int]) -> dict[int, backtest.Prediction]:
    params = load_params()
    replay = list(range(pipeline.FIRST_SEASON, max(seasons) + 1))
    data = backtest.load(replay)
    res = backtest.run(replay, params, data=data, record_predictions_for=set(seasons))
    return {p.game_pk: p for p in res.predictions}


def build_samples(seasons, pre, re):
    xs, ys, meta = [], [], []
    for s in seasons:
        for r in pbp.read_season(s):
            p = pre.get(r["game_pk"])
            if p is None:
                continue
            o = outs_remaining(r["inning"], r["bottom"], r["outs"])
            sgn = 1 if r["bottom"] else -1
            xs.append(features(logit(p.home_win_prob), o, r["home_score"] - r["away_score"], sgn,
                               re.get((r["outs"], r["bases"]), 0.0)))
            ys.append(p.outcome)
            meta.append((r["game_pk"], r["inning"]))
    return xs, ys, meta


def predict(beta, re, *, pre_game_p: float, inning: int, bottom: bool, outs: int, bases: int, d: int) -> float:
    o = outs_remaining(inning, bottom, outs)
    x = features(logit(pre_game_p), o, d, 1 if bottom else -1, re.get((outs, bases), 0.0))
    return sigmoid(sum(b * v for b, v in zip(beta, x)))


def checks(beta, re, pre_ps: Sequence[float]) -> dict:
    lo, hi = min(pre_ps), max(pre_ps)
    grid = [lo + (hi - lo) * i / 50 for i in range(51)]
    first_pitch_gap = max(abs(predict(beta, re, pre_game_p=p, inning=1, bottom=False, outs=0, bases=0, d=0) - p)
                          for p in grid)
    # Away leads by 5 in the bottom of the 9th, 2 outs, home batting, any bases.
    worst = min(1 - predict(beta, re, pre_game_p=p, inning=9, bottom=True, outs=2, bases=b, d=-5)
                for p in grid for b in range(8))
    return {"pre_game_p_range": [round(lo, 4), round(hi, 4)],
            "first_pitch_max_abs_gap": first_pitch_gap, "first_pitch_within_0_02": first_pitch_gap <= 0.02,
            "monotone_in_score_diff": beta[2] > 0,
            "leader_by_5_bottom_9_two_outs_min_wp": worst,
            "leader_by_5_bottom_9_two_outs_ge_0_97": worst >= 0.97}


def fit(xs, ys) -> list[float]:
    return logistic_fit(xs, ys)


def save(beta, re, payload: dict) -> None:
    ARTIFACT.write_text(json.dumps({
        "methodology_version": "mlb-1.2", "fitted_at": datetime.now(timezone.utc).isoformat(),
        "coefficients": dict(zip(["b0", "b1", "b2"], beta)),
        "run_expectancy": {f"{o}-{b}": v for (o, b), v in sorted(re.items())},
        **payload}, indent=2))


_loaded: tuple[list[float], dict] | None = None


def load() -> tuple[list[float], dict]:
    global _loaded
    if _loaded is None:
        a = json.loads(ARTIFACT.read_text())
        beta = [a["coefficients"][k] for k in ("b0", "b1", "b2")]
        re = {tuple(int(x) for x in k.split("-")): v for k, v in a["run_expectancy"].items()}
        _loaded = (beta, re)
    return _loaded
