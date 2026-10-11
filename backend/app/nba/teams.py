"""NBA franchise table keyed on ESPN team id (methodology/NBA.md §4).

ESPN's team id is stable across relocations and renames and already follows
roster continuity (id 3 = 1990s Charlotte Hornets → New Orleans; id 30 =
2004 Bobcats → current Hornets; id 29 = Vancouver → Memphis; id 25 =
Seattle → Oklahoma City). The franchise id IS the ESPN team id, so lineage
needs no hand-curated era table. Any id not in this table (All-Star teams,
international clubs) is not an NBA franchise and its games are dropped.

Abbreviations are the conventional three-letter codes rather than ESPN's
(GS → GSW, NO → NOP, NY → NYK, SA → SAS, UTAH → UTA, WSH → WAS). Colors are
ESPN's published primary/alternate team colors, used for badges only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    espn_id: int
    abbr: str
    name: str
    color: str      # primary, "#rrggbb"
    alt_color: str  # alternate, "#rrggbb"


_ROWS = [
    (1, "ATL", "Atlanta Hawks", "c8102e", "fdb927"),
    (2, "BOS", "Boston Celtics", "008348", "ffffff"),
    (3, "NOP", "New Orleans Pelicans", "0a2240", "b4975a"),
    (4, "CHI", "Chicago Bulls", "ce1141", "000000"),
    (5, "CLE", "Cleveland Cavaliers", "860038", "bc945c"),
    (6, "DAL", "Dallas Mavericks", "0064b1", "bbc4ca"),
    (7, "DEN", "Denver Nuggets", "0e2240", "fec524"),
    (8, "DET", "Detroit Pistons", "1d428a", "c8102e"),
    (9, "GSW", "Golden State Warriors", "fdb927", "1d428a"),
    (10, "HOU", "Houston Rockets", "ce0e2d", "000000"),
    (11, "IND", "Indiana Pacers", "0c2340", "ffd520"),
    (12, "LAC", "LA Clippers", "12173f", "c8102e"),
    (13, "LAL", "Los Angeles Lakers", "552583", "fdb927"),
    (14, "MIA", "Miami Heat", "98002e", "000000"),
    (15, "MIL", "Milwaukee Bucks", "00471b", "eee1c6"),
    (16, "MIN", "Minnesota Timberwolves", "266092", "79bc43"),
    (17, "BKN", "Brooklyn Nets", "000000", "ffffff"),
    (18, "NYK", "New York Knicks", "1d428a", "f58426"),
    (19, "ORL", "Orlando Magic", "0150b5", "9ca0a3"),
    (20, "PHI", "Philadelphia 76ers", "1d428a", "e01234"),
    (21, "PHX", "Phoenix Suns", "29127a", "e56020"),
    (22, "POR", "Portland Trail Blazers", "e03a3e", "000000"),
    (23, "SAC", "Sacramento Kings", "5a2d81", "6a7a82"),
    (24, "SAS", "San Antonio Spurs", "000000", "c4ced4"),
    (25, "OKC", "Oklahoma City Thunder", "007ac1", "ef3b24"),
    (26, "UTA", "Utah Jazz", "4e008e", "79a3dc"),
    (27, "WAS", "Washington Wizards", "e31837", "002b5c"),
    (28, "TOR", "Toronto Raptors", "d91244", "000000"),
    (29, "MEM", "Memphis Grizzlies", "5d76a9", "12173f"),
    (30, "CHA", "Charlotte Hornets", "008ca8", "1d1060"),
]

TEAMS: dict[int, Team] = {
    tid: Team(tid, abbr, name, f"#{c}", f"#{alt}") for tid, abbr, name, c, alt in _ROWS
}


# Dashboard line/badge colors tuned for the dark UI (same reasoning as NHL
# §13.I): navy/black primaries vanish on charcoal, so those teams use their
# published alternate (gold, silver, cream, light blue) or a lightened
# primary. Keyed by franchise so historical names (SEA, NJN, NOH) inherit.
DISPLAY_COLORS: dict[int, str] = {
    1: "#E03A3E", 2: "#00A35C", 3: "#B4975A", 4: "#CE1141", 5: "#B23A63",
    6: "#2B8BE0", 7: "#FEC524", 8: "#3A66C4", 9: "#FDB927", 10: "#CE0E2D",
    11: "#FFD520", 12: "#C8102E", 13: "#8A5CC9", 14: "#D0103A", 15: "#EEE1C6",
    16: "#79BC43", 17: "#D0D0D0", 18: "#F58426", 19: "#2F7BE0", 20: "#5B8DEF",
    21: "#E56020", 22: "#E03A3E", 23: "#9B6BD6", 24: "#C4CED4", 25: "#2FA4E7",
    26: "#79A3DC", 27: "#E31837", 28: "#D91244", 29: "#7D95C7", 30: "#00A6C0",
}

# ESPN's historical abbreviations → conventional display codes. Era-specific
# names are kept (VAN in 2000-01, SEA through 2007-08, NJN through 2011-12);
# only ESPN's non-standard spellings are normalized.
_ABBR_FIX = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS", "NJ": "NJN"}


def display_abbr(espn_id: int, espn_abbr: str | None, season_id: int) -> str:
    """Era-appropriate code for a franchise in a given season."""
    if espn_abbr is None:
        return TEAMS[espn_id].abbr
    if espn_id == 3:  # Charlotte (2000-02) → New Orleans Hornets → Pelicans (2013)
        if espn_abbr == "CHA":
            return "CHH"
        return "NOP" if season_id >= 20132014 else "NOH"
    return _ABBR_FIX.get(espn_abbr, espn_abbr)


def is_franchise(espn_id: int | None) -> bool:
    return espn_id in TEAMS
