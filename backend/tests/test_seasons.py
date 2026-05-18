"""Tests for the season-id helpers."""

from datetime import date

import pytest

from app import seasons


def test_parse_modern_season():
    s = seasons.parse(20232024)
    assert s.start_year == 2023
    assert s.end_year == 2024
    assert s.label == "2023-24"
    assert not s.is_pre_1967


def test_parse_first_season():
    s = seasons.parse(19171918)
    assert s.start_year == 1917
    assert s.is_pre_1967
    assert s.label == "1917-18"


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        seasons.parse(123)
    with pytest.raises(ValueError):
        seasons.parse(20232025)  # non-consecutive years


def test_date_range_covers_september_to_july():
    start, end = seasons.date_range(20232024)
    assert start == date(2023, 9, 1)
    assert end == date(2024, 7, 31)


def test_date_range_clamps_to_today():
    today = date(2023, 12, 15)
    _, end = seasons.date_range(20232024, today=today)
    assert end == today


def test_date_range_no_clamp_when_today_after_window():
    today = date(2025, 1, 1)
    _, end = seasons.date_range(20232024, today=today)
    assert end == date(2024, 7, 31)


def test_known_season_ids_skips_lockout_and_covers_range():
    ids = seasons.known_season_ids()
    assert ids[0] == 19171918
    assert ids[-1] == 20252026
    assert 20042005 not in ids  # cancelled lockout season
    assert 20032004 in ids
    assert 20052006 in ids
    assert len(ids) == 108


def test_cutoff_pre_1967_boundary():
    assert seasons.parse(19661967).is_pre_1967
    assert not seasons.parse(seasons.CUTOFF_PRE_1967).is_pre_1967
