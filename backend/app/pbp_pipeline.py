"""Play-by-play (goals-only) ingest pipeline — v2.2 §15.

For every completed NHL game in the training window (2010-11 → 2024-25 per
§15), this module fetches the NHL `/v1/gamecenter/{gameId}/play-by-play`
payload, extracts goal events with their (period, time, score-after) context,
and writes one parquet file per season at `data_cache/pbp_goals/{season}.parquet`.

A manifest at `data_cache/pbp_manifest.json` tracks which (season, game_id)
pairs have already been ingested so the pipeline can resume safely.

This is intentionally goals-only — the live-WP empirical lookup only needs
goal timing and resulting scores. Shots, penalties, faceoffs, etc. would be
useful for richer state models in a future version but are out of scope here.

CLI:
    uv run python -m app.pbp_pipeline ingest --season 20242025
    uv run python -m app.pbp_pipeline ingest --since 20102011
    uv run python -m app.pbp_pipeline ingest --all          (training window only)
    uv run python -m app.pbp_pipeline status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from . import pipeline as score_pipeline

BASE = "https://api-web.nhle.com/v1"
HTTP_TIMEOUT = 15.0
CONCURRENCY = 8

# v2.2 §15 training window. 2025-26 is the v2 test set and is excluded.
TRAINING_SEASONS: list[int] = [
    s for s in range(20102011, 20242025 + 10001, 10001)
    if s != 20042005  # already excluded; safety
]

DATA_CACHE = Path(__file__).resolve().parent.parent / "data_cache"
PBP_DIR = DATA_CACHE / "pbp_goals"
MANIFEST_PATH = DATA_CACHE / "pbp_manifest.json"

SCHEMA = pa.schema([
    ("game_id", pa.int64()),
    ("period", pa.int8()),
    ("period_type", pa.string()),  # REG / OT / SO
    ("time_in_period_s", pa.int16()),
    ("time_remaining_in_period_s", pa.int16()),
    ("home_score_after", pa.int8()),
    ("away_score_after", pa.int8()),
])


# ---- Parsing ---------------------------------------------------------------

def _mmss_to_seconds(s: str) -> int:
    """'09:34' -> 574 seconds. Returns 0 on malformed input."""
    if not s or ":" not in s:
        return 0
    try:
        mm, ss = s.split(":")
        return int(mm) * 60 + int(ss)
    except (ValueError, TypeError):
        return 0


def _parse_goal_events(game_id: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk the play-by-play, return one dict per goal."""
    plays = payload.get("plays") or []
    rows: list[dict[str, Any]] = []
    for p in plays:
        if p.get("typeDescKey") != "goal":
            continue
        pd = p.get("periodDescriptor") or {}
        details = p.get("details") or {}
        home_after = details.get("homeScore")
        away_after = details.get("awayScore")
        if home_after is None or away_after is None:
            continue  # malformed; skip rather than mis-attribute
        rows.append({
            "game_id": game_id,
            "period": int(pd.get("number") or 0),
            "period_type": pd.get("periodType") or "REG",
            "time_in_period_s": _mmss_to_seconds(p.get("timeInPeriod") or "0:00"),
            "time_remaining_in_period_s": _mmss_to_seconds(p.get("timeRemaining") or "0:00"),
            "home_score_after": int(home_after),
            "away_score_after": int(away_after),
        })
    return rows


# ---- HTTP fetching --------------------------------------------------------

