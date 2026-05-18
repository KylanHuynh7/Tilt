"""Tests for the franchise lineage table — every transition in §4 v1.1 has a
unit test so a typo in the era ranges is immediately visible.
"""

import pytest

from app import franchises
from app.franchises import current_code, franchise_for


def test_calgary_inherits_atlanta_flames_via_afm_code():
    assert franchise_for("AFM", 19721973) == "calgary_flames"
    assert franchise_for("AFM", 19791980) == "calgary_flames"
    assert franchise_for("CGY", 19801981) == "calgary_flames"
    assert franchise_for("CGY", 20252026) == "calgary_flames"


def test_atl_code_is_thrashers_not_atlanta_flames():
    # ATL was reused only by the Atlanta Thrashers — the Flames era used AFM.
    assert franchise_for("ATL", 19741975) is None
    assert franchise_for("ATL", 19992000) == "winnipeg_jets"
    assert franchise_for("ATL", 20102011) == "winnipeg_jets"


def test_winnipeg_jets_thrashers_relocation():
    assert franchise_for("ATL", 20102011) == "winnipeg_jets"
    assert franchise_for("WPG", 20112012) == "winnipeg_jets"
    assert franchise_for("WPG", 20252026) == "winnipeg_jets"


def test_utah_full_lineage_via_original_jets_phoenix_arizona():
    assert franchise_for("WIN", 19851986) == "utah_mammoth"
    assert franchise_for("WIN", 19951996) == "utah_mammoth"
    assert franchise_for("PHX", 19961997) == "utah_mammoth"
    assert franchise_for("PHX", 20132014) == "utah_mammoth"
    assert franchise_for("ARI", 20142015) == "utah_mammoth"
    assert franchise_for("ARI", 20232024) == "utah_mammoth"
    assert franchise_for("UTA", 20242025) == "utah_mammoth"


def test_devils_inherit_rockies_and_scouts():
    assert franchise_for("KCS", 19741975) == "new_jersey_devils"
    assert franchise_for("CLR", 19761977) == "new_jersey_devils"
    assert franchise_for("CLR", 19811982) == "new_jersey_devils"
    assert franchise_for("NJD", 19821983) == "new_jersey_devils"


def test_avalanche_inherits_nordiques():
    assert franchise_for("QUE", 19791980) == "colorado_avalanche"
    assert franchise_for("QUE", 19941995) == "colorado_avalanche"
    assert franchise_for("COL", 19951996) == "colorado_avalanche"


def test_hurricanes_inherit_whalers():
    assert franchise_for("HFD", 19791980) == "carolina_hurricanes"
    assert franchise_for("HFD", 19961997) == "carolina_hurricanes"
    assert franchise_for("CAR", 19971998) == "carolina_hurricanes"


def test_dallas_inherits_north_stars_minnesota_wild_is_distinct():
    assert franchise_for("MNS", 19671968) == "dallas_stars"
    assert franchise_for("MNS", 19921993) == "dallas_stars"
    assert franchise_for("DAL", 19931994) == "dallas_stars"
    # MIN was reused for the brand-new 2000 expansion franchise; it must NOT
    # collide with the North Stars lineage.
    assert franchise_for("MIN", 20002001) == "minnesota_wild"
    assert franchise_for("MIN", 20252026) == "minnesota_wild"


def test_california_cleveland_chain_kept_separate_from_minnesota():
    # OAK → CGS → CLE are their own franchise through the last pre-merger
    # season. After 1977-78 these codes return None; the rating itself is
    # absorbed via the FRANCHISE_MERGERS table (tested separately).
    assert franchise_for("OAK", 19671968) == "california_cleveland"
    assert franchise_for("CGS", 19701971) == "california_cleveland"
    assert franchise_for("CLE", 19771978) == "california_cleveland"
    assert franchise_for("CLE", 19781979) is None
    # MNS played all those seasons as a distinct franchise:
    assert franchise_for("MNS", 19771978) == "dallas_stars"


def test_oak_cgs_cle_merger_registered_at_1978_79_boundary():
    """§4 v1.2 simple-average rule. Only one merger in NHL history, scheduled
    to fire at the start of 1978-79.
    """
    assert len(franchises.FRANCHISE_MERGERS) == 1
    m = franchises.FRANCHISE_MERGERS[0]
    assert m.absorbed_id == "california_cleveland"
    assert m.surviving_id == "dallas_stars"
    assert m.effective_season == 19781979
    assert franchises.mergers_at_boundary(19781979) == [m]
    assert franchises.mergers_at_boundary(19771978) == []
    assert franchises.mergers_at_boundary(19791980) == []


def test_detroit_three_codes_one_franchise():
    assert franchise_for("DCG", 19261927) == "detroit_red_wings"
    assert franchise_for("DFL", 19301931) == "detroit_red_wings"
    assert franchise_for("DET", 19321933) == "detroit_red_wings"


def test_toronto_three_codes_one_franchise():
    assert franchise_for("TAN", 19171918) == "toronto_maple_leafs"
    assert franchise_for("TSP", 19191920) == "toronto_maple_leafs"
    assert franchise_for("TOR", 19271928) == "toronto_maple_leafs"


def test_unknown_or_non_nhl_codes_return_none():
    assert franchise_for("USA", 20252026) is None  # exhibition / int'l
    assert franchise_for("ZZZ", 20002001) is None  # nonsense
    assert franchise_for("ATL", 19801981) is None  # AFM had retired


def test_current_code_for_active_franchises():
    assert current_code("calgary_flames") == "CGY"
    assert current_code("winnipeg_jets") == "WPG"
    assert current_code("utah_mammoth") == "UTA"
    assert current_code("dallas_stars") == "DAL"
    assert current_code("minnesota_wild") == "MIN"


def test_current_code_none_for_defunct():
    assert current_code("montreal_maroons") is None
    assert current_code("california_cleveland") is None
    assert current_code("ottawa_senators_original") is None


def test_active_set_has_exactly_32_franchises():
    assert len(franchises.ACTIVE_FRANCHISE_IDS) == 32
    for fid in franchises.ACTIVE_FRANCHISE_IDS:
        assert current_code(fid) is not None, fid


@pytest.mark.parametrize("code,season,expected", [
    ("BOS", 19241925, "boston_bruins"),
    ("BOS", 20252026, "boston_bruins"),
    ("MTL", 19171918, "montreal_canadiens"),
    ("MTL", 20252026, "montreal_canadiens"),
    ("PHI", 19671968, "philadelphia_flyers"),
    ("OTT", 19921993, "ottawa_senators"),
    ("SEN", 19171918, "ottawa_senators_original"),
])
def test_misc_spot_checks(code, season, expected):
    assert franchise_for(code, season) == expected
