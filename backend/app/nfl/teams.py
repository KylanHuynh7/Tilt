"""NFL franchises keyed on the current nflverse team code (methodology/NFL.md §4).

Lineage: nflverse uses era codes for relocated teams, which map onto the
current franchise and inherit its rating (STL → LA 2016, SD → LAC 2017,
OAK → LV 2020). Houston (2002) is the only in-window expansion.

ESPN (live data) spells two codes differently: LAR → LA, WSH → WAS.
Display colors are tuned for the dark UI (NHL §13.I reasoning): navy and
black primaries use a lighter primary or the published alternate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    code: str
    name: str
    color: str


_ROWS = [
    ("ARI", "Arizona Cardinals", "#C8102E"), ("ATL", "Atlanta Falcons", "#D0273A"),
    ("BAL", "Baltimore Ravens", "#7B4FD0"), ("BUF", "Buffalo Bills", "#2F6FE0"),
    ("CAR", "Carolina Panthers", "#0085CA"), ("CHI", "Chicago Bears", "#E64100"),
    ("CIN", "Cincinnati Bengals", "#FB4F14"), ("CLE", "Cleveland Browns", "#FF3C00"),
    ("DAL", "Dallas Cowboys", "#B0B7BC"), ("DEN", "Denver Broncos", "#FC4C02"),
    ("DET", "Detroit Lions", "#0076B6"), ("GB", "Green Bay Packers", "#FFB612"),
    ("HOU", "Houston Texans", "#EB0028"), ("IND", "Indianapolis Colts", "#3A7BD5"),
    ("JAX", "Jacksonville Jaguars", "#00A3B4"), ("KC", "Kansas City Chiefs", "#E31837"),
    ("LA", "Los Angeles Rams", "#FFD100"), ("LAC", "Los Angeles Chargers", "#FFC20E"),
    ("LV", "Las Vegas Raiders", "#A5ACAF"), ("MIA", "Miami Dolphins", "#00A6AE"),
    ("MIN", "Minnesota Vikings", "#8A5CC9"), ("NE", "New England Patriots", "#C60C30"),
    ("NO", "New Orleans Saints", "#D3BC8D"), ("NYG", "New York Giants", "#3D6FC2"),
    ("NYJ", "New York Jets", "#2E9E5B"), ("PHI", "Philadelphia Eagles", "#1E8C93"),
    ("PIT", "Pittsburgh Steelers", "#FFB612"), ("SEA", "Seattle Seahawks", "#69BE28"),
    ("SF", "San Francisco 49ers", "#D4202A"), ("TB", "Tampa Bay Buccaneers", "#D32F45"),
    ("TEN", "Tennessee Titans", "#4495D2"), ("WAS", "Washington Commanders", "#FFB612"),
]
TEAMS: dict[str, Team] = {c: Team(c, n, col) for c, n, col in _ROWS}

ERA_CODES = {"STL": "LA", "SD": "LAC", "OAK": "LV"}
ESPN_CODES = {"LAR": "LA", "WSH": "WAS"}


def franchise(code: str) -> str | None:
    """nflverse era code → current franchise code (None if unknown)."""
    f = ERA_CODES.get(code, code)
    return f if f in TEAMS else None


def from_espn(abbr: str) -> str | None:
    return franchise(ESPN_CODES.get(abbr, abbr))
