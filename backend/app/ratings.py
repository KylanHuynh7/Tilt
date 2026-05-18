"""Elo-variant rating engine per METHODOLOGY.md §§4-5 (with v2.0 home-ice).

Primitives:
  - win_probability(R_home, R_away, home_bump=0)  §5 + §12 win-prob formula
  - apply_game(R_a, R_b, outcome, ...)            §5 single-game update
  - apply_decay(rating, carry)                    §4 between-season regression
  - classify_outcome(...)                         §5 + v1.1 tie handling

The constants are the v1.0 starting values; K_REGULAR, K_PLAYOFF, the OT/SO
weights, DECAY_CARRY, and HOME_BUMP_DEFAULT are tunable during validation and
frozen before any test-set evaluation.

`home_bump` is the v2.0 addition. A value of 0 reproduces the v1 behavior
exactly; positive values bias predictions toward the home team in Elo points.
The v1 model is locked at home_bump=0 — see §10 #2.
"""

from dataclasses import dataclass
from typing import Literal

INITIAL_RATING: float = 1500.0
LEAGUE_MEAN: float = 1500.0
DIVISOR: float = 400.0

K_REGULAR: float = 6.0
K_PLAYOFF: float = 10.0  # uniform across all playoff games per v1.1 Section 5

DECAY_CARRY: float = 0.75  # §4: R_new = mean + carry * (R - mean)

# v2.0 §12: rating-point bias applied to the home team's effective rating in
# `win_probability`. 0.0 = v1 behavior (neutral ice). Tuned during v2
# validation; the v2 grid sweeps {0, 20, 40, 60, 80, 100}.
HOME_BUMP_DEFAULT: float = 0.0

# Tie outcomes are only valid in seasons before the shootout (introduced
# 2005-06). The classifier enforces this; the engine should never see a TIE
# label outside the historical era.
TIE_ERA_END: int = 20052006  # first season where TIE must be unreachable

# Outcome weights per METHODOLOGY.md v1.1 §5.
Outcome = Literal[
    "REG_WIN", "OT_WIN", "SO_WIN", "TIE", "SO_LOSS", "OT_LOSS", "REG_LOSS"
]
OUTCOME_WEIGHTS: dict[Outcome, float] = {
    "REG_WIN":  1.00,
    "OT_WIN":   0.75,
    "SO_WIN":   0.65,
    "TIE":      0.50,
    "SO_LOSS":  0.35,
    "OT_LOSS":  0.25,
    "REG_LOSS": 0.00,
}


def win_probability(
    rating_a: float,
    rating_b: float,
    *,
    home_bump: float = HOME_BUMP_DEFAULT,
) -> float:
    """P(A wins) per the Elo formula in §5, with the v2.0 §12 home-ice bump.

    Semantically `rating_a` is the home team and `rating_b` is the away team.
    The bump is added to `rating_a`'s effective rating before computing the
    Elo gap. To get the away team's perspective, compute `1 - this value`
    rather than swapping arguments — swapping would incorrectly attribute
    the home-ice advantage to the away team.

    `home_bump = 0.0` exactly reproduces the v1 (neutral-ice) behavior, so
    callers that don't model home ice (e.g. `ratings.apply_game` in test
    paths) can ignore this argument. The v1 frozen model is locked at
    home_bump=0 per §10 #2.
    """
    effective_gap = (rating_b - rating_a - home_bump) / DIVISOR
    return 1.0 / (1.0 + 10.0 ** effective_gap)


@dataclass
class RatingUpdate:
    new_rating_a: float
    new_rating_b: float


def apply_game(
    rating_a: float,
    rating_b: float,
    outcome_a: Outcome,
    *,
    is_playoff: bool = False,
) -> RatingUpdate:
    """Apply one game's result to both teams' ratings.

    `outcome_a` is the result from team A's perspective; team B's outcome and
    weight are inferred as the symmetric complement so both teams' updates sum
    to zero and the league mean stays at 1500 by construction.
    """
    k = K_PLAYOFF if is_playoff else K_REGULAR
    w_a = OUTCOME_WEIGHTS[outcome_a]
    w_b = 1.0 - w_a  # symmetric by construction; TIE → 0.5/0.5
    p_a = win_probability(rating_a, rating_b)
    p_b = 1.0 - p_a
    return RatingUpdate(
        new_rating_a=rating_a + k * (w_a - p_a),
        new_rating_b=rating_b + k * (w_b - p_b),
    )


def apply_decay(rating: float, *, carry: float = DECAY_CARRY) -> float:
    """Between-season regression to the league mean (§4).

        R_new = 1500 + carry * (R - 1500)

    Expansion teams (with no prior rating) should be initialized at 1500 and
    must NOT have decay applied — that's a caller-side rule, not enforced here.
    """
    return LEAGUE_MEAN + carry * (rating - LEAGUE_MEAN)


def classify_outcome(
    *,
    home_score: int,
    away_score: int,
    period_type: str | None,
    season_id: int,
    perspective: Literal["home", "away"],
) -> Outcome:
    """Map a completed game row to an Outcome label from one team's POV.

    Rules:
      - period_type is one of "REG", "OT", "SO", or None.
      - Equal scores in regulation imply a tie. Ties are only valid in
        pre-2005-06 seasons (TIE_ERA_END); from 2005-06 onward equal regulation
        scores cannot exist — the shootout always decides — so the caller has
        a data integrity bug if this branch fires.
      - Unknown period_type falls back to regulation handling; better to fail
        loud (wrong outcome label) than silent (game skipped).
    """
    if home_score == away_score:
        if season_id >= TIE_ERA_END:
            raise ValueError(
                f"equal scores ({home_score}-{away_score}) in season {season_id}; "
                "ties are impossible post-2005-06"
            )
        return "TIE"

    home_won = home_score > away_score
    won = home_won if perspective == "home" else not home_won
    period = (period_type or "REG").upper()
    if period == "REG":
        return "REG_WIN" if won else "REG_LOSS"
    if period == "OT":
        return "OT_WIN" if won else "OT_LOSS"
    if period == "SO":
        return "SO_WIN" if won else "SO_LOSS"
    # Unrecognized period type — treat as regulation. The unit tests cover
    # the known values; this branch exists to keep the engine moving on the
    # rare malformed historical row.
    return "REG_WIN" if won else "REG_LOSS"
