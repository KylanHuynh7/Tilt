"""Game-day lineups from ESPN depth charts (NFL, NBA, NHL).

ESPN's core API publishes, per team, one or more charts ("3WR 1TE",
"Base 4-3 D", "Special Teams" for the NFL; one positional chart for NBA and
NHL) with athletes ranked per slot. We join those athlete ids onto the
roster we already fetch (names, headshots, injury status) and return:

    units: [{unit, formation, slots: [{slot, label, starters: [player], depth: [player]}]}]

Starters per slot come from the formation name ("3WR 1TE" → 3 WR, 1 TE);
every other slot has one starter. Facts only — no Tilt model involved.
College football has no ESPN depth charts; callers fall back to the roster.
"""

from __future__ import annotations

import re
import time
from datetime import date

import httpx

CORE = "https://sports.core.api.espn.com/v2/sports/{path}/seasons/{season}/teams/{team}/depthcharts"
LEAGUE_PATHS = {"nfl": "football/leagues/nfl", "nba": "basketball/leagues/nba", "nhl": "hockey/leagues/nhl"}
TTL_S = 30 * 60
_cache: dict[tuple, tuple[float, list]] = {}

NHL_LABELS = {"c": "Centers (lines 1–4)", "lw": "Left wings", "rw": "Right wings", "d": "Defense (pairs)", "g": "Goalies"}


def espn_season(sport: str, today: date | None = None) -> int:
    """ESPN labels NBA/NHL seasons by their ending year; NFL by the start year."""
    today = today or date.today()
    if sport == "nfl":
        return today.year if today.month >= 3 else today.year - 1
    return today.year + 1 if today.month >= 8 else today.year


def unit_name(sport: str, chart_name: str, slot_keys: list[str]) -> str:
    if sport != "nfl":
        return "Starting lineup"
    name = chart_name.lower()
    if "special" in name:
        return "Special teams"
    if any(k in slot_keys for k in ("lde", "rde", "mlb", "lcb", "ss", "fs", "nt", "lolb", "rolb")):
        return "Defense"
    return "Offense"


def starters_for(slot_key: str, formation: str) -> int:
    m = re.search(rf"(\d+)\s*{slot_key}\b", formation, flags=re.IGNORECASE)
    return int(m.group(1)) if m else 1


def _athlete_id(ref: str) -> str:
    return ref.split("/athletes/")[1].split("?")[0]


def parse_charts(sport: str, payload: dict) -> list[dict]:
    units = []
    for chart in payload.get("items") or []:
        positions = chart.get("positions") or {}
        formation = chart.get("name") or ""
        slots = []
        for key, v in positions.items():
            ranked = sorted(v.get("athletes") or [], key=lambda a: a.get("rank", 99))
            ids = [_athlete_id(a["athlete"]["$ref"]) for a in ranked if a.get("athlete", {}).get("$ref")]
            n = starters_for(key, formation) if sport == "nfl" else 1
            label = NHL_LABELS.get(key) if sport == "nhl" else None
            slots.append({"slot": (v.get("position") or {}).get("abbreviation") or key.upper(),
                          "label": label, "starter_ids": ids[:n], "depth_ids": ids[n:]})
        units.append({"unit": unit_name(sport, formation, list(positions)), "formation": formation, "slots": slots})
    order = {"Offense": 0, "Defense": 1, "Special teams": 2, "Starting lineup": 0}
    return sorted(units, key=lambda u: order.get(u["unit"], 9))


async def fetch(client: httpx.AsyncClient, sport: str, team_id: str) -> list[dict] | None:
    if sport not in LEAGUE_PATHS or not team_id:
        return None
    key = (sport, team_id)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    try:
        r = await client.get(CORE.format(path=LEAGUE_PATHS[sport], season=espn_season(sport), team=team_id), timeout=20)
        r.raise_for_status()
        units = parse_charts(sport, r.json())
    except Exception:  # noqa: BLE001 — no depth chart never breaks the page
        units = []
    _cache[key] = (time.time(), units)
    return units


# A chart is only shown if it places at least a full lineup's worth of
# players: ESPN's NHL charts are often near-empty (one player listed).
MIN_PLACED = {"nfl": 22, "nba": 5, "nhl": 18}


def attach(roster: dict, units: list[dict] | None, sport: str | None = None) -> dict:
    """Join depth-chart ids onto roster players. Players on the roster but in
    no depth slot go to `others`; the ruled-out list is unchanged.
    """
    if not units:
        return {**roster, "lineup": None,
                "lineup_note": "No depth chart is published for this team, so players are grouped by position."}
    players = {p["id"]: p for g in roster.get("available", []) for p in g["players"]}
    out_ids = {p["id"]: p for p in roster.get("ruled_out", [])}
    placed: set[str] = set()

    def resolve(pid):
        p = players.get(pid) or out_ids.get(pid)
        if p:
            placed.add(pid)
        return p

    lineup = []
    for u in units:
        slots = []
        for s in u["slots"]:
            starters = [p for p in map(resolve, s["starter_ids"]) if p]
            depth = [p for p in map(resolve, s["depth_ids"]) if p]
            if starters or depth:
                slots.append({"slot": s["slot"], "label": s["label"], "starters": starters, "depth": depth})
        if slots:
            lineup.append({"unit": u["unit"], "formation": u["formation"], "slots": slots})
    if sport and len(placed) < MIN_PLACED.get(sport, 0):
        return {**roster, "lineup": None,
                "lineup_note": "This team's published depth chart is incomplete, so players are grouped by position."}
    others = [p for pid, p in players.items() if pid not in placed]
    return {**roster, "lineup": {"source": "ESPN depth chart", "units": lineup, "others": others}}
