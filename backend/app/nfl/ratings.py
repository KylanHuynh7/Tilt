"""NFL Elo update rule (methodology/NFL.md §5).

    P(home)  = core.elo.expected(R_home, R_away, home_bump = H if not neutral else 0)
    R_new    = R + K × M × (W − P)              W ∈ {1, 0.5, 0}
    M        = ln(|MOV| + 1) × 2.2 / (0.001 × D + 2.2)   when mov is on
    D        = R_winner − R_loser, home bump on whichever side had it
    ties     → M = 1 (ln(1) = 0 would freeze ratings on a tie)

The MOV constants are FiveThirtyEight's NFL values, fixed by §5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core import elo

INITIAL_RATING = 1500.0
LEAGUE_MEAN = 1500.0


@dataclass(frozen=True)
class Params:
    k_regular: float = 20.0
    k_playoff: float = 20.0
    carry: float = 0.67
    home_bump: float = 50.0
    mov: bool = True


def win_probability(r_home: float, r_away: float, *, home_bump: float, neutral: bool) -> float:
    return elo.expected(r_home, r_away, home_bump=0.0 if neutral else home_bump)


def mov_multiplier(margin: int, winner_diff: float) -> float:
    return math.log(abs(margin) + 1) * 2.2 / (0.001 * winner_diff + 2.2)


def outcome(home_score: int, away_score: int) -> float:
    if home_score == away_score:
        return 0.5
    return 1.0 if home_score > away_score else 0.0


def update(
    r_home: float, r_away: float, *, home_score: int, away_score: int,
    k: float, home_bump: float, neutral: bool, mov: bool,
) -> tuple[float, float, float]:
    """Apply one game. Returns (new_home, new_away, pre-game P(home))."""
    bump = 0.0 if neutral else home_bump
    p_home = elo.expected(r_home, r_away, home_bump=bump)
    w = outcome(home_score, away_score)
    m = 1.0
    if mov and w != 0.5:
        eff_home = r_home + bump
        winner_diff = (eff_home - r_away) if w == 1.0 else (r_away - eff_home)
        m = mov_multiplier(home_score - away_score, winner_diff)
    delta = k * m * (w - p_home)
    return r_home + delta, r_away - delta, p_home


def regress(rating: float, carry: float) -> float:
    return elo.regress(rating, carry=carry, mean=LEAGUE_MEAN)
