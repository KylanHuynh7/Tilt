"""MLB ingest (methodology/MLB.md §3).

Two caches per season, both committed:
  data_cache/mlb/games/{season}.parquet     one row per game (schedule + result + probables)
  data_cache/mlb/starters/{season}.parquet  starting pitchers' lines from boxscores

Only identity, result, venue, status and probable-pitcher fields are read.
Suspended-and-resumed games appear on two schedule dates under one gamePk;
they collapse to the final row. Coverage is checked per season (§3).

    uv run python -m app.mlb.pipeline ingest --season 2024
    uv run python -m app.mlb.pipeline ingest --all            # 2000 → current
    uv run python -m app.mlb.pipeline status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from .teams import is_franchise

API = "https://statsapi.mlb.com/api/v1"
DATA_DIR = Path(__file__).resolve().parents[2] / "data_cache" / "mlb"
GAMES_DIR, STARTERS_DIR = DATA_DIR / "games", DATA_DIR / "starters"
MANIFEST_PATH = DATA_DIR / "manifest.json"
FIRST_SEASON = 2000
GAME_TYPES = "R,F,D,L,W"          # regular, wild card, division, LCS, World Series
PLAYOFF_TYPES = ("F", "D", "L", "W")
CONCURRENCY = 10
NEUTRAL_MAX_HOME_GAMES = 5        # §3: a venue where the home team hosted < 5 games that season

GAME_SCHEMA = pa.schema([
    ("game_pk", pa.int64()), ("season", pa.int16()), ("game_type", pa.string()),
    ("game_date", pa.date32()), ("home_id", pa.int32()), ("away_id", pa.int32()),
    ("home_abbr", pa.string()), ("away_abbr", pa.string()),
    ("home_score", pa.int16()), ("away_score", pa.int16()), ("is_final", pa.bool_()),
    ("is_tie", pa.bool_()), ("venue_id", pa.int32()), ("neutral", pa.bool_()),
    ("home_probable_id", pa.int32()), ("away_probable_id", pa.int32()),
])
STARTER_SCHEMA = pa.schema([
    ("game_pk", pa.int64()), ("side", pa.string()), ("pitcher_id", pa.int32()),
    ("outs", pa.int16()), ("k", pa.int16()), ("bb", pa.int16()), ("h", pa.int16()),
    ("r", pa.int16()), ("hr", pa.int16()),
])


def _final(status: dict) -> bool:
    return status.get("codedGameState") == "F" or status.get("detailedState") in ("Final", "Completed Early", "Game Over")


def parse_schedule(payload: dict, abbrs: dict[int, str]) -> list[dict]:
    by_pk: dict[int, dict] = {}
    for day in payload.get("dates", []):
        for g in day["games"]:
            t = g["teams"]
            h, a = t["home"], t["away"]
            row = {
                "game_pk": int(g["gamePk"]), "season": int(g["season"]), "game_type": g["gameType"],
                "game_date": date.fromisoformat(g["officialDate"]),
                "home_id": int(h["team"]["id"]), "away_id": int(a["team"]["id"]),
                "home_abbr": abbrs.get(int(h["team"]["id"])), "away_abbr": abbrs.get(int(a["team"]["id"])),
                "home_score": h.get("score"), "away_score": a.get("score"),
                "is_final": _final(g["status"]), "is_tie": bool(g.get("isTie")),
                "venue_id": (g.get("venue") or {}).get("id"), "neutral": False,
                "home_probable_id": (h.get("probablePitcher") or {}).get("id"),
                "away_probable_id": (a.get("probablePitcher") or {}).get("id"),
            }
            prev = by_pk.get(row["game_pk"])
            if prev is None or (row["is_final"] and not prev["is_final"]) or (row["is_final"] and row["game_date"] > prev["game_date"]):
                by_pk[row["game_pk"]] = row      # suspended games: keep the final occurrence
    rows = sorted(by_pk.values(), key=lambda r: (r["game_date"], r["game_pk"]))
    hosted = Counter((r["home_id"], r["venue_id"]) for r in rows)
    for r in rows:
        r["neutral"] = hosted[(r["home_id"], r["venue_id"])] < NEUTRAL_MAX_HOME_GAMES
    return rows


def scheduled_regular_games(season: int) -> int:
    return {2020: 900}.get(season, 2430)


def is_valid_result(r: dict) -> bool:
    """methodology/MLB.md v1.1 validity rule: a game counts only if it is
    final AND carries both scores. The API lists some games as final with no
    score (35 in 2000). Same-day same-teams pairs are NOT deduplicated:
    in MLB those are real doubleheaders.
    """
    return bool(r["is_final"]) and r["home_score"] is not None and r["away_score"] is not None


def coverage(season: int, rows: list[dict]) -> dict:
    played = sum(1 for r in rows if r["game_type"] == "R" and is_valid_result(r)
                 and is_franchise(r["home_id"]) and is_franchise(r["away_id"]))
    scoreless_finals = sum(1 for r in rows if r["is_final"] and not is_valid_result(r))
    expected = scheduled_regular_games(season)
    return {"regular_final": played, "scheduled": expected, "ratio": round(played / expected, 4),
            "passes": abs(played / expected - 1) <= 0.01, "dropped_scoreless_finals": scoreless_finals}


def recheck() -> None:
    m = load_manifest()
    for key in list(m):
        m[key]["coverage"] = coverage(int(key), read_games(int(key)))
    MANIFEST_PATH.write_text(json.dumps(m, indent=2, sort_keys=True))


async def _get(client: httpx.AsyncClient, url: str, **params) -> dict:
    last = None
    for attempt in range(4):
        try:
            r = await client.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"MLB API failed: {url} {params}: {last!r}")


def parse_starters(game_pk: int, box: dict) -> list[dict]:
    out = []
    for side in ("home", "away"):
        team = box["teams"][side]
        if not team.get("pitchers"):
            continue
        pid = team["pitchers"][0]
        st = team["players"][f"ID{pid}"]["stats"]["pitching"]
        out.append({"game_pk": game_pk, "side": side, "pitcher_id": pid,
                    "outs": st.get("outs", 0), "k": st.get("strikeOuts", 0), "bb": st.get("baseOnBalls", 0),
                    "h": st.get("hits", 0), "r": st.get("runs", 0), "hr": st.get("homeRuns", 0)})
    return out


def _write(table_rows: list[dict], schema: pa.Schema, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(table_rows, schema=schema), tmp, compression="zstd")
    os.replace(tmp, path)


async def ingest_season(season: int, *, with_starters: bool = True) -> dict:
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-mlb (non-commercial)"}) as client:
        teams = await _get(client, f"{API}/teams", sportId=1, season=season)
        abbrs = {int(t["id"]): t["abbreviation"] for t in teams["teams"]}
        sched = await _get(client, f"{API}/schedule", sportId=1, season=season,
                           gameType=GAME_TYPES, hydrate="probablePitcher")
        rows = parse_schedule(sched, abbrs)
        _write(rows, GAME_SCHEMA, GAMES_DIR / f"{season}.parquet")

        starters: list[dict] = []
        if with_starters:
            done = [r for r in rows if is_valid_result(r) and is_franchise(r["home_id"]) and is_franchise(r["away_id"])]
            existing = {}
            path = STARTERS_DIR / f"{season}.parquet"
            if path.exists():
                for s in pq.read_table(path).to_pylist():
                    existing.setdefault(s["game_pk"], []).append(s)
            sem = asyncio.Semaphore(CONCURRENCY)

            async def one(pk: int) -> list[dict]:
                if pk in existing:
                    return existing[pk]
                async with sem:
                    box = await _get(client, f"{API}/game/{pk}/boxscore")
                return parse_starters(pk, box)

            for chunk in await asyncio.gather(*[one(r["game_pk"]) for r in done]):
                starters.extend(chunk)
            _write(starters, STARTER_SCHEMA, path)

    entry = {"rows": len(rows), "starter_lines": len(starters),
             "pulled_at": datetime.now(timezone.utc).isoformat(), "coverage": coverage(season, rows),
             "neutral_games": sum(r["neutral"] for r in rows)}
    m = load_manifest()
    m[str(season)] = entry
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(m, indent=2, sort_keys=True))
    return {"season": season, **entry}


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}


def read_games(season: int) -> list[dict]:
    return pq.read_table(GAMES_DIR / f"{season}.parquet").to_pylist()


def read_starters(season: int) -> list[dict]:
    p = STARTERS_DIR / f"{season}.parquet"
    return pq.read_table(p).to_pylist() if p.exists() else []


def current_season(today: date | None = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 3 else today.year - 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.mlb.pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--all", action="store_true")
    sub.add_parser("status")
    sub.add_parser("recheck")
    a = p.parse_args(argv)
    if a.cmd == "recheck":
        recheck()
    if a.cmd == "ingest":
        seasons = [a.season] if a.season else list(range(FIRST_SEASON, current_season() + 1))
        for s in seasons:
            r = asyncio.run(ingest_season(s))
            c = r["coverage"]
            print(f"  [{s}] {r['rows']} games · regular {c['regular_final']}/{c['scheduled']} "
                  f"({'PASS' if c['passes'] else 'FAIL'}) · starters {r['starter_lines']} · neutral {r['neutral_games']}", flush=True)
        return 0
    for s, e in sorted(load_manifest().items()):
        c = e["coverage"]
        print(f"  [{s}] regular {c['regular_final']}/{c['scheduled']} {'PASS' if c['passes'] else 'FAIL'} · starters {e['starter_lines']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
