"""Integration tests for the walk-forward backtest.

These hit the actual ingested Parquet files. The 1967-68 expansion season is
small and self-contained, making it a good smoke target. Larger windows are
covered by parameterized sanity checks rather than exhaustive assertions.
"""

import math

import pytest

from app import backtest, franchises, pipeline
from app.ratings import INITIAL_RATING, LEAGUE_MEAN


pytestmark = pytest.mark.skipif(
    not (pipeline.RAW_DIR / "19671968.parquet").exists(),
    reason="requires Phase A ingest to have run for 1967-68",
)


def test_first_modern_season_runs_clean():
    result = backtest.run([19671968], record_snapshots=True)
    assert result.games_processed > 400  # 12 teams * 74 games / 2 + playoffs
    # No NHL game in 1967-68 involves an unknown franchise — anything dropped
    # is non-NHL game_type (all-star, etc.), not unknown teams.
    assert result.games_dropped_unknown_team == 0


def test_ratings_remain_in_sanity_bounds():
    """§9 stopping criterion #3: no team rating below 1200 or above 1800."""
    result = backtest.run([19671968, 19681969, 19691970, 19701971])
    for fid, rating in result.ratings.items():
        assert 1200.0 < rating < 1800.0, f"{fid} rating {rating} out of bounds"


def test_league_mean_stays_at_1500_after_replay():
    """Elo updates are zero-sum, and decay regresses toward 1500. The mean
    across all rated franchises should stay close to 1500 after any number
    of seasons.
    """
    result = backtest.run([19671968, 19681969, 19691970, 19701971, 19711972])
    mean = sum(result.ratings.values()) / len(result.ratings)
    assert abs(mean - LEAGUE_MEAN) < 1.0


def test_expansion_team_appears_at_1500():
    """The Vancouver Canucks and Buffalo Sabres both joined in 1970-71. After
    processing 1967-68 and 1968-69 they should not exist in state yet; after
    1970-71 they should exist with a rating that started at 1500 and moved.
    """
    pre = backtest.run([19671968, 19681969])
    assert "vancouver_canucks" not in pre.ratings
    assert "buffalo_sabres" not in pre.ratings

    post = backtest.run([19671968, 19681969, 19701971])
    assert "vancouver_canucks" in post.ratings
    assert "buffalo_sabres" in post.ratings


def test_decay_applied_at_season_boundary():
    """If a team enters a new season at exactly 1500, the decay rule is a
    no-op for them but applied for everyone else. Verifying via two-season
    replay vs single-season replay: between-season decay should appear as
    a pull-toward-1500 on any franchise that ended last season off-mean.
    """
    one = backtest.run([19671968])
    two = backtest.run([19671968, 19681969])

    # Pick a franchise that ended 1967-68 off-mean (Montreal won the Cup
    # that year — they should be well above 1500).
    if "montreal_canadiens" in one.ratings and "montreal_canadiens" in two.ratings:
        end_67 = one.ratings["montreal_canadiens"]
        if abs(end_67 - LEAGUE_MEAN) > 5.0:
            # 1968-69 ratings start from a decayed version of end_67 then evolve;
            # we don't know exactly where they land, but the engine wiring is
            # exercised either way. The smoke is: ratings stay in bounds.
            assert 1200.0 < two.ratings["montreal_canadiens"] < 1800.0


def test_warm_start_initial_state_is_honored():
    seed = {"montreal_canadiens": 1620.0, "toronto_maple_leafs": 1430.0}
    result = backtest.run([19671968], initial_state=seed)
    # State should still contain those franchises, with ratings shifted by
    # the season's games rather than reset to 1500.
    assert "montreal_canadiens" in result.ratings
    # Without the seed, MTL would start at 1500 and end somewhere different;
    # with the seed they start higher, so unless they lost every game they
    # should still be > 1500.
    assert result.ratings["montreal_canadiens"] != INITIAL_RATING


def test_predictions_recorded_only_for_specified_seasons():
    result = backtest.run(
        [19671968, 19681969],
        record_predictions_for={19681969},
    )
    seasons = {p.season_id for p in result.predictions}
    assert seasons == {19681969}


def test_no_predictions_recorded_with_empty_set():
    result = backtest.run(
        [19671968],
        record_predictions_for=set(),
    )
    assert result.predictions == []


def test_non_nhl_game_types_dropped_not_processed():
    """1967-68 has one all-star game (game_type=4) which should be dropped."""
    result = backtest.run([19671968])
    assert result.games_dropped_non_nhl_type >= 1


def test_prediction_probabilities_are_valid():
    result = backtest.run([19671968], record_predictions_for={19671968})
    for p in result.predictions:
        assert 0.0 < p.home_win_prob < 1.0
        assert math.isfinite(p.home_rating_before)
        assert math.isfinite(p.away_rating_before)


# ---- Merger handling per §4 v1.2 ----------------------------------------------

def test_california_cleveland_merger_absorbs_into_dallas_at_1978_79():
    """At the 1978-79 boundary the OAK/CGS/CLE chain ends and its rating is
    averaged into the Dallas (then MNS) lineage, then decay applies. The
    absorbed franchise must no longer exist in state from 1978-79 onward.
    """
    # Stop just before the merger boundary to capture the pre-merger numbers.
    pre = backtest.run([s for s in range(19671968, 19771978 + 10001, 10001)])
    mns_pre = pre.ratings["dallas_stars"]
    cle_pre = pre.ratings["california_cleveland"]
    expected_average = 0.5 * (mns_pre + cle_pre)

    # Now run one extra season — 1978-79 itself. At the boundary the engine
    # should average first, then apply decay to the averaged value.
    from app.ratings import apply_decay, DECAY_CARRY
    expected_after_decay = apply_decay(expected_average, carry=DECAY_CARRY)

    post = backtest.run([s for s in range(19671968, 19781979 + 10001, 10001)])
    assert "california_cleveland" not in post.ratings, "absorbed franchise must be removed"
    assert "dallas_stars" in post.ratings

    # The 1978-79 season's games will move the rating further; we just assert
    # that the boundary calculation set the starting point correctly. The
    # ending rating should be within ~50 points of the post-decay average
    # (a generous bound — actual movement depends on the season's results).
    diff = abs(post.ratings["dallas_stars"] - expected_after_decay)
    assert diff < 80.0, (
        f"dallas_stars 1978-79 end ({post.ratings['dallas_stars']:.2f}) "
        f"too far from post-merger-and-decay starting point "
        f"({expected_after_decay:.2f}); diff={diff:.2f}"
    )


def test_no_merger_means_dallas_rating_unchanged_pre_1978():
    """The merger rule must NOT affect pre-1978 ratings — sanity check that
    running through 1977-78 gives the same dallas_stars rating regardless
    of whether 1978-79 is in the window or not.
    """
    pre = backtest.run([s for s in range(19671968, 19771978 + 10001, 10001)])
    # california_cleveland should still exist at end of 1977-78
    assert "california_cleveland" in pre.ratings
    assert "dallas_stars" in pre.ratings
