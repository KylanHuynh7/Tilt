"""NHL franchise lineage table.

Per METHODOLOGY.md v1.1 §4, franchise rating persists across relocations and
name changes. This module is the source of truth mapping the NHL API's
season-specific team codes to a stable franchise identity.

Lookup contract:
    franchise_for(team_code, season_id) -> franchise_id | None

`None` means the code didn't belong to any modeled franchise in that season —
which catches international teams, all-star squads, and PCHA / WHA / exhibition
codes that the public `/v1/score` endpoint mixes into older seasons.

Era ranges are inclusive on both ends. Use 99999999 for "still current".

Tricky cases covered:
  - "ATL" is reused by two distinct franchises with no historical overlap:
    the Atlanta Flames era used "AFM" (1972-80 → Calgary), while "ATL" maps
    only to the Atlanta Thrashers (1999-2011 → Winnipeg).
  - "WPG" is reused: the original Winnipeg Jets era used "WIN" (1979-96 →
    Phoenix/Arizona/Utah). "WPG" is exclusively the relocated Thrashers
    franchise (2011-current).
  - The California Golden Seals / Cleveland Barons franchise (OAK → CGS → CLE)
    is its own franchise through 1977-78 and then ends. Per §4 v1.2, at the
    start of 1978-79 the Minnesota North Stars (dallas_stars lineage) absorbs
    that rating via the simple-average merger rule defined in FRANCHISE_MERGERS
    below. The absorbed franchise stops existing in the rating state from that
    season boundary forward.
  - The Hamilton Tigers (HAM, 1920-25) are treated here as the predecessor
    franchise of the New York Americans (NYA / BRK). This is the conventional
    treatment but some sources dispute it.
"""

from __future__ import annotations

from dataclasses import dataclass

OPEN_END = 99999999


@dataclass(frozen=True)
class FranchiseEra:
    franchise_id: str
    team_code: str
    first_season: int  # inclusive
    last_season: int  # inclusive; OPEN_END = still active under this code

    def covers(self, code: str, season_id: int) -> bool:
        return (
            self.team_code == code
            and self.first_season <= season_id <= self.last_season
        )


# ----------------------------- the table ---------------------------------------
#
# Each franchise is one logical entity. Multiple FranchiseEra rows per franchise
# describe code/era changes (relocations or rebrands). The lookup walks this
# list in order and returns the first match.
#
FRANCHISE_ERAS: list[FranchiseEra] = [
    # --- Current 32 active franchises ----------------------------------------

    FranchiseEra("anaheim_ducks",            "ANA", 19931994, OPEN_END),
    FranchiseEra("boston_bruins",            "BOS", 19241925, OPEN_END),
    FranchiseEra("buffalo_sabres",           "BUF", 19701971, OPEN_END),

    FranchiseEra("calgary_flames",           "AFM", 19721973, 19791980),
    FranchiseEra("calgary_flames",           "CGY", 19801981, OPEN_END),

    FranchiseEra("carolina_hurricanes",      "HFD", 19791980, 19961997),
    FranchiseEra("carolina_hurricanes",      "CAR", 19971998, OPEN_END),

    FranchiseEra("chicago_blackhawks",       "CHI", 19261927, OPEN_END),

    FranchiseEra("colorado_avalanche",       "QUE", 19791980, 19941995),
    FranchiseEra("colorado_avalanche",       "COL", 19951996, OPEN_END),

    FranchiseEra("columbus_blue_jackets",    "CBJ", 20002001, OPEN_END),

    FranchiseEra("dallas_stars",             "MNS", 19671968, 19921993),
    FranchiseEra("dallas_stars",             "DAL", 19931994, OPEN_END),

    FranchiseEra("detroit_red_wings",        "DCG", 19261927, 19291930),
    FranchiseEra("detroit_red_wings",        "DFL", 19301931, 19311932),
    FranchiseEra("detroit_red_wings",        "DET", 19321933, OPEN_END),

    FranchiseEra("edmonton_oilers",          "EDM", 19791980, OPEN_END),
    FranchiseEra("florida_panthers",         "FLA", 19931994, OPEN_END),
    FranchiseEra("los_angeles_kings",        "LAK", 19671968, OPEN_END),
    FranchiseEra("minnesota_wild",           "MIN", 20002001, OPEN_END),
    FranchiseEra("montreal_canadiens",       "MTL", 19171918, OPEN_END),
    FranchiseEra("nashville_predators",      "NSH", 19981999, OPEN_END),

    FranchiseEra("new_jersey_devils",        "KCS", 19741975, 19751976),
    FranchiseEra("new_jersey_devils",        "CLR", 19761977, 19811982),
    FranchiseEra("new_jersey_devils",        "NJD", 19821983, OPEN_END),

    FranchiseEra("new_york_islanders",       "NYI", 19721973, OPEN_END),
    FranchiseEra("new_york_rangers",         "NYR", 19261927, OPEN_END),
    FranchiseEra("ottawa_senators",          "OTT", 19921993, OPEN_END),
    FranchiseEra("philadelphia_flyers",      "PHI", 19671968, OPEN_END),
    FranchiseEra("pittsburgh_penguins",      "PIT", 19671968, OPEN_END),
    FranchiseEra("san_jose_sharks",          "SJS", 19911992, OPEN_END),
    FranchiseEra("seattle_kraken",           "SEA", 20212022, OPEN_END),
    FranchiseEra("st_louis_blues",           "STL", 19671968, OPEN_END),
    FranchiseEra("tampa_bay_lightning",      "TBL", 19921993, OPEN_END),

    FranchiseEra("toronto_maple_leafs",      "TAN", 19171918, 19181919),
    FranchiseEra("toronto_maple_leafs",      "TSP", 19191920, 19261927),
    FranchiseEra("toronto_maple_leafs",      "TOR", 19271928, OPEN_END),

    FranchiseEra("utah_mammoth",             "WIN", 19791980, 19951996),  # original Jets
    FranchiseEra("utah_mammoth",             "PHX", 19961997, 20132014),
    FranchiseEra("utah_mammoth",             "ARI", 20142015, 20232024),
    FranchiseEra("utah_mammoth",             "UTA", 20242025, OPEN_END),

    FranchiseEra("vancouver_canucks",        "VAN", 19701971, OPEN_END),
    FranchiseEra("vegas_golden_knights",     "VGK", 20172018, OPEN_END),
    FranchiseEra("washington_capitals",      "WSH", 19741975, OPEN_END),

    FranchiseEra("winnipeg_jets",            "ATL", 19992000, 20102011),  # Thrashers era
    FranchiseEra("winnipeg_jets",            "WPG", 20112012, OPEN_END),

    # --- Defunct franchises that appear in the API's coverage window ---------

    # California / Oakland / Cleveland chain — absorbed into Minnesota in 1978.
    # Kept as its own franchise per the conservative reading of §4 v1.1.
    FranchiseEra("california_cleveland",     "OAK", 19671968, 19691970),
    FranchiseEra("california_cleveland",     "CGS", 19701971, 19751976),
    FranchiseEra("california_cleveland",     "CLE", 19761977, 19771978),

    # Pre-1967 defunct franchises that the modern /v1/score endpoint still
    # serves rows for. Tracked so the engine has somewhere to put their
    # rating updates; no calibration claims are made for the era per §2/§3.
    FranchiseEra("montreal_maroons",         "MMR", 19241925, 19371938),

    FranchiseEra("new_york_americans",       "HAM", 19201921, 19241925),
    FranchiseEra("new_york_americans",       "NYA", 19251926, 19401941),
    FranchiseEra("new_york_americans",       "BRK", 19411942, 19411942),

    FranchiseEra("pittsburgh_pirates",       "PIR", 19251926, 19291930),
    FranchiseEra("pittsburgh_pirates",       "QUA", 19301931, 19301931),

    FranchiseEra("ottawa_senators_original", "SEN", 19171918, 19331934),

    FranchiseEra("montreal_wanderers",       "MWN", 19171918, 19171918),
    FranchiseEra("quebec_bulldogs",          "QBD", 19191920, 19191920),

    # Two short-lived Toronto rivals that played alongside the Arenas / St. Pats.
    FranchiseEra("toronto_st_marys",         "SMT", 19181919, 19191920),
]


