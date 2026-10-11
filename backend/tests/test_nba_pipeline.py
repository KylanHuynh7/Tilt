"""NBA ingest: ESPN parsing, data-validity rules, coverage, neutral sites.

Offline — every ESPN payload here is a hand-built fixture in the shape the
live API returns.
"""

from datetime import date

import pytest

from app.nba import espn, pipeline


def _event(eid="401", year=2025, stype=2, home=("2", "BOS", "110"), away=("13", "LAL", "100"),
           completed=True, period=4, neutral=False, city="Boston"):
    return {
        "id": eid,
        "season": {"year": year, "type": stype},
        "competitions": [{
            "neutralSite": neutral,
            "venue": {"address": {"city": city}},
            "status": {"period": period, "type": {"completed": completed, "name": "STATUS_FINAL"}},
            "competitors": [
                {"homeAway": "home", "team": {"id": home[0], "abbreviation": home[1]}, "score": home[2]},
                {"homeAway": "away", "team": {"id": away[0], "abbreviation": away[1]}, "score": away[2]},
            ],
        }],
    }


def _row(**kw):
    return espn.parse_event(_event(**kw), date(2025, 1, 5))


def test_parse_event_maps_fields():
    r = _row(period=5)
    assert r["season_id"] == 20242025
    assert (r["home_team_id"], r["away_team_id"]) == (2, 13)
    assert (r["home_score"], r["away_score"], r["n_periods"]) == (110, 100, 5)
    assert r["completed"] is True


def test_parse_event_missing_abbreviation_is_tolerated():
    e = _event()
    del e["competitions"][0]["competitors"][1]["team"]["abbreviation"]
    assert espn.parse_event(e, date(2025, 1, 5))["away_abbr"] is None


def test_parse_event_schema_change_raises():
    e = _event()
    del e["competitions"]
    with pytest.raises(espn.SchemaError):
        espn.parse_event(e, date(2025, 1, 5))


@pytest.mark.parametrize("neutral,city,expected", [
    (True, "Las Vegas", True),          # ESPN-flagged (NBA Cup final, Paris, ...)
    (False, "Lake Buena Vista", True),  # 2020 bubble — not flagged by ESPN
    (False, "Boston", False),
])
def test_neutral_site_rule(neutral, city, expected):
    assert espn.is_neutral(_row(neutral=neutral, city=city)) is expected


def test_clean_rows_drops_zero_zero_finals():
    real = _row(eid="191103004")
    phantom = _row(eid="400217505", home=("2", "BOS", "0"), away=("13", "LAL", "0"))
    phantom["game_date"] = date(2025, 1, 6)
    out, drops = pipeline.clean_rows([real, phantom])
    assert [r["game_id"] for r in out] == [191103004]
    assert drops == {"dropped_zero_zero": 1, "dropped_duplicates": 0}


def test_clean_rows_collapses_same_day_duplicate_keeping_original_id():
    a, b = _row(eid="230104006"), _row(eid="400222658")
    out, drops = pipeline.clean_rows([b, a])
    assert [r["game_id"] for r in out] == [230104006]
    assert drops["dropped_duplicates"] == 1


def test_unfinished_zero_zero_game_is_kept():
    pre = _row(home=("2", "BOS", "0"), away=("13", "LAL", "0"), completed=False)
    out, drops = pipeline.clean_rows([pre])
    assert len(out) == 1 and drops["dropped_zero_zero"] == 0


def test_scheduled_games():
    assert pipeline.scheduled_regular_games(19941995) == 27 * 41
    assert pipeline.scheduled_regular_games(20002001) == 29 * 41
    assert pipeline.scheduled_regular_games(20242025) == 1230
    assert pipeline.scheduled_regular_games(20192020) == 1059


def test_first_model_season_restarts_after_failed_coverage():
    ok = {"coverage": {"passes": True}}
    bad = {"coverage": {"passes": False}}
    manifest = {"19931994": ok, "19992000": bad, "20002001": ok, "20182019": bad}
    # The failure at/after validation start does not move the warm-up start.
    assert pipeline.first_model_season(manifest) == 20002001
    assert pipeline.first_model_season({"19931994": ok}) == 19931994


def test_season_window_spans_bubble():
    days = pipeline.season_window(20192020)
    assert days[0] == date(2019, 9, 1) and date(2020, 10, 11) in days


def test_committed_manifest_matches_rule():
    """Guards the real data: the only pre-validation coverage failure is
    1999-2000, so the model starts in 2000-01.
    """
    manifest = pipeline.load_manifest()
    if not manifest:
        pytest.skip("NBA ingest has not run")
    assert pipeline.first_model_season(manifest) == 20002001
