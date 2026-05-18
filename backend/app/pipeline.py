"""Idempotent NHL API ingest to Parquet — Phase A of v1 milestone 2.

Pulls every game from `/v1/score/{date}` across each season's window and writes
one Parquet file per season to `data_cache/raw/{season_id}.parquet`. A manifest
at `data_cache/manifest.json` records what was pulled and when.

Idempotency rules:
  - Re-running ingest on a completed past season overwrites the file atomically
    (write to .tmp, rename). The output should be byte-identical modulo API
    drift, which is rare for historical games.
  - The current season can be re-pulled freely; that's how new games land.
  - --skip-existing avoids re-pulling seasons already in the manifest. --force
    overrides any skip logic.

This module deliberately knows nothing about ratings or evaluation. Per §10 #1
it ingests every season, including the held-out test set (2023-24, 2024-25),
but evaluation code is segregated into a separate script that loads the frozen
parameters and is run exactly once at the end of milestone 2.

CLI:
  uv run python -m app.pipeline ingest --season 20232024
  uv run python -m app.pipeline ingest --all [--skip-existing] [--force]
  uv run python -m app.pipeline ingest --since 20002001
  uv run python -m app.pipeline list
  uv run python -m app.pipeline status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from . import seasons

BASE = "https://api-web.nhle.com/v1"
HTTP_TIMEOUT = 15.0
CONCURRENCY = 6  # polite to the public API; ~7s per season at this rate

DATA_CACHE = Path(__file__).resolve().parent.parent / "data_cache"
RAW_DIR = DATA_CACHE / "raw"
MANIFEST_PATH = DATA_CACHE / "manifest.json"

SCHEMA = pa.schema([
    ("game_id", pa.int64()),
    ("season_id", pa.int64()),
    ("game_date", pa.date32()),
    ("game_type", pa.int32()),  # 1=preseason, 2=regular, 3=playoff, 4=all-star
    ("pre_1967", pa.bool_()),
    ("home", pa.string()),
    ("away", pa.string()),
    ("home_score", pa.int32()),
    ("away_score", pa.int32()),
    ("period_type", pa.string()),  # REG / OT / SO / null
    ("state", pa.string()),  # raw NHL game state (OFF / FINAL / FUT / ...)
])


# ---- Parsing -------------------------------------------------------------------


def _parse_game(raw: dict[str, Any], season_id: int) -> dict[str, Any] | None:
    """Map one NHL API game record to the Parquet row schema. Returns None on
    malformed records — defensive so one bad game never breaks a whole day.
    """
    try:
        gid = int(raw["id"])
        home = raw["homeTeam"]["abbrev"]
        away = raw["awayTeam"]["abbrev"]
    except (KeyError, TypeError, ValueError):
        return None
    try:
        gd = date.fromisoformat(raw.get("gameDate", ""))
    except ValueError:
        return None
    outcome = raw.get("gameOutcome") or {}
    return {
        "game_id": gid,
        "season_id": season_id,
        "game_date": gd,
        "game_type": int(raw.get("gameType", 0) or 0),
        "pre_1967": season_id < seasons.CUTOFF_PRE_1967,
        "home": home,
        "away": away,
        "home_score": _opt_int(raw["homeTeam"].get("score")),
        "away_score": _opt_int(raw["awayTeam"].get("score")),
        "period_type": outcome.get("lastPeriodType"),
        "state": raw.get("gameState") or "UNKNOWN",
    }


def _opt_int(x: Any) -> int | None:
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# ---- HTTP fetching -------------------------------------------------------------


async def _fetch_day(
    client: httpx.AsyncClient,
    day: date,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Fetch one day's scores, tolerating persistent server errors.

    Retries on any HTTP/timeout error. If the final attempt still fails with a
    4xx or 5xx status, treats the day as "no games" rather than aborting the
    whole season — the NHL API serves persistent 5xx for some specific dates
    (notably preseason days in older seasons) that are operationally identical
    to an empty day. Network/timeout failures that survive all retries still
    propagate, because those reflect real connectivity problems.
    """
    async with sem:
        last_status_err: httpx.HTTPStatusError | None = None
        for attempt in range(3):
            try:
                r = await client.get(f"{BASE}/score/{day.isoformat()}", timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                return r.json().get("games", []) or []
            except httpx.HTTPStatusError as exc:
                last_status_err = exc
                if attempt == 2:
                    code = exc.response.status_code
                    print(
                        f"  [warn] {day.isoformat()}: HTTP {code} after retries — "
                        f"treating as empty day",
                        file=sys.stderr,
                    )
                    return []
            except (httpx.HTTPError, httpx.TimeoutException):
                if attempt == 2:
                    raise
            await asyncio.sleep(0.4 * (attempt + 1))
        # Unreachable, but keeps the type checker happy
        if last_status_err is not None:
            return []
        return []


async def _fetch_season(
    client: httpx.AsyncClient,
    season_id: int,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    start, end = seasons.date_range(season_id, today=today)
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    sem = asyncio.Semaphore(CONCURRENCY)
    chunks = await asyncio.gather(*[_fetch_day(client, d, sem) for d in days])
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for chunk in chunks:
        for raw in chunk:
            row = _parse_game(raw, season_id)
            if row is None:
                continue
            if row["game_id"] in seen:
                continue  # rescheduled games can appear on multiple dates
            seen.add(row["game_id"])
            rows.append(row)
    rows.sort(key=lambda r: (r["game_date"], r["game_id"]))
    return rows


# ---- Parquet I/O ---------------------------------------------------------------


def _table_from_rows(rows: list[dict[str, Any]]) -> pa.Table:
    if not rows:
        return SCHEMA.empty_table()
    columns = {name: [] for name in SCHEMA.names}
    for r in rows:
        for name in SCHEMA.names:
            columns[name].append(r.get(name))
    arrays = [pa.array(columns[name], type=SCHEMA.field(name).type) for name in SCHEMA.names]
    return pa.Table.from_arrays(arrays, schema=SCHEMA)


def write_season(season_id: int, rows: list[dict[str, Any]]) -> Path:
    """Atomic write: tmp file + rename so partial writes never leave a corrupt
    parquet behind.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    final = RAW_DIR / f"{season_id}.parquet"
    tmp = final.with_suffix(".parquet.tmp")
    pq.write_table(_table_from_rows(rows), tmp, compression="zstd")
    os.replace(tmp, final)
    return final


def read_season(season_id: int) -> pa.Table:
    path = RAW_DIR / f"{season_id}.parquet"
    return pq.read_table(path)


def season_exists(season_id: int) -> bool:
    return (RAW_DIR / f"{season_id}.parquet").exists()


# ---- Manifest ------------------------------------------------------------------


@dataclass
class ManifestEntry:
    season_id: int
    rows: int
    pulled_at: str  # ISO timestamp


def load_manifest() -> dict[str, dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text())


def save_manifest(manifest: dict[str, dict[str, Any]]) -> None:
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(tmp, MANIFEST_PATH)


def _update_manifest(season_id: int, row_count: int) -> None:
    manifest = load_manifest()
    manifest[str(season_id)] = {
        "season_id": season_id,
        "rows": row_count,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
    }
    save_manifest(manifest)


# ---- High-level orchestration --------------------------------------------------


async def ingest_one(
    season_id: int,
    *,
    skip_existing: bool = False,
    force: bool = False,
    today: date | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[int, int]:
    """Returns (season_id, row_count). row_count is -1 if skipped."""
    if skip_existing and not force and season_exists(season_id):
        return season_id, -1
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient()
    try:
        rows = await _fetch_season(client, season_id, today=today)
        write_season(season_id, rows)
        _update_manifest(season_id, len(rows))
        return season_id, len(rows)
    finally:
        if owns_client:
            await client.aclose()


async def ingest_many(
    season_ids: Iterable[int],
    *,
    skip_existing: bool = False,
    force: bool = False,
    today: date | None = None,
) -> list[tuple[int, int]]:
    """Run seasons sequentially. Each season already parallelizes day-fetches
    internally; running seasons in parallel on top of that would exceed polite
    rate limits.
    """
    out: list[tuple[int, int]] = []
    async with httpx.AsyncClient() as client:
        for sid in season_ids:
            sid, n = await ingest_one(
                sid,
                skip_existing=skip_existing,
                force=force,
                today=today,
                client=client,
            )
            out.append((sid, n))
            tag = "skipped" if n < 0 else f"{n} games"
            print(f"  [{sid}] {tag}")
    return out


# ---- CLI -----------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="app.pipeline", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="Pull season(s) from the NHL API")
    sel = ingest.add_mutually_exclusive_group(required=True)
    sel.add_argument("--season", type=int, help="single season id, e.g. 20232024")
    sel.add_argument("--all", action="store_true", help="every known season")
    sel.add_argument("--since", type=int, help="every season >= this id")
    ingest.add_argument("--skip-existing", action="store_true",
                        help="don't re-pull seasons already on disk")
    ingest.add_argument("--force", action="store_true",
                        help="re-pull even if skip-existing would skip")
    ingest.add_argument("--offline-seasons", action="store_true",
                        help="use the hardcoded fallback season list instead of /v1/season")

    sub.add_parser("list", help="list ingested seasons (from the manifest)")
    sub.add_parser("status", help="manifest summary + on-disk parquet count")

    return p


async def _resolve_season_ids(args: argparse.Namespace) -> list[int]:
    if args.season:
        return [args.season]
    if args.offline_seasons:
        all_ids = seasons.known_season_ids()
    else:
        async with httpx.AsyncClient() as client:
            try:
                all_ids = await seasons.fetch_all_season_ids(client)
            except Exception:
                all_ids = seasons.known_season_ids()
    if args.all:
        return all_ids
    if args.since:
        return [s for s in all_ids if s >= args.since]
    return []


async def _cmd_ingest(args: argparse.Namespace) -> int:
    sids = await _resolve_season_ids(args)
    if not sids:
        print("no seasons selected", file=sys.stderr)
        return 1
    print(f"ingesting {len(sids)} season(s)…")
    results = await ingest_many(
        sids,
        skip_existing=args.skip_existing,
        force=args.force,
    )
    total = sum(n for _, n in results if n >= 0)
    skipped = sum(1 for _, n in results if n < 0)
    print(f"done. {total} game rows written across {len(results) - skipped} season(s); "
          f"{skipped} skipped.")
    return 0


def _cmd_list(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    if not manifest:
        print("(empty)")
        return 0
    for key in sorted(manifest, key=int):
        e = manifest[key]
        print(f"  {e['season_id']}  {e['rows']:>5} games  pulled {e['pulled_at']}")
    return 0


def _cmd_status(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    on_disk = sorted(int(p.stem) for p in RAW_DIR.glob("*.parquet")) if RAW_DIR.exists() else []
    in_manifest = sorted(int(k) for k in manifest)
    print(f"manifest entries: {len(in_manifest)}")
    print(f"parquet files on disk: {len(on_disk)}")
    only_manifest = set(in_manifest) - set(on_disk)
    only_disk = set(on_disk) - set(in_manifest)
    if only_manifest:
        print(f"  in manifest, missing parquet: {sorted(only_manifest)}")
    if only_disk:
        print(f"  parquet on disk, no manifest entry: {sorted(only_disk)}")
    total_rows = sum(e["rows"] for e in manifest.values())
    print(f"total game rows recorded in manifest: {total_rows}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "ingest":
        return asyncio.run(_cmd_ingest(args))
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "status":
        return _cmd_status(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
