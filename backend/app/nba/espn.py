"""ESPN public scoreboard client for the NBA (methodology/NBA.md §3).

One request per calendar day — ESPN's scoreboard ignores date ranges. The
parser is strict about the fields the model depends on and raises
`SchemaError` if they disappear, so an upstream format change fails loudly
instead of silently dropping games (§8 "data source breakage").
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# §3: the 2020 bubble is not flagged neutral by ESPN; every bubble game was
# played at this venue city.
BUBBLE_CITY = "Lake Buena Vista"

MAX_RETRIES = 4


class SchemaError(RuntimeError):
    """ESPN payload is missing a field the model depends on."""


def season_id_for_espn_year(year: int) -> int:
    """ESPN labels a season by its ending year: 2025 → 20242025."""
    return (year - 1) * 10000 + year


def _int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_event(event: dict, game_date: date) -> dict:
    """Map one ESPN scoreboard event to a pipeline row."""
    try:
        comp = event["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = sides["home"], sides["away"]
        status = comp.get("status") or event["status"]
        stype = status["type"]
        season = event["season"]
        row = {
            "game_id": int(event["id"]),
            "season_id": season_id_for_espn_year(int(season["year"])),
            "game_date": game_date,
            "season_type": int(season["type"]),
            "home_team_id": int(home["team"]["id"]),
            "away_team_id": int(away["team"]["id"]),
            "home_abbr": home["team"].get("abbreviation"),
            "away_abbr": away["team"].get("abbreviation"),
            "home_score": _int_or_none(home.get("score")),
            "away_score": _int_or_none(away.get("score")),
            "n_periods": _int_or_none(status.get("period")),
            "completed": bool(stype["completed"]),
            "status": str(stype["name"]),
            "espn_neutral": bool(comp.get("neutralSite", False)),
            "venue_city": ((comp.get("venue") or {}).get("address") or {}).get("city"),
        }
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SchemaError(f"unexpected ESPN event shape (id={event.get('id')}): {exc!r}") from exc
    return row


def is_neutral(row: dict) -> bool:
    """§3 neutral-site rule: ESPN's flag OR the bubble venue city."""
    return bool(row["espn_neutral"]) or row.get("venue_city") == BUBBLE_CITY


async def fetch_day(client: httpx.AsyncClient, day: date) -> list[dict]:
    """All events on one calendar day, parsed. Retries transient failures;
    raises after MAX_RETRIES so a season ingest never records a silent gap.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = await client.get(SCOREBOARD_URL, params={"dates": day.strftime("%Y%m%d")}, timeout=30)
            r.raise_for_status()
            payload = r.json()
            break
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"ESPN scoreboard failed for {day}: {last_exc!r}")
    if "events" not in payload:
        raise SchemaError(f"no 'events' key in ESPN scoreboard for {day}")
    # ESPN occasionally returns an empty `{}` placeholder event (seen on
    # 2007-10-19). It carries no game, so it is skipped; anything else that
    # fails to parse still raises.
    return [parse_event(e, day) for e in payload["events"] if e]
