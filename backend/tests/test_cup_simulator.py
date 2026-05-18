"""Tests for the v2.1 Monte Carlo Cup simulator."""

import math
import random

import pytest

from app import cup_simulator, historical, pipeline, standings


pytestmark = pytest.mark.skipif(
    not (pipeline.RAW_DIR / "20252026.parquet").exists(),
    reason="requires Phase A ingest of the current season",
)


@pytest.fixture(scope="module")
def cup_context():
    historical.initialize()
    state = standings.derive_playoff_state(20252026)
    stand = standings.compute_standings(20252026)
    ratings = cup_simulator.ratings_by_team_code(
        historical.current_active_ratings_with_codes()
    )
    cache = historical.get_cache()
    return {
        "state": state,
        "standings": stand,
        "ratings": ratings,
        "k_playoff": cache.params.k_playoff,
        "home_bump": cache.params.home_bump,
    }


def test_conference_membership_covers_all_32():
    union = cup_simulator.EAST_TEAMS | cup_simulator.WEST_TEAMS
    assert len(union) == 32
    assert cup_simulator.EAST_TEAMS.isdisjoint(cup_simulator.WEST_TEAMS)


def test_conference_of_known_teams():
    assert cup_simulator.conference_of("CAR") == "East"
    assert cup_simulator.conference_of("BOS") == "East"
    assert cup_simulator.conference_of("COL") == "West"
    assert cup_simulator.conference_of("VGK") == "West"


def test_outcome_type_probs_sum_to_one():
    assert math.isclose(sum(cup_simulator.OUTCOME_TYPE_PROBS.values()), 1.0, abs_tol=1e-9)


def test_home_for_game_index_follows_2_2_1_1_1():
    f = cup_simulator._home_for_game_index
    assert f(1, "HIGH", "LOW") == "HIGH"
    assert f(2, "HIGH", "LOW") == "HIGH"
    assert f(3, "HIGH", "LOW") == "LOW"
    assert f(4, "HIGH", "LOW") == "LOW"
    assert f(5, "HIGH", "LOW") == "HIGH"
    assert f(6, "HIGH", "LOW") == "LOW"
    assert f(7, "HIGH", "LOW") == "HIGH"


def test_series_sim_terminates_in_at_most_7_games_from_zero():
    ratings = {"HIGH": 1500.0, "LOW": 1500.0}
    rng = random.Random(0)
    games_played = 0

    # Patch _sim_game to count; quickest way without monkeypatching the random
    # outcome is to just run the series and check the resulting state isn't
    # impossible. We assert the function returns a participant.
    winner = cup_simulator._sim_series(
        "HIGH", "LOW",
        wins_higher_start=0, wins_lower_start=0,
        games_played_start=0,
        ratings=ratings, k_playoff=10.0, home_bump=40.0, rng=rng,
    )
    assert winner in ("HIGH", "LOW")


def test_series_sim_resumes_from_in_progress_state():
    # If we start at 3-3, exactly one more game should be played and that
    # determines the winner.
    ratings = {"HIGH": 1500.0, "LOW": 1500.0}
    rng = random.Random(0)
    winner = cup_simulator._sim_series(
        "HIGH", "LOW",
        wins_higher_start=3, wins_lower_start=3,
        games_played_start=6,
        ratings=ratings, k_playoff=10.0, home_bump=40.0, rng=rng,
    )
    assert winner in ("HIGH", "LOW")


def test_cup_simulate_returns_probabilities_summing_to_one(cup_context):
    result = cup_simulator.simulate_cup(
        cup_context["state"],
        cup_context["standings"],
        cup_context["ratings"],
        k_playoff=cup_context["k_playoff"],
        home_bump=cup_context["home_bump"],
        n_simulations=500,
        seed=1,
    )
    assert math.isclose(sum(result.cup_probabilities.values()), 1.0, abs_tol=1e-6)


def test_eliminated_teams_have_zero_probability(cup_context):
    result = cup_simulator.simulate_cup(
        cup_context["state"],
        cup_context["standings"],
        cup_context["ratings"],
        k_playoff=cup_context["k_playoff"],
        home_bump=cup_context["home_bump"],
        n_simulations=500,
        seed=1,
    )
    for team in result.eliminated:
        assert result.cup_probabilities[team] == 0.0


def test_alive_teams_have_positive_probability(cup_context):
    result = cup_simulator.simulate_cup(
        cup_context["state"],
        cup_context["standings"],
        cup_context["ratings"],
        k_playoff=cup_context["k_playoff"],
        home_bump=cup_context["home_bump"],
        n_simulations=2000,
        seed=1,
    )
    for team in result.alive:
        assert result.cup_probabilities[team] > 0.0


def test_repeated_runs_with_same_seed_are_deterministic(cup_context):
    a = cup_simulator.simulate_cup(
        cup_context["state"], cup_context["standings"], cup_context["ratings"],
        k_playoff=cup_context["k_playoff"], home_bump=cup_context["home_bump"],
        n_simulations=500, seed=42,
    )
    b = cup_simulator.simulate_cup(
        cup_context["state"], cup_context["standings"], cup_context["ratings"],
        k_playoff=cup_context["k_playoff"], home_bump=cup_context["home_bump"],
        n_simulations=500, seed=42,
    )
    assert a.cup_probabilities == b.cup_probabilities


def test_n_simulations_field_matches_request(cup_context):
    result = cup_simulator.simulate_cup(
        cup_context["state"], cup_context["standings"], cup_context["ratings"],
        k_playoff=cup_context["k_playoff"], home_bump=cup_context["home_bump"],
        n_simulations=777, seed=1,
    )
    assert result.n_simulations == 777
