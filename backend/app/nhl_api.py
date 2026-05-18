"""Thin client over the public NHL web API (api-web.nhle.com).

Scope: just enough to power the v1 thin vertical slice — today's schedule and
this-season's completed games. Historical-season ingest and idempotent caching
land in the next milestone.

The endpoints used here are the publicly documented `/v1/schedule/{date}` and
`/v1/score/{date}` resources. Both return JSON. Game state values seen in the
wild include "FUT" (future), "PRE" (pregame), "LIVE", "CRIT" (critical / late),
"FINAL", and "OFF" (official). We treat OFF and FINAL as "completed".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

BASE = "https://api-web.nhle.com/v1"
HTTP_TIMEOUT = 10.0

# Rough 2025-26 regular season start. Slightly early is fine — empty days are cheap.
SEASON_START_2025_26 = date(2025, 10, 7)

COMPLETED_STATES = {"OFF", "FINAL"}


@dataclass(frozen=True)
class Game:
    game_id: int
    game_date: date
    home: str  # 3-letter abbreviation
    away: str
    home_score: int | None
    away_score: int | None
    period_type: str | None  # "REG", "OT", "SO", or None if not finished
    state: str  # raw game state from the API

    @property
    def is_completed(self) -> bool:
        return self.state in COMPLETED_STATES and self.home_score is not None


def _parse_game(raw: dict[str, Any], game_day: date) -> Game | None:
    """Parse a single game record from the /score or /schedule payload.

    Returns None if the record can't be mapped to two known team abbreviations —
    rare, but defensive parsing keeps one bad record from breaking a whole day.
    """
    try:
        home = raw["homeTeam"]["abbrev"]
        away = raw["awayTeam"]["abbrev"]
    except KeyError:
        return None
    period_type = None
    if raw.get("gameOutcome"):
        period_type = raw["gameOutcome"].get("lastPeriodType")
    return Game(
        game_id=raw["id"],
        game_date=game_day,
        home=home,
        away=away,
        home_score=raw["homeTeam"].get("score"),
        away_score=raw["awayTeam"].get("score"),
        period_type=period_type,
        state=raw.get("gameState", "UNKNOWN"),
    )


async def fetch_games_on(client: httpx.AsyncClient, day: date) -> list[Game]:
    """All games scheduled on `day`, completed or otherwise."""
    url = f"{BASE}/score/{day.isoformat()}"
    resp = await client.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    games: list[Game] = []
    for raw in payload.get("games", []):
        g = _parse_game(raw, day)
        if g is not None:
            games.append(g)
    return games


async def fetch_today(client: httpx.AsyncClient, today: date) -> list[Game]:
    return await fetch_games_on(client, today)


async def fetch_completed_since(
    client: httpx.AsyncClient,
    start: date,
    end: date,
) -> list[Game]:
    """Walk dates [start, end] inclusive and return every completed game.

    Naive day-by-day fetch. Fine for a thin slice (≈220 days max per season);
    next milestone will replace this with a cached, idempotent ingest.
    """
    out: list[Game] = []
    day = start
    while day <= end:
        for g in await fetch_games_on(client, day):
            if g.is_completed:
                out.append(g)
        day += timedelta(days=1)
    return out