async def _fetch_pbp(
    client: httpx.AsyncClient,
    game_id: int,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Fetch one game's play-by-play. Returns the goal-event rows, possibly empty.

    Persistent 404s and 5xx after retries are tolerated as "no data for this
    game" — old games occasionally lack a play-by-play feed and we don't want
    a single bad record to break a whole-season ingest.
    """
    async with sem:
        url = f"{BASE}/gamecenter/{game_id}/play-by-play"
        for attempt in range(3):
            try:
                r = await client.get(url, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                return _parse_goal_events(game_id, r.json())
            except httpx.HTTPStatusError as exc:
                if attempt == 2:
                    code = exc.response.status_code
                    print(f"  [warn] game {game_id}: HTTP {code} — skipping", file=sys.stderr)
                    return []
            except (httpx.HTTPError, httpx.TimeoutException):
                if attempt == 2:
                    raise
            await asyncio.sleep(0.4 * (attempt + 1))
        return []


# ---- Per-season orchestration ---------------------------------------------

def _completed_game_ids_in_season(season_id: int) -> list[int]:
    """Read the existing score parquet to find every completed game id."""
    path = score_pipeline.RAW_DIR / f"{season_id}.parquet"
    if not path.exists():
        return []
    t = pq.read_table(path, columns=["game_id", "game_type", "state"])
    # Regular season + playoffs only; all-star and special events excluded.
    keep = pc.and_(
        pc.or_(pc.equal(t.column("game_type"), 2), pc.equal(t.column("game_type"), 3)),
        pc.or_(pc.equal(t.column("state"), "OFF"), pc.equal(t.column("state"), "FINAL")),
    )
    return sorted(t.filter(keep).column("game_id").to_pylist())


async def ingest_season(
    season_id: int,
    *,
    skip_existing: bool = True,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, int]:
    """Fetch and store goal events for one season. Returns (n_games, n_goals)."""
    game_ids = _completed_game_ids_in_season(season_id)
    if not game_ids:
        return 0, 0

    PBP_DIR.mkdir(parents=True, exist_ok=True)
    final = PBP_DIR / f"{season_id}.parquet"
    if skip_existing and final.exists():
        existing = pq.read_table(final, columns=["game_id"])
        n_unique_games = len(set(existing.column("game_id").to_pylist()))
        return n_unique_games, existing.num_rows

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient()

    try:
        sem = asyncio.Semaphore(CONCURRENCY)
        chunks = await asyncio.gather(
            *[_fetch_pbp(client, gid, sem) for gid in game_ids]
        )
        rows: list[dict[str, Any]] = []
        for chunk in chunks:
            rows.extend(chunk)

        table = _table_from_rows(rows)
        tmp = final.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, final)
        _update_manifest(season_id, len(game_ids), len(rows))
        return len(game_ids), len(rows)
    finally:
        if owns_client:
            await client.aclose()


def _table_from_rows(rows: list[dict[str, Any]]) -> pa.Table:
    if not rows:
        return SCHEMA.empty_table()
    cols = {name: [] for name in SCHEMA.names}
    for r in rows:
        for name in SCHEMA.names:
            cols[name].append(r.get(name))
    arrays = [pa.array(cols[name], type=SCHEMA.field(name).type) for name in SCHEMA.names]
    return pa.Table.from_arrays(arrays, schema=SCHEMA)


# ---- Manifest -------------------------------------------------------------

def _load_manifest() -> dict[str, dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text())


def _update_manifest(season_id: int, n_games: int, n_goals: int) -> None:
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    manifest[str(season_id)] = {
        "season_id": season_id,
        "n_games": n_games,
        "n_goals": n_goals,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(tmp, MANIFEST_PATH)


# ---- Convenience accessor -------------------------------------------------

def read_goal_events(season_id: int) -> pa.Table:
    return pq.read_table(PBP_DIR / f"{season_id}.parquet")


# ---- CLI ------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="app.pbp_pipeline",
                                description="play-by-play goal-event ingest")
    sub = p.add_subparsers(dest="cmd", required=True)
    ingest = sub.add_parser("ingest", help="fetch and store goal events")
    sel = ingest.add_mutually_exclusive_group(required=True)
    sel.add_argument("--season", type=int)
    sel.add_argument("--all", action="store_true",
                     help="every v2.2 training season")
    sel.add_argument("--since", type=int)
    ingest.add_argument("--force", action="store_true",
                        help="re-fetch even if season parquet exists")
    sub.add_parser("status")
    return p


async def _cmd_ingest(args: argparse.Namespace) -> int:
    if args.all:
        seasons: list[int] = list(TRAINING_SEASONS)
    elif args.since:
        seasons = [s for s in TRAINING_SEASONS if s >= args.since]
    else:
        seasons = [args.season]
    skip = not args.force
    print(f"ingesting PBP for {len(seasons)} season(s); skip_existing={skip}")
    async with httpx.AsyncClient() as client:
        for sid in seasons:
            n_games, n_goals = await ingest_season(
                sid, skip_existing=skip, client=client,
            )
            print(f"  [{sid}] {n_games} games, {n_goals} goal events")
    return 0


def _cmd_status(_: argparse.Namespace) -> int:
    manifest = _load_manifest()
    if not manifest:
        print("(empty)")
        return 0
    for key in sorted(manifest, key=int):
        e = manifest[key]
        print(f"  {e['season_id']}  {e['n_games']:>5} games  {e['n_goals']:>5} goals  "
              f"{e.get('ingested_at', '?')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "ingest":
        return asyncio.run(_cmd_ingest(args))
    if args.cmd == "status":
        return _cmd_status(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
