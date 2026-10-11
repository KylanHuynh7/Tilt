"""ESPN depth charts → lineups (formation-aware starters, roster join)."""

from app.core import lineups


def _ath(i, rank):
    return {"rank": rank, "athlete": {"$ref": f"http://x/athletes/{i}?lang=en"}}


PAYLOAD = {"items": [
    {"name": "3WR 1TE", "positions": {
        "wr": {"position": {"abbreviation": "WR"}, "athletes": [_ath(11, 1), _ath(14, 4), _ath(12, 2), _ath(13, 3)]},
        "qb": {"position": {"abbreviation": "QB"}, "athletes": [_ath(1, 1), _ath(2, 2)]}}},
    {"name": "Base 4-3 D", "positions": {
        "lde": {"position": {"abbreviation": "LDE"}, "athletes": [_ath(30, 1)]}}},
]}


def test_formation_sets_starters_and_units_are_ordered():
    units = lineups.parse_charts("nfl", PAYLOAD)
    assert [u["unit"] for u in units] == ["Offense", "Defense"]
    wr = next(s for s in units[0]["slots"] if s["slot"] == "WR")
    assert wr["starter_ids"] == ["11", "12", "13"] and wr["depth_ids"] == ["14"]
    qb = next(s for s in units[0]["slots"] if s["slot"] == "QB")
    assert qb["starter_ids"] == ["1"] and qb["depth_ids"] == ["2"]


def test_attach_joins_roster_and_lists_others():
    roster = {"available": [{"group": "offense", "players": [
        {"id": "1", "name": "QB One", "status": None}, {"id": "2", "name": "QB Two", "status": None},
        {"id": "99", "name": "Unslotted", "status": None}]}],
        "ruled_out": [{"id": "11", "name": "Hurt WR", "status": "Out", "reason": "Out"}]}
    out = lineups.attach(roster, lineups.parse_charts("nfl", PAYLOAD))
    off = out["lineup"]["units"][0]
    qb = next(s for s in off["slots"] if s["slot"] == "QB")
    assert [p["name"] for p in qb["starters"]] == ["QB One"] and [p["name"] for p in qb["depth"]] == ["QB Two"]
    wr = next(s for s in off["slots"] if s["slot"] == "WR")
    assert wr["starters"][0]["name"] == "Hurt WR"            # injured starters still shown in their slot
    assert [p["name"] for p in out["lineup"]["others"]] == ["Unslotted"]


def test_no_chart_means_no_lineup():
    assert lineups.attach({"available": [], "ruled_out": []}, [])["lineup"] is None


def test_espn_season_labels():
    from datetime import date
    assert lineups.espn_season("nfl", date(2026, 10, 11)) == 2026
    assert lineups.espn_season("nba", date(2026, 10, 11)) == 2027
    assert lineups.espn_season("nhl", date(2027, 2, 1)) == 2027


def test_incomplete_chart_falls_back_with_note():
    roster = {"available": [{"group": "c", "players": [{"id": "1", "name": "A", "status": None}]}], "ruled_out": []}
    units = [{"unit": "Starting lineup", "formation": "", "slots": [{"slot": "LW", "label": None, "starter_ids": ["1"], "depth_ids": []}]}]
    out = lineups.attach(roster, units, "nhl")
    assert out["lineup"] is None and "incomplete" in out["lineup_note"]
