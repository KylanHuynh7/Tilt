"""Monte Carlo Stanley Cup probability simulator — v2.1 §14.

Given:
  - current rating state (from historical.current_ratings)
  - current playoff bracket state (from standings.derive_playoff_state)
  - frozen v2.0 parameters (K_playoff, home_bump, outcome weights)

Runs N independent simulations of the rest of the playoffs and returns the
probability each playoff team wins the Cup.

Design choices documented in METHODOLOGY.md §14:
  - Per-game rating updates within a single sim run.
  - Outcome type (REG/OT/SO) sampled from the league-wide historical
    distribution; not modeled as a function of rating gap.
  - In-progress series resume from current state (game count and per-team
    wins preserved).
  - The bracket tree is derived empirically from observed Round 1 matchups
    in combination with conference membership.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .franchises import current_code, franchise_for
from .ratings import OUTCOME_WEIGHTS, win_probability
from .standings import PlayoffState, Series, Standing

# ---- Conference membership (current 32 NHL franchises) -----------------------
#
# Used to determine which Round 2 series feed which Conference Final series.
# An R2 series is in the same conference as the teams it contains; the two
# R2 series in each conference feed that conference's CF.

EAST_TEAMS = frozenset({
    "BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR",
    "CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH",
})
WEST_TEAMS = frozenset({
    "ANA", "CGY", "EDM", "LAK", "SJS", "SEA", "VAN", "VGK",
    "CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTA", "WPG",
})


def conference_of(team_code: str) -> str:
    if team_code in EAST_TEAMS:
        return "East"
    if team_code in WEST_TEAMS:
        return "West"
    raise ValueError(f"unknown team code: {team_code!r}")


# ---- Outcome-type sampling ---------------------------------------------------

# 2024-25 empirical distribution (regular season + playoffs combined).
# Documented in §14 as the assumed sampling distribution; not modeled as a
# function of rating gap. Refresh this if the league mix shifts materially.
OUTCOME_TYPE_PROBS = {
    "REG": 0.795,
    "OT":  0.155,
    "SO":  0.050,
}


def _sample_outcome_type(rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for outcome_type, p in OUTCOME_TYPE_PROBS.items():
        cum += p
        if r < cum:
            return outcome_type
    return "REG"  # numerical safety


# ---- Game-level sim ----------------------------------------------------------

@dataclass
class SimGame:
    home: str
    away: str
    winner: str
    outcome_type: str  # REG | OT | SO


def _sim_game(
    home: str,
    away: str,
    ratings: dict[str, float],
    *,
    k_playoff: float,
    home_bump: float,
    rng: random.Random,
) -> SimGame:
    """Sample one game given the two teams' current ratings.

    Updates `ratings` in place using the v2.0 rule (K_playoff for playoffs).
    Mutating in place is deliberate — the per-sim hot/cold streak dynamics
    require ratings to carry from game to game within a single sim run.
    """
    r_home = ratings.get(home, 1500.0)
    r_away = ratings.get(away, 1500.0)
    p_home = win_probability(r_home, r_away, home_bump=home_bump)

    home_won = rng.random() < p_home
    winner = home if home_won else away
    outcome_type = _sample_outcome_type(rng)

    # Determine the weighted outcome from home perspective.
    if home_won:
        w_home = {"REG": OUTCOME_WEIGHTS["REG_WIN"],
                  "OT":  OUTCOME_WEIGHTS["OT_WIN"],
                  "SO":  OUTCOME_WEIGHTS["SO_WIN"]}[outcome_type]
    else:
        w_home = {"REG": OUTCOME_WEIGHTS["REG_LOSS"],
                  "OT":  OUTCOME_WEIGHTS["OT_LOSS"],
                  "SO":  OUTCOME_WEIGHTS["SO_LOSS"]}[outcome_type]
    w_away = 1.0 - w_home

    ratings[home] = r_home + k_playoff * (w_home - p_home)
    ratings[away] = r_away + k_playoff * (w_away - (1.0 - p_home))

    return SimGame(home=home, away=away, winner=winner, outcome_type=outcome_type)


# ---- Series sim --------------------------------------------------------------

def _home_for_game_index(
    one_indexed_game: int,
    higher_seed: str,
    lower_seed: str,
) -> str:
    """2-2-1-1-1 home pattern. Games 1, 2, 5, 7 at higher seed; 3, 4, 6 at lower."""
    return higher_seed if one_indexed_game in {1, 2, 5, 7} else lower_seed


def _sim_series(
    higher_seed: str,
    lower_seed: str,
    *,
    wins_higher_start: int,
    wins_lower_start: int,
    games_played_start: int,
    ratings: dict[str, float],
    k_playoff: float,
    home_bump: float,
    rng: random.Random,
) -> str:
    """Play out a best-of-7 from the given starting score until one team wins 4.

    `wins_*_start` and `games_played_start` describe the state coming in
    (used to resume in-progress series). Returns the winning team code.
    """
    wins_h = wins_higher_start
    wins_l = wins_lower_start
    next_game = games_played_start + 1
    while wins_h < 4 and wins_l < 4:
        if next_game > 7:
            # Defensive — should never happen if the inputs are sane.
            return higher_seed if wins_h >= wins_l else lower_seed
        home = _home_for_game_index(next_game, higher_seed, lower_seed)
        away = lower_seed if home == higher_seed else higher_seed
        result = _sim_game(
            home, away, ratings,
            k_playoff=k_playoff, home_bump=home_bump, rng=rng,
        )
        if result.winner == higher_seed:
            wins_h += 1
        else:
            wins_l += 1
        next_game += 1
    return higher_seed if wins_h >= 4 else lower_seed


# ---- Bracket structure -------------------------------------------------------

@dataclass
class BracketNode:
    """One series slot in the bracket. Once both `a` and `b` are known (either
    set up front or filled in by a previous round's winner), the series can
    be simulated. `state` carries any in-progress wins/games_played; for
    not-yet-started series it's the trivial zero state.
    """
    a: str | None = None
    b: str | None = None
    higher_seed: str | None = None
    wins_a_start: int = 0
    wins_b_start: int = 0
    games_played_start: int = 0
    winner: str | None = None  # set after sim


def _bracket_from_state(
    state: PlayoffState,
    standings: dict[str, Standing],
) -> tuple[list[BracketNode], list[BracketNode], BracketNode]:
    """Build the (CF slots, R2 slots, SCF slot) data structure that the sim
    walks. R1 is omitted — by current Cup-sim scope, the regular season is
    over and Round 1 has been fully played, so no R1 simulation is needed.

    Returns (east_cf, west_cf, scf) where east_cf and west_cf are lists of
    BracketNode objects (one CF series per conference).
    """
    # ---- Conference assignments per active R2 series ----
    r2_by_conference: dict[str, list[Series]] = {"East": [], "West": []}
    for s in state.round2_series:
        conf = conference_of(s.team_a)
        # Sanity: both teams should be in the same conference.
        if conference_of(s.team_b) != conf:
            raise ValueError(f"R2 series {s.team_a}-{s.team_b} spans conferences")
        r2_by_conference[conf].append(s)

    r2_nodes: list[BracketNode] = []
    for series in (*state.round2_series,):
        if series.is_complete:
            node = BracketNode(
                a=series.team_a, b=series.team_b,
                higher_seed=series.higher_seed,
                wins_a_start=series.wins_a, wins_b_start=series.wins_b,
                games_played_start=series.games_completed,
                winner=series.winner,
            )
        else:
            node = BracketNode(
                a=series.team_a, b=series.team_b,
                higher_seed=series.higher_seed,
                wins_a_start=series.wins_a, wins_b_start=series.wins_b,
                games_played_start=series.games_completed,
            )
        r2_nodes.append(node)

    # ---- Build CF slots (one per conference) ----
    east_cf: list[BracketNode] = []
    west_cf: list[BracketNode] = []
    for conf, series_list in r2_by_conference.items():
        # If both R2 series for this conference are already complete we know
        # the CF participants up front; otherwise we'll resolve them after
        # each sim plays the in-progress R2 series.
        cf_node = BracketNode()
        slot = east_cf if conf == "East" else west_cf
        slot.append(cf_node)

    # Any CF series already played (rare — only if we're mid-CF or later).
    for series in state.cf_series:
        conf = conference_of(series.team_a)
        target = east_cf[0] if conf == "East" else west_cf[0]
        target.a = series.team_a
        target.b = series.team_b
        target.higher_seed = series.higher_seed
        target.wins_a_start = series.wins_a
        target.wins_b_start = series.wins_b
        target.games_played_start = series.games_completed
        target.winner = series.winner

    # ---- SCF slot ----
    scf = BracketNode()
    for series in state.scf_series:
        scf.a = series.team_a
        scf.b = series.team_b
        scf.higher_seed = series.higher_seed
        scf.wins_a_start = series.wins_a
        scf.wins_b_start = series.wins_b
        scf.games_played_start = series.games_completed
        scf.winner = series.winner

    return east_cf, west_cf, scf, r2_nodes


# ---- Higher seed resolution --------------------------------------------------

def _pick_higher_seed(team_a: str, team_b: str, standings: dict[str, Standing]) -> str:
    """For not-yet-started series, the higher seed (Game 1 home) is the team
    with more regular-season points. Falls back to alphabetical for ties
    (rare in practice and immaterial to Cup probabilities at this scale).
    """
    a_pts = standings.get(team_a, Standing(team_a, 0, 0, 0, 0)).points
    b_pts = standings.get(team_b, Standing(team_b, 0, 0, 0, 0)).points
    if a_pts != b_pts:
        return team_a if a_pts > b_pts else team_b
    return min(team_a, team_b)


# ---- Single sim run ----------------------------------------------------------

def _run_one_sim(
    state: PlayoffState,
    standings: dict[str, Standing],
    starting_ratings: dict[str, float],
    *,
    k_playoff: float,
    home_bump: float,
    rng: random.Random,
) -> str:
    """Play out the remainder of the playoffs once and return the Cup winner."""
    if state.cup_champion is not None:
        return state.cup_champion

    east_cf, west_cf, scf, r2_nodes = _bracket_from_state(state, standings)
    ratings = dict(starting_ratings)  # local copy mutated per game

    # ---- Round 2: finish any in-progress / not-yet-started series ----
    r2_winners_by_conf: dict[str, list[str]] = {"East": [], "West": []}
    for node in r2_nodes:
        if node.winner is None:
            assert node.a and node.b and node.higher_seed
            lower = node.b if node.higher_seed == node.a else node.a
            winner = _sim_series(
                node.higher_seed, lower,
                wins_higher_start=node.wins_a_start if node.higher_seed == node.a else node.wins_b_start,
                wins_lower_start=node.wins_b_start if node.higher_seed == node.a else node.wins_a_start,
                games_played_start=node.games_played_start,
                ratings=ratings, k_playoff=k_playoff,
                home_bump=home_bump, rng=rng,
            )
            node.winner = winner
        r2_winners_by_conf[conference_of(node.winner)].append(node.winner)

    # ---- Conference Finals ----
    cf_winners: list[str] = []
    for conf, slot in (("East", east_cf), ("West", west_cf)):
        node = slot[0]
        if node.winner is None:
            # Determine matchup if not already known.
            if node.a is None or node.b is None:
                winners = r2_winners_by_conf[conf]
                if len(winners) != 2:
                    raise ValueError(
                        f"{conf} CF expected 2 R2 winners, got {winners}"
                    )
                node.a, node.b = winners
                node.higher_seed = _pick_higher_seed(node.a, node.b, standings)
            lower = node.b if node.higher_seed == node.a else node.a
            winner = _sim_series(
                node.higher_seed, lower,
                wins_higher_start=node.wins_a_start if node.higher_seed == node.a else node.wins_b_start,
                wins_lower_start=node.wins_b_start if node.higher_seed == node.a else node.wins_a_start,
                games_played_start=node.games_played_start,
                ratings=ratings, k_playoff=k_playoff,
                home_bump=home_bump, rng=rng,
            )
            node.winner = winner
        cf_winners.append(node.winner)

    # ---- Stanley Cup Final ----
    if scf.winner is not None:
        return scf.winner
    if scf.a is None or scf.b is None:
        scf.a, scf.b = cf_winners
        scf.higher_seed = _pick_higher_seed(scf.a, scf.b, standings)
    lower = scf.b if scf.higher_seed == scf.a else scf.a
    return _sim_series(
        scf.higher_seed, lower,
        wins_higher_start=scf.wins_a_start if scf.higher_seed == scf.a else scf.wins_b_start,
        wins_lower_start=scf.wins_b_start if scf.higher_seed == scf.a else scf.wins_a_start,
        games_played_start=scf.games_played_start,
        ratings=ratings, k_playoff=k_playoff,
        home_bump=home_bump, rng=rng,
    )


# ---- Top-level orchestration -------------------------------------------------

@dataclass
class CupSimResult:
    simulated_at: str  # ISO timestamp
    n_simulations: int
    wall_seconds: float
    state_round: int  # current round when the sim was run (1-5)
    playoff_field: list[str]
    eliminated: list[str]
    alive: list[str]
    in_progress_series: list[str]  # e.g. ["BUF vs MTL @ 3-3"]
    cup_probabilities: dict[str, float]  # team_code -> probability


def simulate_cup(
    state: PlayoffState,
    standings: dict[str, Standing],
    current_ratings_by_team: dict[str, float],
    *,
    k_playoff: float,
    home_bump: float,
    n_simulations: int = 10_000,
    seed: int | None = None,
) -> CupSimResult:
    """Run `n_simulations` independent playoff simulations and return per-team
    Cup probabilities.

    `current_ratings_by_team` is a `{team_code: rating}` mapping — typically
    derived from `historical.current_active_ratings_with_codes()` so only the
    active 32 franchises are represented. Defunct franchises are not in the
    playoff field by definition.
    """
    rng = random.Random(seed)
    t0 = time.time()

    counts: Counter[str] = Counter()
    for _ in range(n_simulations):
        champion = _run_one_sim(
            state, standings, current_ratings_by_team,
            k_playoff=k_playoff, home_bump=home_bump, rng=rng,
        )
        counts[champion] += 1

    cup_probs: dict[str, float] = {}
    for team in state.playoff_field:
        cup_probs[team] = round(counts[team] / n_simulations, 4)

    in_progress = [
        f"{s.team_a} vs {s.team_b} @ {s.wins_a}-{s.wins_b}"
        for s in state.all_series() if s.is_in_progress
    ]

    from datetime import datetime, timezone
    return CupSimResult(
        simulated_at=datetime.now(timezone.utc).isoformat(),
        n_simulations=n_simulations,
        wall_seconds=round(time.time() - t0, 2),
        state_round=state.current_round,
        playoff_field=state.playoff_field,
        eliminated=state.eliminated,
        alive=state.alive,
        in_progress_series=in_progress,
        cup_probabilities=cup_probs,
    )


# ---- Convenience adapter for the API layer ----------------------------------

def ratings_by_team_code(active_with_codes: list[tuple[str, str, float]]) -> dict[str, float]:
    """Convert `historical.current_active_ratings_with_codes()`'s output
    (`[(code, franchise_id, rating), ...]`) into `{code: rating}` for the sim.
    """
    return {code: rating for code, _, rating in active_with_codes}
