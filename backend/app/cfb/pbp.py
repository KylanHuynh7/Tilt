"""College football play-by-play → per-play states (methodology/CFB.md §12, v1.3).

Reads ONLY v1.3 fields from ESPN `summary` → drives.previous[].plays[]
(period, clock, scores, start.down, start.yardsToEndzone, start.team.id). The
payload's winprobability / odds / pickcenter blocks are never read (§10).
FBS-vs-FBS games only. Resumable: games already stored are skipped.

    uv run python -m app.cfb.pbp ingest --train    # 2004–2013
    uv run python -m app.cfb.pbp ingest --test     # 2022–2025 (one-shot evaluator only)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from . import pipeline

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
PBP_DIR = pipeline.DATA_DIR / "pbp"
MANIFEST = PBP_DIR / "manifest.json"
TRAIN_SEASONS = list(range(2004, 2014))
TEST_SEASONS = [2022, 2023, 2024, 2025]
CONCURRENCY = 12

SCHEMA = pa.schema([
    ("game_id", pa.int64()), ("qtr", pa.int8()), ("clock_s", pa.int16()), ("home_poss", pa.int8()),
    ("yards_to_ez", pa.int8()), ("home_score", pa.int16()), ("away_score", pa.int16()),
])


def parse_clock(display: str | None) -> int:
    if not display:
        return 0
    if ":" in display:
        m, s = display.split(":")
        return int(m) * 60 + int(float(s))
    return int(float(display))


def samples_from_plays(plays: list[dict], home_id: str, away_id: str) -> tuple[list[dict], int]:
    """(valid samples, total plays) under the v1.3 checks."""
    out = []
    for p in plays:
        st = p.get("start") or {}
        down, y = st.get("down"), st.get("yardsToEndzone")
        team = str((st.get("team") or {}).get("id") or "")
        if not (isinstance(down, int) and 1 <= down <= 4 and isinstance(y, int) and 1 <= y <= 99):
            continue
        if team not in (home_id, away_id):
            continue
        out.append({"qtr": int((p.get("period") or {}).get("number") or 1),
                    "clock_s": parse_clock((p.get("clock") or {}).get("displayValue")),
                    "home_poss": 1 if team == home_id else -1, "yards_to_ez": y,
                    "home_score": int(p.get("homeScore") or 0), "away_score": int(p.get("awayScore") or 0)})
    return out, len(plays)


async def _fetch(client, gid: int) -> list[dict]:
    last = None
    for attempt in range(4):
        try:
            r = await client.get(SUMMARY, params={"event": gid}, timeout=60)
            r.raise_for_status()
            drives = (r.json().get("drives") or {}).get("previous") or []   # only `drives` is read
            return [pl for d in drives for pl in (d.get("plays") or [])]
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"ESPN summary {gid} failed: {last!r}")


async def ingest_season(season: int) -> dict:
    rows_all = pipeline.read_games(season)
    fbs = pipeline.fbs_teams(season, rows_all)
    games = [g for g in pipeline.completed_games(rows_all) if g["home_id"] in fbs and g["away_id"] in fbs]
    path = PBP_DIR / f"{season}.parquet"
    rows = pq.read_table(path).to_pylist() if path.exists() else []
    have = {r["game_id"] for r in rows}
    todo = [g for g in games if g["game_id"] not in have]
    stats = {"no_plays": 0, "final_mismatch": 0, "too_few_valid": 0}
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, g):
        async with sem:
            plays = await _fetch(client, g["game_id"])
        if not plays:
            stats["no_plays"] += 1
            return []
        last = plays[-1]
        if (int(last.get("homeScore") or -1), int(last.get("awayScore") or -1)) != (g["home_score"], g["away_score"]):
            stats["final_mismatch"] += 1
            return []
        samples, total = samples_from_plays(plays, str(g["home_id"]), str(g["away_id"]))
        if len(samples) < 0.5 * total:
            stats["too_few_valid"] += 1
            return []
        return [{"game_id": g["game_id"], **s} for s in samples]

    async with httpx.AsyncClient(headers={"User-Agent": "tilt-cfb"}) as client:
        for start in range(0, len(todo), 300):
            for part in await asyncio.gather(*[one(client, g) for g in todo[start:start + 300]]):
                rows.extend(part)
            PBP_DIR.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")
    m = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    prev = m.get(str(season), {})
    m[str(season)] = {"fbs_vs_fbs_games": len(games), "kept": len({r["game_id"] for r in rows}), "plays": len(rows),
                      **{k: prev.get(k, 0) + v for k, v in stats.items()}}
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))
    return {"season": season, **m[str(season)]}


def read_season(season: int) -> list[dict]:
    return pq.read_table(PBP_DIR / f"{season}.parquet").to_pylist()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.cfb.pbp")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--train", action="store_true")
    g.add_argument("--test", action="store_true")
    a = p.parse_args(argv)
    for s in ([a.season] if a.season else TRAIN_SEASONS if a.train else TEST_SEASONS):
        r = asyncio.run(ingest_season(s))
        print(f"  [{s}] kept {r['kept']}/{r['fbs_vs_fbs_games']} · mismatch {r['final_mismatch']} · too few valid "
              f"{r['too_few_valid']} · no plays {r['no_plays']} · {r['plays']} plays", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
