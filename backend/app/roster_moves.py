"""Roster moves inferred from box-score lineups (METHODOLOGY.md §20, V3-1 → V3-3).

A *move* is a player whose consecutive appearances within one season are for
different teams, counted only if the player appeared in ≥ 10 of the old team's
games that season before moving (V3-2). Each move yields a boost *event* for
both teams:
  - new team: its first game with the player;
  - old team: its first game on or after that date.
Events are keyed (game_id, team code); several moves on one team-date collapse
into one event (V3-3).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from . import boxscores

MIN_GAMES_OLD_TEAM = 10


@dataclass(frozen=True)
class Move:
    season_id: int
    player_id: int
    name: str
    from_team: str
    to_team: str
    first_game_new: int
    move_date: date
    games_with_old: int


def detect(rows: Iterable[dict]) -> tuple[list[Move], set[tuple[int, str]]]:
    """Moves and (game_id, team) events from one season's box-score rows."""
    rows = [r for r in rows if r["game_type"] in (2, 3)]
    schedule: dict[str, list[tuple[date, int]]] = defaultdict(list)
    seen_team_games: set[tuple[str, int]] = set()
    by_player: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if (r["team"], r["game_id"]) not in seen_team_games:
            seen_team_games.add((r["team"], r["game_id"]))
            schedule[r["team"]].append((r["game_date"], r["game_id"]))
        by_player[r["player_id"]].append(r)
    for games in schedule.values():
        games.sort()

    moves: list[Move] = []
    events: set[tuple[int, str]] = set()
    for pid, apps in by_player.items():
        apps.sort(key=lambda r: (r["game_date"], r["game_id"]))
        counts: dict[str, int] = defaultdict(int)
        prev = None
        for r in apps:
            if prev is not None and r["team"] != prev["team"] and counts[prev["team"]] >= MIN_GAMES_OLD_TEAM:
                old = prev["team"]
                moves.append(Move(r["season_id"], pid, r.get("name") or "", old, r["team"], r["game_id"],
                                  r["game_date"], counts[old]))
                events.add((r["game_id"], r["team"]))
                nxt = next((gid for d, gid in schedule[old] if d >= r["game_date"]), None)
                if nxt is not None:
                    events.add((nxt, old))
            counts[r["team"]] += 1
            prev = r
    return moves, events


def season_events(season_id: int) -> set[tuple[int, str]]:
    return detect(boxscores.read_season(season_id))[1]


def all_events(season_ids: Iterable[int]) -> set[tuple[int, str]]:
    out: set[tuple[int, str]] = set()
    for s in season_ids:
        out |= season_events(s)
    return out


# Completed seasons' events never change: cached once (same `detect` as the
# freeze) so the live dashboard doesn't re-read 2M box-score rows at startup.
CACHE = Path(__file__).resolve().parent.parent / "artifacts" / "nhl_roster_events.json"


def write_cache(season_ids: Iterable[int]) -> int:
    data = {str(s): sorted([list(e) for e in season_events(s)]) for s in season_ids}
    CACHE.write_text(json.dumps(data))
    return sum(len(v) for v in data.values())


def events_for(season_ids: Iterable[int]) -> set[tuple[int, str]]:
    """Cached events for completed seasons, detected live for the rest."""
    cached = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    out: set[tuple[int, str]] = set()
    for s in season_ids:
        if str(s) in cached:
            out |= {(int(g), t) for g, t in cached[str(s)]}
        elif (boxscores.BOX_DIR / f"{s}.parquet").exists():
            out |= season_events(s)
    return out
