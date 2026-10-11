"""NFL ingest: nflverse games.csv → a single Parquet of permitted columns
(methodology/NFL.md §3).

Only the columns §3 allows are kept, so betting lines (`spread_line`,
moneylines, totals, odds) never enter the repository. Each season's
regular-season count is checked against the schedule (§3 coverage rule).

    uv run python -m app.nfl.pipeline ingest
    uv run python -m app.nfl.pipeline status
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
DATA_DIR = Path(__file__).resolve().parents[2] / "data_cache" / "nfl"
GAMES_PATH = DATA_DIR / "games.parquet"
MANIFEST_PATH = DATA_DIR / "manifest.json"

FIRST_SEASON = 1999
PLAYOFF_TYPES = ("WC", "DIV", "CON", "SB")
COVERAGE_TOLERANCE_GAMES = 1  # §3: within one game of schedule

# §3 permitted columns. Everything else in games.csv is dropped on ingest.
ALLOWED = ["game_id", "season", "game_type", "week", "gameday", "home_team", "away_team",
           "home_score", "away_score", "location", "overtime"]
FORBIDDEN = {"spread_line", "total_line", "home_moneyline", "away_moneyline",
             "home_spread_odds", "away_spread_odds", "under_odds", "over_odds"}

SCHEMA = pa.schema([
    ("game_id", pa.string()), ("season", pa.int16()), ("game_type", pa.string()),
    ("week", pa.int8()), ("gameday", pa.date32()), ("home_team", pa.string()),
    ("away_team", pa.string()), ("home_score", pa.int16()), ("away_score", pa.int16()),
    ("location", pa.string()), ("overtime", pa.bool_()),
])


def _int(v: str) -> int | None:
    return int(float(v)) if v not in ("", "NA", None) else None


def parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    missing = set(ALLOWED) - set(reader.fieldnames or [])
    if missing:
        raise RuntimeError(f"nflverse games.csv is missing columns {sorted(missing)}")
    rows = []
    for r in reader:
        rows.append({
            "game_id": r["game_id"], "season": int(r["season"]), "game_type": r["game_type"],
            "week": int(r["week"]), "gameday": date.fromisoformat(r["gameday"]),
            "home_team": r["home_team"], "away_team": r["away_team"],
            "home_score": _int(r["home_score"]), "away_score": _int(r["away_score"]),
            "location": r["location"], "overtime": _int(r["overtime"]) == 1,
        })
    return rows


def scheduled_regular_games(season: int) -> int:
    teams = 31 if season < 2002 else 32
    games = 16 if season < 2021 else 17
    return teams * games // 2


def coverage(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for season in sorted({r["season"] for r in rows}):
        reg = [r for r in rows if r["season"] == season and r["game_type"] == "REG"]
        played = sum(1 for r in reg if r["home_score"] is not None)
        expected = scheduled_regular_games(season)
        out[str(season)] = {
            "regular_scheduled_rows": len(reg),
            "regular_played": played,
            "scheduled": expected,
            "complete": played >= expected - COVERAGE_TOLERANCE_GAMES,
            "passes": abs(len(reg) - expected) <= COVERAGE_TOLERANCE_GAMES,
        }
    return out


def ingest() -> dict:
    r = httpx.get(GAMES_URL, follow_redirects=True, timeout=60)
    r.raise_for_status()
    rows = parse_csv(r.text)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = GAMES_PATH.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), tmp, compression="zstd")
    os.replace(tmp, GAMES_PATH)
    manifest = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "source": GAMES_URL,
        "rows": len(rows),
        "columns_kept": ALLOWED,
        "coverage": coverage(rows),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def read_games() -> list[dict]:
    rows = pq.read_table(GAMES_PATH).to_pylist()
    rows.sort(key=lambda r: (r["gameday"], r["game_id"]))
    return rows


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}


def main(argv: list[str] | None = None) -> int:
    cmd = (argv or sys.argv[1:] or ["status"])[0]
    m = ingest() if cmd == "ingest" else load_manifest()
    for s, c in m.get("coverage", {}).items():
        flag = "PASS" if c["passes"] else "FAIL"
        print(f"  [{s}] regular rows {c['regular_scheduled_rows']}/{c['scheduled']} · "
              f"played {c['regular_played']} · coverage {flag}{'' if c['complete'] else ' · in progress'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
