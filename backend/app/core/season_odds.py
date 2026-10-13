"""Shared response shape for per-sport season/playoff odds simulations.

Each sport's simulator returns rows; this module adds the column schema the
shared frontend table renders, and caches one result per ratings build.
"""

from __future__ import annotations

import time
from typing import Callable

_cache: dict[str, tuple[object, float, dict]] = {}


def cached(sport: str, version: object, build: Callable[[], dict], ttl: float = 3600) -> dict:
    """Rebuild when the sport's ratings cache changes (`version`) or after `ttl` seconds."""
    hit = _cache.get(sport)
    if hit and hit[0] == version and time.time() - hit[1] < ttl:
        return hit[2]
    out = build()
    _cache[sport] = (version, time.time(), out)
    return out


def payload(*, sport: str, season: int, n: int, games_left: int, columns: list[dict], rows: list[dict],
            note: str, label: str) -> dict:
    return {"sport": sport, "season": season, "n_simulations": n, "games_left": games_left,
            "columns": columns, "rows": rows, "note": note, "title_label": label}