# Quick reverse maps for the dashboard and the engine.
ACTIVE_FRANCHISE_IDS: set[str] = {
    "anaheim_ducks", "boston_bruins", "buffalo_sabres", "calgary_flames",
    "carolina_hurricanes", "chicago_blackhawks", "colorado_avalanche",
    "columbus_blue_jackets", "dallas_stars", "detroit_red_wings",
    "edmonton_oilers", "florida_panthers", "los_angeles_kings",
    "minnesota_wild", "montreal_canadiens", "nashville_predators",
    "new_jersey_devils", "new_york_islanders", "new_york_rangers",
    "ottawa_senators", "philadelphia_flyers", "pittsburgh_penguins",
    "san_jose_sharks", "seattle_kraken", "st_louis_blues",
    "tampa_bay_lightning", "toronto_maple_leafs", "utah_mammoth",
    "vancouver_canucks", "vegas_golden_knights", "washington_capitals",
    "winnipeg_jets",
}


def franchise_for(team_code: str, season_id: int) -> str | None:
    """Return the franchise_id covering this (code, season) or None."""
    for era in FRANCHISE_ERAS:
        if era.covers(team_code, season_id):
            return era.franchise_id
    return None


def current_code(franchise_id: str) -> str | None:
    """The team code this franchise uses today, or None for defunct franchises."""
    for era in FRANCHISE_ERAS:
        if era.franchise_id == franchise_id and era.last_season == OPEN_END:
            return era.team_code
    return None


# --- Mergers (§4 v1.2) ---------------------------------------------------------

@dataclass(frozen=True)
class FranchiseMerger:
    absorbed_id: str
    surviving_id: str
    effective_season: int  # the season at whose START the merger applies

    def fires_at_boundary(self, entering_season: int) -> bool:
        return self.effective_season == entering_season


# Only one merger in NHL history sits inside the modeled era. The default
# rule per §4 v1.2 is the simple arithmetic average of the two pre-merger
# ratings; the backtest engine applies this BEFORE the standard decay step
# at the same season boundary. (Decay is linear in (R - mean) so order is
# algebraically irrelevant — averaging is done first for clarity.)
FRANCHISE_MERGERS: list[FranchiseMerger] = [
    FranchiseMerger(
        absorbed_id="california_cleveland",
        surviving_id="dallas_stars",
        effective_season=19781979,
    ),
]


def mergers_at_boundary(entering_season: int) -> list[FranchiseMerger]:
    return [m for m in FRANCHISE_MERGERS if m.fires_at_boundary(entering_season)]
