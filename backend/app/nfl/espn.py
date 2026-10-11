"""ESPN NFL scoreboard client for live data (methodology/NFL.md §3).

The scoreboard with no `dates` parameter returns the current week. Only game
identity, score, clock, period, neutral flag and (when live) the `situation`
block are read; ESPN's `odds` and predictor fields are never touched (§10).
"""

from __future__ import annotations

import httpx

from .teams import from_espn

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


class SchemaError(RuntimeError):
    pass


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_event(e: dict) -> dict:
    try:
        comp = e["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        status = comp.get("status") or e["status"]
        stype = status["type"]
        sit = comp.get("situation") or {}
        poss_id = sit.get("possession")
        team_ids = {sides[k]["team"]["id"]: k for k in ("home", "away")}
        return {
            "game_id": e["id"],
            "date": e.get("date"),
            "season_type": int(e["season"]["type"]),
            "week": (e.get("week") or {}).get("number"),
            "home": from_espn(sides["home"]["team"]["abbreviation"]),
            "away": from_espn(sides["away"]["team"]["abbreviation"]),
            "home_score": _int(sides["home"].get("score")),
            "away_score": _int(sides["away"].get("score")),
            "neutral": bool(comp.get("neutralSite", False)),
            "state": str(stype.get("state", "")),     # pre / in / post
            "completed": bool(stype.get("completed")),
            "period": _int(status.get("period")) or 0,
            "clock_s": float(status.get("clock") or 0.0),
            # Live-only game state (unverified until first observed live; §3).
            "possession": team_ids.get(poss_id),       # "home" / "away" / None
            "yardline_100": _int(sit.get("yardsToEndzone")),
            "down": _int(sit.get("down")),
            "distance": _int(sit.get("distance")),
        }
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SchemaError(f"unexpected ESPN NFL event shape (id={e.get('id')}): {exc!r}") from exc


async def fetch_current_week(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(SCOREBOARD_URL, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if "events" not in payload:
        raise SchemaError("no 'events' in ESPN NFL scoreboard")
    return [parse_event(e) for e in payload["events"] if e]
