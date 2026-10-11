"""College football ingest (methodology/CFB.md §3).

One parquet per season of every game involving an FBS team (ESPN group 80):
weeks 1–16 of the regular season plus the postseason. ESPN's per-season
group-80 team list is stored alongside for the FBS-membership rule. Only
identity, score, status, week, neutral and conference-game fields are read;
odds / FPI / predictor fields never are (§10).

    uv run python -m app.cfb.pipeline ingest --all     # 2001 → current
    uv run python -m app.cfb.pipeline status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
FBS_TEAMS = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/{y}/types/2/groups/80/teams"
DATA_DIR = Path(__file__).resolve().parents[2] / "data_cache" / "cfb"
GAMES_DIR = DATA_DIR / "games"
MANIFEST_PATH = DATA_DIR / "manifest.json"
FIRST_SEASON = 2001
REGULAR_WEEKS = range(1, 18)   # through week 17 (late Hawai'i / Army–Navy games)

SCHEMA = pa.schema([
    ("game_id", pa.int64()), ("season", pa.int16()), ("season_type", pa.int8()), ("week", pa.int8()),
    ("game_date", pa.string()), ("home_id", pa.int32()), ("away_id", pa.int32()),
    ("home_abbr", pa.string()), ("away_abbr", pa.string()), ("home_name", pa.string()), ("away_name", pa.string()),
    ("home_score", pa.int16()), ("away_score", pa.int16()), ("completed", pa.bool_()),
    ("neutral", pa.bool_()), ("conference_game", pa.bool_()),
])


class SchemaError(RuntimeError):
    pass


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_event(e: dict, season_type: int, week: int) -> dict:
    try:
        c = e["competitions"][0]
        sides = {x["homeAway"]: x for x in c["competitors"]}
        h, a = sides["home"], sides["away"]
        # Season type and week come from the EVENT, not the query: for
        # pre-2024 seasons ESPN's `seasontype=3` query also returns ~390
        # regular-season games, so query-based labels were wrong.
        ev_type = int((e.get("season") or {}).get("type") or season_type)
        ev_week = int((e.get("week") or {}).get("number") or week)
        return {
            "game_id": int(e["id"]), "season": int(e["season"]["year"]), "season_type": ev_type,
            "week": ev_week if ev_type == 2 else 0, "game_date": (e.get("date") or "")[:10],
            "home_id": int(h["team"]["id"]), "away_id": int(a["team"]["id"]),
            "home_abbr": h["team"].get("abbreviation"), "away_abbr": a["team"].get("abbreviation"),
            "home_name": h["team"].get("displayName"), "away_name": a["team"].get("displayName"),
            "home_score": _int(h.get("score")), "away_score": _int(a.get("score")),
            "completed": bool(c["status"]["type"]["completed"]),
            "neutral": bool(c.get("neutralSite")), "conference_game": bool(c.get("conferenceCompetition")),
        }
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SchemaError(f"unexpected ESPN CFB event shape (id={e.get('id')}): {exc!r}") from exc


async def _get(client, url, **params) -> dict:
    last = None
    for attempt in range(5):
        try:
            r = await client.get(url, params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"ESPN CFB request failed {url} {params}: {last!r}")


async def ingest_season(season: int) -> dict:
    async with httpx.AsyncClient(headers={"User-Agent": "tilt-cfb"}) as client:
        jobs = [(2, w, {"dates": season, "week": w, "groups": 80, "limit": 400, "seasontype": 2}) for w in REGULAR_WEEKS]
        # Bowls/playoff: query each date Dec 1 → Jan 20 (ESPN only labels them
        # correctly by date); keep events the API itself marks postseason.
        from datetime import date as _d, timedelta as _td
        d0 = _d(season, 12, 1)
        for i in range((_d(season + 1, 1, 20) - d0).days + 1):
            day = (d0 + _td(days=i)).strftime("%Y%m%d")
            jobs.append((3, 0, {"dates": day, "groups": 80, "limit": 400}))
        sem = asyncio.Semaphore(10)

        async def one(params):
            async with sem:
                return await _get(client, SCOREBOARD, **params)

        payloads = await asyncio.gather(*[one(p) for _, _, p in jobs])
        fbs = await _get(client, FBS_TEAMS.format(y=season), limit=400)
    by_id: dict[int, dict] = {}
    for (stype, week, _), payload in zip(jobs, payloads):
        for e in payload.get("events") or []:
            if not e:
                continue
            r = parse_event(e, stype, week)
            if r["season"] == season and not (stype == 3 and r["season_type"] != 3):
                by_id[r["game_id"]] = r
    rows = sorted(by_id.values(), key=lambda r: (r["game_date"], r["game_id"]))
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = GAMES_DIR / f"{season}.parquet.tmp"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), tmp, compression="zstd")
    os.replace(tmp, GAMES_DIR / f"{season}.parquet")
    group80 = sorted(int(x["$ref"].split("/teams/")[1].split("?")[0]) for x in fbs.get("items", []))
    m = load_manifest()
    m[str(season)] = {"rows": len(rows), "completed": sum(r["completed"] for r in rows),
                      "group80_teams": group80, "pulled_at": datetime.now(timezone.utc).isoformat()}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(m, indent=1, sort_keys=True))
    return {"season": season, "rows": len(rows), "completed": m[str(season)]["completed"], "group80": len(group80)}


FULL_SCHEDULE_MIN_GAMES = 6   # games vs ESPN-listed FBS opponents; FCS teams never reach this


def completed_games(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["completed"] and r["home_score"] is not None and r["away_score"] is not None]


def fbs_teams(season: int, rows: list[dict] | None = None) -> set[int]:
    """methodology/CFB.md v1.1 FBS rule: in ESPN's group-80 list AND played
    at least one completed game (drops ESPN's placeholder ids), OR played
    ≥ 6 completed games against the FBS slate (adds teams missing from
    ESPN's list, e.g. eight in 2001).
    """
    rows = completed_games(rows if rows is not None else read_games(season))
    g80 = set(load_manifest().get(str(season), {}).get("group80_teams", []))
    per: dict[int, int] = {}
    vs_fbs: dict[int, int] = {}
    for r in rows:
        for t, opp in ((r["home_id"], r["away_id"]), (r["away_id"], r["home_id"])):
            per[t] = per.get(t, 0) + 1
            if opp in g80:
                vs_fbs[t] = vs_fbs.get(t, 0) + 1
    return {t for t in per if (t in g80 and per[t] >= 1) or vs_fbs.get(t, 0) >= FULL_SCHEDULE_MIN_GAMES}


def coverage(season: int) -> dict:
    """§3 as clarified in v1.1: ≥ 95% of FBS teams have ≥ 11 regular-season
    games *listed* (completed, or listed but cancelled/postponed). The rule
    detects missing data, not games that were never played. 2020 exempt.
    """
    rows = read_games(season)
    fbs = fbs_teams(season, rows)
    reg = [r for r in rows if r["season_type"] == 2]
    per: dict[int, int] = {}
    for r in reg:
        per[r["home_id"]] = per.get(r["home_id"], 0) + 1
        per[r["away_id"]] = per.get(r["away_id"], 0) + 1
    need = 11
    full = sum(1 for t in fbs if per.get(t, 0) >= need)
    share = full / len(fbs) if fbs else 0.0
    return {"fbs_teams": len(fbs), "full_schedule": full, "share": round(share, 4), "min_games": need,
            "passes": season == 2020 or share >= 0.95, "exempt": season == 2020}


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}


def read_games(season: int) -> list[dict]:
    return pq.read_table(GAMES_DIR / f"{season}.parquet").to_pylist()


def current_season(today: date | None = None) -> int:
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="app.cfb.pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    g = ing.add_mutually_exclusive_group(required=True)
    g.add_argument("--season", type=int)
    g.add_argument("--all", action="store_true")
    a = p.parse_args(argv)
    seasons = [a.season] if a.season else list(range(FIRST_SEASON, current_season() + 1))
    for s in seasons:
        r = asyncio.run(ingest_season(s))
        print(f"  [{s}] {r['rows']} games ({r['completed']} completed) · ESPN group-80 list {r['group80']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
