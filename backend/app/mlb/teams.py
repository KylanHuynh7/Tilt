"""MLB franchises keyed on the MLB Stats API team id (methodology/MLB.md §3).

The API's team id is stable across relocations and renames (120 = Expos →
Nationals; 139 Devil Rays → Rays; 114 Indians → Guardians; 133 Oakland →
"Athletics"), so the id IS the franchise. Era abbreviations come from the
schedule rows. Display colors are tuned for the dark "ballpark night" world.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    mlb_id: int
    abbr: str
    name: str
    color: str


_ROWS = [
    (108, "LAA", "Los Angeles Angels", "#E4002C"), (109, "ARI", "Arizona Diamondbacks", "#E3D4AD"),
    (110, "BAL", "Baltimore Orioles", "#FC4C02"), (111, "BOS", "Boston Red Sox", "#E4334B"),
    (112, "CHC", "Chicago Cubs", "#3B7BE0"), (113, "CIN", "Cincinnati Reds", "#E8213A"),
    (114, "CLE", "Cleveland Guardians", "#E31937"), (115, "COL", "Colorado Rockies", "#A08ADB"),
    (116, "DET", "Detroit Tigers", "#FA4616"), (117, "HOU", "Houston Astros", "#EB6E1F"),
    (118, "KC", "Kansas City Royals", "#5A8FE0"), (119, "LAD", "Los Angeles Dodgers", "#3E86D6"),
    (120, "WSH", "Washington Nationals", "#E0283D"), (121, "NYM", "New York Mets", "#FF5910"),
    (133, "ATH", "Athletics", "#2FA36B"), (134, "PIT", "Pittsburgh Pirates", "#FDB827"),
    (135, "SD", "San Diego Padres", "#FFC425"), (136, "SEA", "Seattle Mariners", "#2AA3A0"),
    (137, "SF", "San Francisco Giants", "#FD5A1E"), (138, "STL", "St. Louis Cardinals", "#E0303F"),
    (139, "TB", "Tampa Bay Rays", "#8FBCE6"), (140, "TEX", "Texas Rangers", "#3F6FE0"),
    (141, "TOR", "Toronto Blue Jays", "#2F86E0"), (142, "MIN", "Minnesota Twins", "#D31145"),
    (143, "PHI", "Philadelphia Phillies", "#E81828"), (144, "ATL", "Atlanta Braves", "#CE1141"),
    (145, "CWS", "Chicago White Sox", "#C4CED4"), (146, "MIA", "Miami Marlins", "#00A3E0"),
    (147, "NYY", "New York Yankees", "#C4CED3"), (158, "MIL", "Milwaukee Brewers", "#FFC52F"),
]
TEAMS: dict[int, Team] = {i: Team(i, a, n, c) for i, a, n, c in _ROWS}


def is_franchise(team_id: int | None) -> bool:
    return team_id in TEAMS
