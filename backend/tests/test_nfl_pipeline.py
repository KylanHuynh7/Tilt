"""NFL ingest (methodology/NFL.md §3-§4): permitted columns only, coverage
rule, lineage. Offline except the committed-data guard.
"""

import pyarrow.parquet as pq
import pytest

from app.nfl import pipeline, teams

HEADER = ("game_id,season,game_type,week,gameday,weekday,gametime,away_team,away_score,"
          "home_team,home_score,location,result,total,overtime,spread_line,home_moneyline\n")


def test_parse_csv_keeps_permitted_fields():
    text = HEADER + "2025_01_DAL_PHI,2025,REG,1,2025-09-04,Thursday,20:20,DAL,20,PHI,24,Home,4,44,0,-7.5,-350\n"
    (row,) = pipeline.parse_csv(text)
    assert set(row) == set(pipeline.ALLOWED)
    assert row["home_score"] == 24 and row["overtime"] is False


def test_parse_csv_unplayed_game_has_null_scores():
    text = HEADER + "2026_18_DAL_PHI,2026,REG,18,2027-01-03,Sunday,13:00,DAL,NA,PHI,NA,Home,NA,NA,NA,NA,NA\n"
    (row,) = pipeline.parse_csv(text)
    assert row["home_score"] is None


def test_parse_csv_rejects_schema_change():
    with pytest.raises(RuntimeError, match="missing columns"):
        pipeline.parse_csv("game_id,season\nx,2025\n")


def test_schedule_sizes():
    assert pipeline.scheduled_regular_games(1999) == 248
    assert pipeline.scheduled_regular_games(2002) == 256
    assert pipeline.scheduled_regular_games(2021) == 272


@pytest.mark.parametrize("code,expected", [("STL", "LA"), ("SD", "LAC"), ("OAK", "LV"), ("KC", "KC"), ("XYZ", None)])
def test_lineage(code, expected):
    assert teams.franchise(code) == expected


def test_espn_codes_map_to_franchises():
    assert teams.from_espn("LAR") == "LA" and teams.from_espn("WSH") == "WAS"


@pytest.mark.skipif(not pipeline.GAMES_PATH.exists(), reason="NFL ingest has not run")
def test_committed_parquet_has_no_betting_columns():
    cols = set(pq.read_table(pipeline.GAMES_PATH).column_names)
    assert cols == set(pipeline.ALLOWED)
    assert not cols & pipeline.FORBIDDEN
    cov = pipeline.load_manifest()["coverage"]
    assert all(cov[str(s)]["passes"] for s in range(1999, 2026))
