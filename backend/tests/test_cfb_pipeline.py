"""College football ingest rules (methodology/CFB.md v1.1)."""

import pytest

from app.cfb import pipeline


def _ev(eid=1, year=2015, stype=2, week=5, home=("1", "A", "10"), away=("2", "B", "7"), neutral=False):
    return {"id": eid, "date": "2015-10-03T19:00Z", "season": {"year": year, "type": stype}, "week": {"number": week},
            "competitions": [{"neutralSite": neutral, "conferenceCompetition": True,
                              "status": {"type": {"completed": True}},
                              "competitors": [
                                  {"homeAway": "home", "team": {"id": home[0], "abbreviation": home[1], "displayName": home[1]}, "score": home[2]},
                                  {"homeAway": "away", "team": {"id": away[0], "abbreviation": away[1], "displayName": away[1]}, "score": away[2]}]}]}


def test_season_type_comes_from_event_not_query():
    r = pipeline.parse_event(_ev(stype=2, week=9), season_type=3, week=0)
    assert r["season_type"] == 2 and r["week"] == 9


def test_postseason_week_is_zero():
    r = pipeline.parse_event(_ev(stype=3, week=1), season_type=3, week=0)
    assert r["season_type"] == 3 and r["week"] == 0


def test_schema_change_raises():
    e = _ev()
    del e["competitions"]
    with pytest.raises(pipeline.SchemaError):
        pipeline.parse_event(e, 2, 1)


def _row(h, a, completed=True):
    return {"home_id": h, "away_id": a, "home_score": 1 if completed else None, "away_score": 0 if completed else None,
            "completed": completed, "season_type": 2}


def test_fbs_rule_drops_placeholders_and_fcs_adds_unlisted(monkeypatch):
    # 1,2,3 listed FBS; 99 a listed placeholder that never plays; 7 unlisted but plays 6 FBS teams; 50 an FCS team
    rows = [_row(1, 2), _row(2, 3), _row(1, 50)] + [_row(7, 1)] * 3 + [_row(7, 2)] * 3 + [_row(50, 51)] * 6
    monkeypatch.setattr(pipeline, "load_manifest", lambda: {"2015": {"group80_teams": [1, 2, 3, 99]}})
    assert pipeline.fbs_teams(2015, rows) == {1, 2, 3, 7}


@pytest.mark.skipif(not pipeline.MANIFEST_PATH.exists(), reason="CFB ingest has not run")
def test_committed_fbs_counts_match_history():
    official = {2001: 117, 2005: 119, 2012: 124, 2014: 128, 2017: 130, 2023: 133, 2024: 134, 2025: 136}
    for season, n in official.items():
        assert len(pipeline.fbs_teams(season)) == n, season
    assert all(pipeline.coverage(s)["passes"] for s in range(2001, 2026))
