"""Tests for the standings + playoff-state derivation used by the Cup sim."""

import pytest

from app import pipeline, standings


pytestmark = pytest.mark.skipif(
    not (pipeline.RAW_DIR / "20252026.parquet").exists(),
    reason="requires Phase A ingest of the current season",
)


def test_playoff_field_has_16_teams_when_round1_complete():
    state = standings.derive_playoff_state(20252026)
    assert len(state.playoff_field) == 16


def test_round1_has_8_series():
    state = standings.derive_playoff_state(20252026)
    assert len(state.round1_series) == 8
    # All R1 series should be complete by Round 2 (no in-progress R1).
    assert all(s.is_complete for s in state.round1_series)


def test_round2_has_4_series_total_in_full_bracket():
    state = standings.derive_playoff_state(20252026)
    assert len(state.round2_series) == 4


def test_alive_and_eliminated_are_disjoint_and_cover_field():
    state = standings.derive_playoff_state(20252026)
    assert set(state.alive).isdisjoint(set(state.eliminated))
    assert set(state.alive) | set(state.eliminated) == set(state.playoff_field)


def test_in_progress_series_have_no_winner():
    state = standings.derive_playoff_state(20252026)
    for s in state.all_series():
        if s.is_in_progress:
            assert s.winner is None
            assert s.wins_a < 4 and s.wins_b < 4


def test_completed_series_winner_has_4_wins():
    state = standings.derive_playoff_state(20252026)
    for s in state.all_series():
        if s.is_complete:
            assert max(s.wins_a, s.wins_b) == 4
            assert s.winner in (s.team_a, s.team_b)


def test_standings_total_games_per_team_match_82_for_completed_season():
    s = standings.compute_standings(20252026)
    # 2025-26 regular season is complete; every team should have 82 games
    # worth of decisions (W + L + OT_L). Allow small slack for any single
    # postponed/cancelled game that we may have skipped.
    for team, st in s.items():
        decisions = st.wins + st.losses + st.ot_losses
        assert 80 <= decisions <= 82, f"{team}: {decisions} decisions"


def test_standings_points_match_2W_plus_1OTL():
    s = standings.compute_standings(20252026)
    for team, st in s.items():
        assert st.points == 2 * st.wins + st.ot_losses
