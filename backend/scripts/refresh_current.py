"""Refresh every sport's current-season data on disk (run before each deploy).

Cloud Run's filesystem is ephemeral and instances scale to zero, so the data
baked into the image IS the site's data. The deploy workflow runs this (and
nightly on a schedule), then builds the image. Each sport is independent: a
failure is reported and the others still refresh. Only current-season data is
touched; no model is refitted.

    uv run python -m scripts.refresh_current
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from datetime import date


async def _nhl() -> dict:
    from app import boxscores, engine, nhl_projections, pipeline
    sid = engine._current_season_id(date.today())
    await pipeline.ingest_one(sid, today=date.today(), force=True)
    box = await boxscores.ingest_season(sid, live=True)
    out = {"season": sid, "box_games": box["kept"]}
    if nhl_projections.available():
        nhl_projections.build_and_save()
        out["projection_state"] = "rebuilt"
    return out


async def _nba() -> dict:
    from app.nba import pipeline
    sid = pipeline.current_season_id()
    r = await pipeline.ingest_one(sid)
    return {"season": sid, "rows": r["rows"]}


async def _nfl() -> dict:
    from app.nfl import pipeline
    return {"rows": pipeline.ingest()["rows"]}


async def _mlb() -> dict:
    from app.mlb import pipeline
    r = await pipeline.ingest_season(pipeline.current_season())
    return {"season": r["season"], "rows": r["rows"], "starter_lines": r["starter_lines"]}


async def _cfb() -> dict:
    from app.cfb import pipeline
    r = await pipeline.ingest_season(pipeline.current_season())
    return {"season": pipeline.current_season(), **{k: v for k, v in r.items() if isinstance(v, (int, str))}}


async def main() -> int:
    results = {}
    for name, fn in (("nhl", _nhl), ("nba", _nba), ("nfl", _nfl), ("mlb", _mlb), ("cfb", _cfb)):
        t0 = time.time()
        try:
            results[name] = {"ok": True, **(await fn()), "seconds": round(time.time() - t0, 1)}
        except Exception as exc:  # noqa: BLE001 — stale data for one sport beats no deploy
            traceback.print_exc()
            results[name] = {"ok": False, "error": repr(exc)[:300], "seconds": round(time.time() - t0, 1)}
        print(f"  {name}: {results[name]}", flush=True)
    print(json.dumps(results, indent=2))
    # Fail only if every sport failed (e.g. no network); partial staleness still deploys.
    return 0 if any(r["ok"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
