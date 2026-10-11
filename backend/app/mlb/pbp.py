"""MLB play-by-play → plate-appearance states (methodology/MLB.md §12, v1.2).

Fetches `game/{pk}/playByPlay` for every valid game in a season and keeps one
row per plate appearance with the state BEFORE it: inning, half, outs, bases
(bitmask 1B=1, 2B=2, 3B=4), and score. Only the v1.2 fields are read. A game
is kept only if its last play's score equals the official final.

Resumable: games already in the season parquet are skipped, so an
interrupted download continues where it stopped.

    uv run python -m app.mlb.pbp ingest --train   # 2010–2014
    uv run python -m app.mlb.pbp ingest --test    # 2022–2025 (one-shot evaluator only)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from . import pipeline
from .teams import is_franchise

PBP_DIR = pipeline.DATA_DIR / "pbp"
MANIFEST = PBP_DIR / "manifest.json"
TRAIN_SEASONS = [2010, 2011, 2012, 2013, 2014]
TEST_SEASONS = [2022, 2023, 2024, 2025]
CONCURRENCY = 10
GHOST_RUNNER_FROM = 2020

SCHEMA = pa.schema([
    ("game_pk", pa.int64()), ("seq", pa.int16()), ("inning", pa.int8()), ("bottom", pa.bool_()),
    ("outs", pa.int8()), ("bases", pa.int8()), ("home_score", pa.int16()), ("away_score", pa.int16()),
])


def _bases(m: dict) -> int:
    return (1 if m.get("postOnFirst") else 0) | (2 if m.get("postOnSecond") else 0) | (4 if m.get("postOnThird") else 0)


def states_from_plays(plays: list[dict], *, ghost_runner: bool) -> list[dict]:
    """State before each plate appearance (v1.2)."""
    out = []
    prev_key = None
    outs, bases, hs, as_ = 0, 0, 0, 0
    for i, p in enumerate(plays):
        about = p["about"]
        inning, bottom = int(about["inning"]), about["halfInning"] == "bottom"
        key = (inning, bottom)
        if key != prev_key:  # new half-inning: reset outs and bases
            outs = 0
            bases = 2 if (ghost_runner and inning >= 10) else 0
            prev_key = key
        out.append({"seq": i, "inning": inning, "bottom": bottom, "outs": min(outs, 2),
                    "bases": bases, "home_score": hs, "away_score": as_})
        res = p.get("result") or {}
        hs, as_ = int(res.get("homeScore", hs)), int(res.get("awayScore", as_))
        outs = int((p.get("count") or {}).get("outs", outs))
        bases = _bases(p.get("matchup") or {})
    return out


async def _fetch(client: httpx.AsyncClient, pk: int) -> list[dict]:
    last = None
    for attempt in range(4):
        try:
            r = await client.get(f"{pipeline.API}/game/{pk}/playByPlay", timeout=30)
            r.raise_for_status()
            return r.json().get("allPlays") or []
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"playByPlay {pk} failed: {last!r}")


async def ingest_season(season: int) -> dict:
    games = [g for g in pipeline.read_games(season)
             if pipeline.is_valid_result(g) and is_franchise(g["home_id"]) and is_franchise(g["away_id"])]
    path = PBP_DIR / f"{season}.parquet"
    rows = pq.read_table(path).to_pylist() if path.exists() else []
    have = {r["game_pk"] for r in rows}
    todo = [g for g in games if g["game_pk"] not in have]
    stats = {"no_plays": 0, "final_mismatch": 0}
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, g):
        async with sem:
            plays = await _fetch(client, g["game_pk"])
        if not plays:
            stats["no_plays"] += 1
            return []
        last = plays[-1].get("result") or {}
        if (last.get("homeScore"), last.get("awayScore")) != (g["home_score"], g["away_score"]):
            stats["final_mismatch"] += 1
            return []
        ghost = season >= GHOST_RUNNER_FROM and g["game_type"] == "R"
        return [{"game_pk": g["game_pk"], **s} for s in states_from_plays(plays, ghost_runner=ghost)]

    async with httpx.AsyncClient(headers={"User-Agent": "tilt-mlb (non-commercial)", "Accept-Encoding": "gzip"}) as client:
        # Chunks so progress is saved as we go (resumable).
        for start in range(0, len(todo), 400):
            chunk = todo[start:start + 400]
            for part in await asyncio.gather(*[one(client, g) for g in chunk]):
                rows.extend(part)
            PBP_DIR.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")

    kept = len({r["game_pk"] for r in rows})
    m = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    prev = m.get(str(season), {})
    m[str(season)] = {"games": len(games), "kept": kept, "pa_rows": len(rows),
                      "no_plays": prev.get("no_plays", 0) + stats["no_plays"],
                      "final_mismatch": prev.get("final_mismatch", 0) + stats["final_mismatch"]}
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))
    return {"season": season, **m[str(season)]}


def read_season(season: int) -> list[dict]:
    return pq.read_table(PBP_DIR / f"{season}.parquet").to_pylist()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.mlb.pbp")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--train", action="store_true")
    g.add_argument("--test", action="store_true")
    a = p.parse_args(argv)
    for s in ([a.season] if a.season else TRAIN_SEASONS if a.train else TEST_SEASONS):
        r = asyncio.run(ingest_season(s))
        print(f"  [{s}] kept {r['kept']}/{r['games']} · mismatch {r['final_mismatch']} · "
              f"no plays {r['no_plays']} · {r['pa_rows']} PAs", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
