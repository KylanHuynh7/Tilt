"""Tests for live game-state extraction from the play-by-play payload (§16)."""

import pytest

from app import live_state
from app.live_state import LiveState, parse_live_state


def _make_payload(*, game_state="LIVE", plays=None) -> dict:
    return {
        "gameState": game_state,
        "plays": plays or [],
    }


def _goal(period: int, time_remaining: str, home_after: int, away_after: int,
          period_type: str = "REG") -> dict:
    return {
        "typeDescKey": "goal",
        "periodDescriptor": {"number": period, "periodType": period_type,
                              "maxRegulationPeriods": 3},
        "timeRemaining": time_remaining,
        "details": {"homeScore": home_after, "awayScore": away_after},
    }


def _non_goal_play(period: int, time_remaining: str, period_type: str = "REG") -> dict:
    return {
        "typeDescKey": "shot-on-goal",
        "periodDescriptor": {"number": period, "periodType": period_type,
                              "maxRegulationPeriods": 3},
        "timeRemaining": time_remaining,
    }


def test_parse_returns_none_when_no_game_state():
    assert parse_live_state({"plays": []}) is None


def test_parse_handles_pregame_with_no_plays():
    s = parse_live_state(_make_payload(game_state="FUT", plays=[]))
    assert s is not None
    assert s.game_state == "FUT"
    assert s.is_live is False
    assert s.home_score == 0
    assert s.away_score == 0
    assert s.period == 1
    assert s.time_remaining_s == 20 * 60


def test_parse_extracts_score_from_goal_events():
    plays = [
        _goal(1, "12:34", 1, 0),
        _non_goal_play(2, "14:00"),
        _goal(2, "10:15", 1, 1),
        _goal(3, "05:20", 2, 1),
        _non_goal_play(3, "03:30"),
    ]
    s = parse_live_state(_make_payload(game_state="LIVE", plays=plays))
    assert s is not None
    assert s.is_live is True
    assert s.home_score == 2
    assert s.away_score == 1
    assert s.score_diff == 1
    assert s.period == 3  # latest play is in P3
    assert s.time_remaining_s == 3 * 60 + 30  # 03:30 → 210s


def test_parse_buckets_overtime_to_period_4():
    plays = [
        _goal(1, "10:00", 1, 0),
        _goal(3, "01:00", 1, 1),
        _non_goal_play(4, "04:30", period_type="OT"),
    ]
    s = parse_live_state(_make_payload(game_state="CRIT", plays=plays))
    assert s is not None
    assert s.period == 4
    assert s.is_live is True


def test_parse_normalizes_time_to_zero_for_completed_games():
    plays = [
        _goal(3, "01:00", 2, 1),
        _non_goal_play(3, "00:00"),  # game over
    ]
    s = parse_live_state(_make_payload(game_state="OFF", plays=plays))
    assert s is not None
    assert s.time_remaining_s == 0
    assert s.is_live is False
    assert s.home_score == 2
    assert s.away_score == 1


def test_parse_handles_malformed_play_gracefully():
    plays = [
        {"typeDescKey": "goal", "details": {"homeScore": "wat", "awayScore": None}},
        _goal(2, "08:00", 1, 0),
    ]
    s = parse_live_state(_make_payload(game_state="LIVE", plays=plays))
    assert s is not None
    # Bad goal record ignored; only the valid one counts.
    assert s.home_score == 1
    assert s.away_score == 0


def test_parse_unrecognized_period_number_buckets_to_4():
    # Some payloads have OT period numbers like 5/6/7 in playoffs.
    plays = [_non_goal_play(5, "12:00", period_type="OT")]
    s = parse_live_state(_make_payload(game_state="LIVE", plays=plays))
    assert s.period == 4


def test_live_state_score_diff_property():
    s = LiveState(game_state="LIVE", period=2, time_remaining_s=600,
                  home_score=3, away_score=2)
    assert s.score_diff == 1
    assert s.is_live is True


def test_constants_consistency():
    # The three state-bucket sets must not overlap.
    assert live_state.LIVE_STATES.isdisjoint(live_state.PREGAME_STATES)
    assert live_state.LIVE_STATES.isdisjoint(live_state.COMPLETED_STATES)
    assert live_state.PREGAME_STATES.isdisjoint(live_state.COMPLETED_STATES)
