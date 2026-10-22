"""Player stats cards (facts from ESPN, not a Tilt model).

Season-by-season stats plus career totals for one athlete, normalized from
ESPN's `common/v3/.../athletes/{id}/stats`. Every category ESPN returns is
passed through (NBA averages/totals, NFL passing/rushing/…, NHL skater or
goalie lines). Cached for an hour per athlete.
"""

from __future__ import annotations

import time

import httpx

URL = "https://site.web.api.espn.com/apis/common/v3/sports/{path}/athletes/{athlete_id}/stats"
SPORT_PATHS = {"nba": "basketball/nba", "nfl": "football/nfl", "nhl": "hockey/nhl"}
TTL_S = 60 * 60
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def normalize(payload: dict) -> dict:
    # ESPN keys `teams` by slug; seasons reference teamId or teamSlug. Only the
    # abbreviation is read (team logos in this payload are never used, §13.I).
    teams: dict[str, str] = {}
    for slug, t in (payload.get("teams") or {}).items():
        abbr = (t or {}).get("abbreviation")
        teams[str(slug)] = abbr
        if (t or {}).get("id"):
            teams[str(t["id"])] = abbr
    cats = []
    for c in payload.get("categories") or []:
        seasons = []
        for row in c.get("statistics") or []:
            seasons.append({
                "season": (row.get("season") or {}).get("displayName"),
                "year": (row.get("season") or {}).get("year"),
                "team": teams.get(str(row.get("teamId"))) or teams.get(str(row.get("teamSlug"))),
                "stats": row.get("stats") or [],
            })
        seasons.sort(key=lambda r: r["year"] or 0, reverse=True)
        cats.append({
            "name": c.get("name"),
            "display_name": (c.get("displayName") or c.get("name") or "").strip(),
            "labels": c.get("labels") or [],
            "descriptions": c.get("displayNames") or c.get("labels") or [],
            "seasons": seasons,
            "career": c.get("totals") or [],
        })
    return {"categories": [c for c in cats if c["seasons"] or c["career"]]}


async def fetch(sport: str, athlete_id: str) -> dict:
    path = SPORT_PATHS[sport]
    key = (sport, athlete_id)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    async with httpx.AsyncClient(headers={"User-Agent": "tilt"}) as client:
        r = await client.get(URL.format(path=path, athlete_id=athlete_id), timeout=20)
        if r.status_code == 404:
            # ESPN's answer for players with no recorded stats (e.g. freshmen):
            # an empty card, not an error.
            out = {"sport": sport, "athlete_id": athlete_id, "categories": [], "source": "ESPN"}
            _cache[key] = (time.time(), out)
            return out
        r.raise_for_status()
        out = {"sport": sport, "athlete_id": athlete_id, **normalize(r.json()), "source": "ESPN"}
    _cache[key] = (time.time(), out)
    return out
