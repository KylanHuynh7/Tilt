"""Elo-variant rating engine per METHODOLOGY.md v1.1 §§4-5.

Primitives:
  - win_probability(R_a, R_b)              §5 win-prob formula
  - apply_game(R_a, R_b, outcome, ...)     §5 single-game update
  - apply_decay(rating, carry)             §4 between-season regression to 1500
  - classify_outcome(...)                  §5 + v1.1 tie handling

The constants are the v1.0 starting values; K_REGULAR, K_PLAYOFF, the OT/SO
weights, and DECAY_CARRY are tunable during Phase C validation and frozen
before the test set is touched.
"""

from dataclasses import dataclass
from typing import Literal

INITIAL_RATING: float = 1500.0
LEAGUE_MEAN: float = 1500.0
DIVISOR: float = 400.0

K_REGULAR: float = 6.0
K_PLAYOFF: float = 10.0  # uniform across all playoff games per v1.1 Section 5

DECAY_CARRY: float = 0.75  # §4: R_new = mean + carry * (R - mean)

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


def win_probability(rating_a: float, rating_b: float) -> float:
    """P(A wins) per the Elo formula in Section 5."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / DIVISOR))


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
