"""NBA play-by-play → minute-mark game states (methodology/NBA.md §12, v1.2).

For each game, ESPN's `summary` endpoint is fetched and ONLY its `plays`
list is read (its win-probability / odds blocks are never touched, §10).
Each game becomes one row per game-minute: 48 regulation marks (12:00 …
1:00 of every quarter) plus 5 per overtime (5:00 … 1:00), carrying the
running score at that mark. A game is kept only if its last play's score
matches the scoreboard final (v1.2 validity rule).

    uv run python -m app.nba.pbp ingest --season 20092010
    uv run python -m app.nba.pbp ingest --train      # 2009-10 → 2017-18
    uv run python -m app.nba.pbp ingest --test       # 2024-25, 2025-26
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from . import backtest, espn
from .teams import is_franchise

SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
PBP_DIR = backtest.pipeline.DATA_DIR / "pbp"
MANIFEST_PATH = PBP_DIR / "manifest.json"

TRAIN_SEASONS = [20092010 + 10001 * i for i in range(9)]  # 2009-10 → 2017-18
TEST_SEASONS = [20242025, 20252026]
CONCURRENCY = 12

QUARTER_S = 720
OT_S = 300

SCHEMA = pa.schema([
    ("game_id", pa.int64()),
    ("period", pa.int8()),
    ("sec_left", pa.int16()),   # seconds left in the period at this mark
    ("home_score", pa.int16()),
    ("away_score", pa.int16()),
])


def parse_clock(display: str) -> float:
    """ESPN clocks are "11:34" above a minute and "34.5" below it."""
    display = display.strip()
    if ":" in display:
        mm, ss = display.split(":")
        return int(mm) * 60 + float(ss)
    return float(display)


def period_length(period: int) -> int:
    return QUARTER_S if period <= 4 else OT_S


def minute_marks(n_periods: int) -> list[tuple[int, int]]:
    """(period, sec_left) for every game-minute mark, in chronological order."""
    marks = []
    for p in range(1, n_periods + 1):
        length = period_length(p)
        marks.extend((p, s) for s in range(length, 0, -60))
    return marks


def samples_from_plays(plays: list[dict], n_periods: int) -> list[tuple[int, int, int, int]]:
    """Running score at each minute mark: every play at or before the mark
    counts. Plays are in ESPN's chronological order.
    """
    timeline = []
    for pl in plays:
        p = int(pl["period"]["number"])
        timeline.append((p, parse_clock(pl["clock"]["displayValue"]),
                         int(pl["homeScore"]), int(pl["awayScore"])))
    out = []
    i, home, away = 0, 0, 0
    for p, mark in minute_marks(n_periods):
        # Consume plays that happened at or before this mark: earlier
        # periods, or this period with at least `mark` seconds left.
        while i < len(timeline) and (timeline[i][0] < p or (timeline[i][0] == p and timeline[i][1] >= mark)):
            home, away = timeline[i][2], timeline[i][3]
            i += 1
        out.append((p, mark, home, away))
    return out


async def fetch_plays(client: httpx.AsyncClient, game_id: int) -> list[dict]:
    last_exc: Exception | None = None
    for attempt in range(espn.MAX_RETRIES):
        try:
            r = await client.get(SUMMARY_URL, params={"event": game_id}, timeout=30)
            r.raise_for_status()
            return r.json().get("plays") or []  # the only block read (§10, v1.2)
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"ESPN summary failed for {game_id}: {last_exc!r}")


def _season_games(season_id: int) -> list[dict]:
    return [r for r in backtest.model_rows(season_id)
            if is_franchise(r["home_team_id"]) and is_franchise(r["away_team_id"])]


async def ingest_season(season_id: int) -> dict:
    games = _season_games(season_id)
    sem = asyncio.Semaphore(CONCURRENCY)
    rows: list[dict] = []
    dropped = {"no_plays": 0, "final_mismatch": 0}

    async def one(client: httpx.AsyncClient, g: dict) -> None:
        async with sem:
            plays = await fetch_plays(client, g["game_id"])
        if not plays:
            dropped["no_plays"] += 1
            return
        last = plays[-1]
        if (int(last["homeScore"]), int(last["awayScore"])) != (g["home_score"], g["away_score"]):
            dropped["final_mismatch"] += 1
            return
        n_periods = max(4, g["n_periods"] or 4, max(int(p["period"]["number"]) for p in plays))
        for p, s, h, a in samples_from_plays(plays, n_periods):
            rows.append({"game_id": g["game_id"], "period": p, "sec_left": s,
                         "home_score": h, "away_score": a})

    async with httpx.AsyncClient(headers={"User-Agent": "tilt-nba-pbp"}) as client:
        await asyncio.gather(*[one(client, g) for g in games])

    rows.sort(key=lambda r: (r["game_id"], r["period"], -r["sec_left"]))
    PBP_DIR.mkdir(parents=True, exist_ok=True)
    final = PBP_DIR / f"{season_id}.parquet"
    tmp = final.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), tmp, compression="zstd")
    os.replace(tmp, final)

    kept = len({r["game_id"] for r in rows})
    entry = {"games": len(games), "kept": kept, **dropped, "samples": len(rows),
             "pulled_at": datetime.now(timezone.utc).isoformat()}
    manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
    manifest[str(season_id)] = entry
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return {"season_id": season_id, **entry}


def read_season(season_id: int) -> list[dict]:
    return pq.read_table(PBP_DIR / f"{season_id}.parquet").to_pylist()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.nba.pbp")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--train", action="store_true")
    g.add_argument("--test", action="store_true")
    args = p.parse_args(argv)
    ids = [args.season] if args.season else (TRAIN_SEASONS if args.train else TEST_SEASONS)
    for sid in ids:
        r = asyncio.run(ingest_season(sid))
        print(f"  [{sid}] kept {r['kept']}/{r['games']} games · no plays {r['no_plays']} · "
              f"final mismatch {r['final_mismatch']} · {r['samples']} samples", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
