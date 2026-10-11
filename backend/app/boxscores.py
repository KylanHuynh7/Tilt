"""NHL per-player box scores (shared by v3 roster moves and player projections).

METHODOLOGY.md §20 (DECISION V3-1) and methodology/NHL_PLAYERS.md §3. One row per
player per game: who dressed, for which team, plus TOI / goals / assists /
points / shots. Regular season + playoffs, 1967-68 through 2025-26 only;
2026-27 is the v3 test season and is never ingested here (§20 V3-5).

    uv run python -m app.boxscores ingest --all
    uv run python -m app.boxscores ingest --season 20102011
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from . import pipeline

BOX_DIR = pipeline.DATA_CACHE / "boxscores"
MANIFEST = BOX_DIR / "manifest.json"
FIRST_SEASON = 19671968
LAST_SEASON = 20252026            # v3 test (2026-27) is excluded by construction
CONCURRENCY = 8
MIN_SKATERS = 12                  # coverage rule per team per game (NHL_PLAYERS.md v0.2: genuine short benches exist)

SCHEMA = pa.schema([
    ("game_id", pa.int64()), ("season_id", pa.int64()), ("game_date", pa.date32()), ("game_type", pa.int8()),
    ("team", pa.string()), ("opponent", pa.string()), ("is_home", pa.bool_()),
    ("player_id", pa.int64()), ("name", pa.string()), ("pos", pa.string()),   # F / D / G
    ("toi_s", pa.int32()), ("goals", pa.int16()), ("assists", pa.int16()), ("points", pa.int16()),
    ("sog", pa.int16()),
])


def seasons() -> list[int]:
    return [s for s in sorted(int(k) for k in pipeline.load_manifest()) if FIRST_SEASON <= s <= LAST_SEASON]


def toi_seconds(v: Any) -> int | None:
    if not v or not isinstance(v, str) or ":" not in v:
        return None
    m, s = v.split(":")
    return int(m) * 60 + int(s)


def parse_box(box: dict, game: dict) -> tuple[list[dict], int]:
    """Rows for one game, and the smaller team's skater count (coverage check)."""
    stats = box.get("playerByGameStats") or {}
    rows, min_skaters = [], 99
    for side, team, opp, home in (("homeTeam", game["home"], game["away"], True),
                                  ("awayTeam", game["away"], game["home"], False)):
        t = stats.get(side) or {}
        skaters = [(p, "F") for p in t.get("forwards", [])] + [(p, "D") for p in t.get("defense", [])]
        min_skaters = min(min_skaters, len(skaters))
        for p, pos in skaters + [(g, "G") for g in t.get("goalies", [])]:
            name = p.get("name")
            rows.append({
                "game_id": game["game_id"], "season_id": game["season_id"], "game_date": game["game_date"],
                "game_type": game["game_type"], "team": team, "opponent": opp, "is_home": home,
                "player_id": int(p["playerId"]), "name": name.get("default") if isinstance(name, dict) else name,
                "pos": pos, "toi_s": toi_seconds(p.get("toi")), "goals": int(p.get("goals") or 0),
                "assists": int(p.get("assists") or 0),
                "points": int(p.get("points") or (int(p.get("goals") or 0) + int(p.get("assists") or 0))),
                "sog": int(p.get("sog") or 0) if pos != "G" else 0,
            })
    return rows, min_skaters


async def _fetch(client: httpx.AsyncClient, gid: int) -> dict:
    last = None
    for attempt in range(5):
        try:
            r = await client.get(f"{pipeline.BASE}/gamecenter/{gid}/boxscore", timeout=30)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"boxscore {gid} failed: {last!r}")


def _games(season: int) -> list[dict]:
    return [g for g in pipeline.read_season(season).to_pylist()
            if g["game_type"] in (2, 3) and g["state"] in ("OFF", "FINAL")]


async def ingest_season(season: int) -> dict:
    if season > LAST_SEASON:
        raise ValueError(f"{season} is after {LAST_SEASON}; the v3 test season is never ingested (§20 V3-5)")
    games = _games(season)
    path = BOX_DIR / f"{season}.parquet"
    rows = pq.read_table(path).to_pylist() if path.exists() else []
    m = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    prev = m.get(str(season), {})
    short = set(prev.get("short_game_ids", []))
    under_16 = set(prev.get("under_16_skater_game_ids", []))
    have = {r["game_id"] for r in rows}
    todo = [g for g in games if g["game_id"] not in have and g["game_id"] not in short]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, g):
        async with sem:
            box = await _fetch(client, g["game_id"])
        out, n = parse_box(box, g)
        if n < 16:
            under_16.add(g["game_id"])
        if n < MIN_SKATERS:
            short.add(g["game_id"])
            return []
        return out

    async with httpx.AsyncClient(headers={"User-Agent": "tilt-boxscores"}) as client:
        for start in range(0, len(todo), 400):
            for part in await asyncio.gather(*[one(client, g) for g in todo[start:start + 400]]):
                rows.extend(part)
            BOX_DIR.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")
    kept = len({r["game_id"] for r in rows})
    m = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    m[str(season)] = {"games": len(games), "kept": kept, "short_game_ids": sorted(short),
                      "under_16_skater_game_ids": sorted(under_16),
                      "rows": len(rows), "covered": kept == len(games) and not short}
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))
    return {"season": season, **m[str(season)]}


def read_season(season: int) -> list[dict]:
    if season > LAST_SEASON:
        raise ValueError(f"{season} is after {LAST_SEASON}")
    return pq.read_table(BOX_DIR / f"{season}.parquet").to_pylist()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.boxscores")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--all", action="store_true")
    a = p.parse_args(argv)
    for s in ([a.season] if a.season else seasons()):
        r = asyncio.run(ingest_season(s))
        print(f"  [{s}] {r['kept']}/{r['games']} games · short {len(r['short_game_ids'])} · "
              f"{r['rows']} rows · covered {r['covered']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
