"""NFL play-by-play → per-play game states (methodology/NFL.md §12, v1.1).

nflverse `play_by_play_{season}.parquet` files are downloaded to a scratch
directory (not committed). Only the §12 v1.1 columns are read, by column
projection, so model outputs in those files (wp, vegas_wp, ep, epa, …) are
never loaded. Each game is kept only if its last play's running score
matches the games.csv final. The compact samples are committed.

    uv run python -m app.nfl.pbp ingest --raw-dir /path/to/scratch --train
    uv run python -m app.nfl.pbp ingest --raw-dir /path/to/scratch --test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from . import pipeline
from .teams import franchise

URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"
PBP_DIR = pipeline.DATA_DIR / "pbp"
MANIFEST_PATH = PBP_DIR / "manifest.json"
TRAIN_SEASONS = list(range(2004, 2015))
TEST_SEASONS = [2022, 2023, 2024, 2025]

READ_COLUMNS = ["game_id", "home_team", "posteam", "qtr", "quarter_seconds_remaining",
                "down", "yardline_100", "total_home_score", "total_away_score"]

SCHEMA = pa.schema([
    ("game_id", pa.string()), ("qtr", pa.int8()), ("qsr", pa.int16()),
    ("home_poss", pa.int8()),          # +1 home has the ball, −1 away
    ("yardline_100", pa.int8()), ("home_score", pa.int16()), ("away_score", pa.int16()),
])


def download(season: int, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"play_by_play_{season}.parquet"
    if not dest.exists():
        with httpx.stream("GET", URL.format(season=season), follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    return dest


def extract(path: Path, finals: dict[str, tuple[int, int]]) -> tuple[list[dict], dict]:
    t = pq.read_table(path, columns=READ_COLUMNS)  # projection: nothing else is read
    rows = t.to_pylist()
    by_game: dict[str, list[dict]] = {}
    for r in rows:
        by_game.setdefault(r["game_id"], []).append(r)
    out, dropped = [], {"not_in_games_csv": 0, "final_mismatch": 0}
    for gid, plays in by_game.items():
        if gid not in finals:
            dropped["not_in_games_csv"] += 1
            continue
        last = plays[-1]
        if (last["total_home_score"], last["total_away_score"]) != finals[gid]:
            dropped["final_mismatch"] += 1
            continue
        for p in plays:
            if p["posteam"] is None or p["down"] is None or p["qtr"] is None or p["yardline_100"] is None:
                continue
            out.append({
                "game_id": gid, "qtr": int(p["qtr"]), "qsr": int(p["quarter_seconds_remaining"] or 0),
                "home_poss": 1 if p["posteam"] == p["home_team"] else -1,
                "yardline_100": int(p["yardline_100"]),
                "home_score": int(p["total_home_score"]), "away_score": int(p["total_away_score"]),
            })
    return out, {"games": len(by_game), "kept": len({r["game_id"] for r in out}), **dropped}


def ingest(season: int, raw_dir: Path) -> dict:
    finals = {r["game_id"]: (r["home_score"], r["away_score"]) for r in pipeline.read_games()
              if r["season"] == season and r["home_score"] is not None
              and franchise(r["home_team"]) and franchise(r["away_team"])}
    rows, stats = extract(download(season, raw_dir), finals)
    PBP_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), PBP_DIR / f"{season}.parquet", compression="zstd")
    manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
    manifest[str(season)] = {**stats, "samples": len(rows)}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return {"season": season, **stats, "samples": len(rows)}


def read_season(season: int) -> list[dict]:
    return pq.read_table(PBP_DIR / f"{season}.parquet").to_pylist()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.nfl.pbp")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    ing.add_argument("--raw-dir", type=Path, required=True)
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--train", action="store_true")
    g.add_argument("--test", action="store_true")
    a = p.parse_args(argv)
    ids = [a.season] if a.season else (TRAIN_SEASONS if a.train else TEST_SEASONS)
    for s in ids:
        r = ingest(s, a.raw_dir)
        print(f"  [{s}] kept {r['kept']}/{r['games']} games · mismatch {r['final_mismatch']} · "
              f"not in games.csv {r['not_in_games_csv']} · {r['samples']} samples", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
