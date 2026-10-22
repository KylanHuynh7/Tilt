"""Postseason calibration layer (methodology/POSTSEASON.md).

    p_post = σ(λ · logit(p)),  0 < λ ≤ 1,  postseason games only.

Ratings are untouched: only the published postseason forecast changes. λ is
fitted per sport on its fitting window and frozen in artifacts/postseason/.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "artifacts" / "postseason" / "lambdas.json"
GRID = [round(0.50 + 0.05 * i, 2) for i in range(11)]          # 0.50 … 1.00
FIT_SEASONS = {"nfl": list(range(2015, 2026)), "mlb": list(range(2015, 2026))}
TEST_SEASON = {"nfl": 2026, "mlb": 2026}


def shrink(p: float, lam: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return 1.0 / (1.0 + math.exp(-lam * math.log(p / (1 - p))))


def log_loss(ps: Sequence[float], ys: Sequence[float]) -> float:
    eps = 1e-15
    return -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in zip(ps, ys)) / len(ps)


def fit(ps: Sequence[float], ys: Sequence[float]) -> tuple[float, dict[float, float]]:
    """λ minimising postseason log-loss on the grid; ties go to the larger λ (less change)."""
    table = {lam: log_loss([shrink(p, lam) for p in ps], ys) for lam in GRID}
    best = min(GRID, key=lambda lam: (table[lam], -lam))
    return best, table


_cache: dict | None = None


def lam_for(sport: str) -> float | None:
    """Frozen λ for a sport if its layer is active (fitted and not switched off)."""
    global _cache
    if _cache is None:
        _cache = json.loads(ARTIFACT.read_text()) if ARTIFACT.exists() else {}
    s = _cache.get(sport) or {}
    if not s or s.get("active") is False or s.get("lambda", 1.0) >= 1.0:
        return None
    return float(s["lambda"])


def apply(sport: str, p: float, is_postseason: bool) -> tuple[float, float | None]:
    """(published probability, λ used or None)."""
    lam = lam_for(sport) if is_postseason else None
    return (shrink(p, lam), lam) if lam else (p, None)
