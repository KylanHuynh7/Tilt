"""NBA ingest: ESPN scoreboard → one Parquet per season (methodology/NBA.md §3).

Idempotent and atomic, mirroring the NHL pipeline. A season is fetched day by
day over a window wide enough to hold any season (Sep 1 of the start year to
Oct 31 of the end year — the 2019-20 bubble ran into October 2020), and events
are kept only if ESPN labels them with that season. That stops a neighbouring
season's preseason from leaking in.

Every ingest records a coverage check in the manifest: completed regular-season
games vs the scheduled count. Per §3, a season enters the model only if the
two agree within 1%.

CLI:
    uv run python -m app.nba.pipeline ingest --season 20242025
    uv run python -m app.nba.pipeline ingest --all [--skip-existing]
    uv run python -m app.nba.pipeline status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from . import espn

DATA_DIR = Path(__file__).resolve().parents[2] / "data_cache" / "nba"
RAW_DIR = DATA_DIR / "raw"
MANIFEST_PATH = DATA_DIR / "manifest.json"

FIRST_SEASON = 19931994  # DECISION 1
CONCURRENCY = 12
COVERAGE_TOLERANCE = 0.01  # §3: within 1% of schedule

REGULAR, PLAYOFF, PLAY_IN = 2, 3, 5

SCHEMA = pa.schema([
    ("game_id", pa.int64()),
    ("season_id", pa.int64()),
    ("game_date", pa.date32()),
    ("season_type", pa.int8()),
    ("home_team_id", pa.int32()),
    ("away_team_id", pa.int32()),
    ("home_abbr", pa.string()),
    ("away_abbr", pa.string()),
    ("home_score", pa.int16()),
    ("away_score", pa.int16()),
    ("n_periods", pa.int8()),
    ("completed", pa.bool_()),
    ("status", pa.string()),
    ("espn_neutral", pa.bool_()),
    ("venue_city", pa.string()),
])


# ---- Schedule (for the §3 coverage rule) --------------------------------------

# Seasons whose official game count isn't teams × 82 / 2.
_SCHEDULE_OVERRIDES = {
    19981999: 725,   # lockout: 29 teams × 50 / 2
    20112012: 990,   # lockout: 30 × 66 / 2
    20192020: 1059,  # 971 pre-suspension + 88 bubble seeding games
    20202021: 1080,  # 30 × 72 / 2
}


def n_teams(season_id: int) -> int:
    start = season_id // 10000
    if start < 1995:
        return 27
    if start < 2004:
        return 29
    return 30


def scheduled_regular_games(season_id: int) -> int:
    if season_id in _SCHEDULE_OVERRIDES:
        return _SCHEDULE_OVERRIDES[season_id]
    return n_teams(season_id) * 82 // 2


def _has_valid_score(r: dict) -> bool:
    return (r["home_score"] or 0) + (r["away_score"] or 0) > 0


def clean_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """Systematic data-validity rules (methodology/NBA.md v1.1 clarification).

    1. A completed game scored 0-0 is not a real NBA result (ESPN carries
       phantom 0-0 "finals" — 76 in 1999-2000) and is dropped.
    2. Two NBA teams never meet twice on one date, so rows sharing
       (date, home, away) are one game listed twice (e.g. DAL-PHI on
       2003-01-04 under two ESPN ids). Keep one: a valid score first, then
       the lowest (original) ESPN id.

    Raw parquets are left untouched; this runs on read. Returns the cleaned
    rows and drop counts for the manifest audit trail.
    """
    zero_zero = [r for r in rows if r["completed"] and not _has_valid_score(r)]
    kept = [r for r in rows if not (r["completed"] and not _has_valid_score(r))]
    by_key: dict[tuple, dict] = {}
    duplicates = 0
    for r in sorted(kept, key=lambda r: r["game_id"]):
        k = (r["game_date"], r["home_team_id"], r["away_team_id"])
        if k in by_key:
            duplicates += 1
            prev = by_key[k]
            if not prev["completed"] and r["completed"]:
                by_key[k] = r
            continue
        by_key[k] = r
    out = sorted(by_key.values(), key=lambda r: (r["game_date"], r["game_id"]))
    return out, {"dropped_zero_zero": len(zero_zero), "dropped_duplicates": duplicates}


def coverage(season_id: int, rows: list[dict]) -> dict:
    """Completed regular-season NBA-vs-NBA games (after `clean_rows`) against
    the schedule.
    """
    from .teams import is_franchise

    cleaned, drops = clean_rows(rows)
    played = sum(
        1 for r in cleaned
        if r["season_type"] == REGULAR and r["completed"]
        and is_franchise(r["home_team_id"]) and is_franchise(r["away_team_id"])
    )
    expected = scheduled_regular_games(season_id)
    ratio = played / expected
    return {
        "regular_games": played,
        "scheduled": expected,
        "ratio": round(ratio, 4),
        "passes": abs(ratio - 1.0) <= COVERAGE_TOLERANCE,
        **drops,
    }


# ---- Fetch ---------------------------------------------------------------------

def season_window(season_id: int) -> list[date]:
    start = season_id // 10000
    d0, d1 = date(start, 9, 1), date(start + 1, 10, 31)
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


async def fetch_season(season_id: int, *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    days = [d for d in season_window(season_id) if d <= today]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client: httpx.AsyncClient, d: date) -> list[dict]:
        async with sem:
            return await espn.fetch_day(client, d)

    async with httpx.AsyncClient(headers={"User-Agent": "tilt-nba-ingest"}) as client:
        per_day = await asyncio.gather(*[one(client, d) for d in days])

    by_id: dict[int, dict] = {}
    for rows in per_day:
        for r in rows:
            if r["season_id"] == season_id:
                by_id[r["game_id"]] = r  # later days win (rescheduled games)
    return sorted(by_id.values(), key=lambda r: (r["game_date"], r["game_id"]))


# ---- Storage -------------------------------------------------------------------

def write_season(season_id: int, rows: list[dict]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    final = RAW_DIR / f"{season_id}.parquet"
    tmp = final.with_suffix(".parquet.tmp")
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, final)
    return final


def read_season(season_id: int) -> list[dict]:
    rows = pq.read_table(RAW_DIR / f"{season_id}.parquet").to_pylist()
    rows.sort(key=lambda r: (r["game_date"], r["game_id"]))
    return rows


def ingested_seasons() -> list[int]:
    return sorted(int(p.stem) for p in RAW_DIR.glob("*.parquet"))


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}


def _save_manifest(manifest: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(tmp, MANIFEST_PATH)


def current_season_id(today: date | None = None) -> int:
    """NBA seasons tip off in October; from August on, the upcoming season."""
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return start * 10000 + start + 1


async def ingest_one(season_id: int, *, skip_existing: bool = False) -> dict:
    if skip_existing and (RAW_DIR / f"{season_id}.parquet").exists():
        return {"season_id": season_id, "skipped": True}
    rows = await fetch_season(season_id)
    write_season(season_id, rows)
    entry = {
        "rows": len(rows),
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "in_progress": season_id >= current_season_id(),
        "coverage": coverage(season_id, rows),
    }
    manifest = load_manifest()
    manifest[str(season_id)] = entry
    _save_manifest(manifest)
    return {"season_id": season_id, **entry}


def recheck_coverage() -> None:
    """Recompute every manifest coverage entry from the parquets on disk."""
    manifest = load_manifest()
    for sid in ingested_seasons():
        entry = manifest.setdefault(str(sid), {})
        entry["coverage"] = coverage(sid, read_season(sid))
    _save_manifest(manifest)


VALIDATION_START = 20182019  # methodology/NBA.md §4


def first_model_season(manifest: dict | None = None) -> int:
    """§3 / DECISION 1: the warm-up starts at FIRST_SEASON unless a season
    before validation fails the coverage rule, in which case it restarts at
    the first season after the last failure (no bridging gaps).
    """
    manifest = load_manifest() if manifest is None else manifest
    first = FIRST_SEASON
    for key in sorted(manifest):
        sid = int(key)
        if sid >= VALIDATION_START:
            break
        cov = manifest[key].get("coverage", {})
        if not cov.get("passes", False):
            start = sid // 10000 + 1
            first = start * 10000 + start + 1
    return first


def all_season_ids(today: date | None = None) -> list[int]:
    last = current_season_id(today) // 10000
    return [y * 10000 + y + 1 for y in range(FIRST_SEASON // 10000, last + 1)]


# ---- CLI -----------------------------------------------------------------------

def _fmt(r: dict) -> str:
    if r.get("skipped"):
        return f"  [{r['season_id']}] skipped"
    c = r["coverage"]
    flag = "in-progress" if r["in_progress"] else ("PASS" if c["passes"] else "FAIL")
    return (f"  [{r['season_id']}] {r['rows']} rows · regular {c['regular_games']}"
            f"/{c['scheduled']} ({c['ratio']:.3f}) coverage {flag}"
            f" · dropped 0-0 {c.get('dropped_zero_zero', 0)}, dup {c.get('dropped_duplicates', 0)}")


async def _ingest(ids: list[int], skip_existing: bool) -> None:
    for sid in ids:  # sequential per season; each season is concurrent per day
        print(_fmt(await ingest_one(sid, skip_existing=skip_existing)), flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.nba.pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--all", action="store_true")
    ing.add_argument("--skip-existing", action="store_true")
    sub.add_parser("status")
    sub.add_parser("recheck", help="recompute coverage from parquets on disk")
    args = p.parse_args(argv)

    if args.cmd == "recheck":
        recheck_coverage()
        args.cmd = "status"

    if args.cmd == "ingest":
        ids = all_season_ids() if args.all else [args.season]
        asyncio.run(_ingest(ids, args.skip_existing))
        return 0

    manifest = load_manifest()
    for sid in ingested_seasons():
        e = manifest.get(str(sid), {})
        if e:
            print(_fmt({"season_id": sid, **e}))
        else:
            print(f"  [{sid}] no manifest entry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
