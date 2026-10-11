"""Team rosters + injury status from ESPN, shared by every sport's game-detail
page. Facts only: Tilt has no player model, so no projections are produced.
Cached in memory for 30 minutes per team to keep detail-page fan-out low.
"""

from __future__ import annotations

import time

import httpx

BASE = "https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{team}/roster"
TTL_S = 30 * 60
_cache: dict[tuple[str, str], tuple[float, dict]] = {}

# Not part of the game-day squad at all (dropped from the page).
EXCLUDED_GROUPS = {"practiceSquad"}
# Whole groups that cannot play.
RULED_OUT_GROUPS = {"injuredReserveOrOut": "Out / IR", "suspended": "Suspended"}
# Injury statuses that rule a player out. Questionable / Doubtful /
# Day-To-Day stay in the available list as game-time decisions.
RULED_OUT_STATUSES = {"out", "injured reserve", "suspension", "suspended", "out for season",
                      "physically unable to perform", "non-football injury", "ir"}


def _player(a: dict) -> dict:
    injuries = a.get("injuries") or []
    return {
        "name": a.get("displayName") or a.get("fullName"),
        "position": (a.get("position") or {}).get("abbreviation"),
        "jersey": a.get("jersey"),
        "status": injuries[0].get("status") if injuries else None,
    }


def parse(payload: dict) -> dict:
    """Split an ESPN roster into the game-day picture:

        available   [{group, players}]  healthy + game-time decisions (tagged)
        ruled_out   [player + reason]   out, IR, suspended

    ESPN returns either a flat athlete list (NBA) or position groups
    (NFL / NHL). Practice-squad players are dropped entirely.
    """
    athletes = payload.get("athletes") or []
    grouped = bool(athletes) and isinstance(athletes[0], dict) and "items" in athletes[0]
    groups = ([(g.get("position"), g.get("items") or []) for g in athletes] if grouped
              else [("Roster", athletes)])
    available, ruled_out = [], []
    for name, items in groups:
        if name in EXCLUDED_GROUPS:
            continue
        keep = []
        for a in items:
            p = _player(a)
            if name in RULED_OUT_GROUPS:
                ruled_out.append({**p, "reason": p["status"] or RULED_OUT_GROUPS[name]})
            elif p["status"] and p["status"].strip().lower() in RULED_OUT_STATUSES:
                ruled_out.append({**p, "reason": p["status"]})
            else:
                keep.append(p)
        if keep:
            available.append({"group": name, "players": keep})
    return {"available": available, "ruled_out": ruled_out}


async def fetch(client: httpx.AsyncClient, sport_path: str, team: str) -> dict:
    key = (sport_path, team)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    try:
        r = await client.get(BASE.format(path=sport_path, team=team), timeout=20)
        r.raise_for_status()
        out = {"loaded": True, **parse(r.json()), "source": "ESPN"}
    except Exception:  # noqa: BLE001 — a missing roster never breaks the page
        out = {"loaded": False, "available": [], "ruled_out": [], "source": "ESPN"}
    _cache[key] = (time.time(), out)
    return out
