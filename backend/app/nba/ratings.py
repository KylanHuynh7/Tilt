"""NBA Elo update rule (methodology/NBA.md §5).

    P(home)  = core.elo.expected(R_home, R_away, home_bump = H if not neutral else 0)
    R_new    = R + K × M × (W − P)          W ∈ {0, 1}
    M        = (|MOV| + 3)^0.8 / (7.5 + 0.006 × D)   when mov is on, else 1
    D        = R_winner − R_loser, with the home bump on whichever side had it

The MOV constants (3, 0.8, 7.5, 0.006) are fixed by §5, not tuned.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import elo

INITIAL_RATING = 1500.0
LEAGUE_MEAN = 1500.0

MOV_OFFSET = 3.0
MOV_EXPONENT = 0.8
MOV_BASE = 7.5
MOV_DIFF_SCALE = 0.006


@dataclass(frozen=True)
class Params:
    k_regular: float = 20.0
    k_playoff: float = 20.0
    carry: float = 0.75
    home_bump: float = 100.0
    mov: bool = True


def win_probability(r_home: float, r_away: float, *, home_bump: float, neutral: bool) -> float:
    return elo.expected(r_home, r_away, home_bump=0.0 if neutral else home_bump)


def mov_multiplier(margin: int, winner_diff: float) -> float:
    """§5 margin-of-victory multiplier. `winner_diff` is the winner's
    effective rating minus the loser's (home bump included), so a favorite
    winning big gets a damped update.
    """
    return (abs(margin) + MOV_OFFSET) ** MOV_EXPONENT / (MOV_BASE + MOV_DIFF_SCALE * winner_diff)


def update(
    r_home: float,
    r_away: float,
    *,
    home_score: int,
    away_score: int,
    k: float,
    home_bump: float,
    neutral: bool,
    mov: bool,
) -> tuple[float, float, float]:
    """Apply one game. Returns (new_home, new_away, pre-game P(home))."""
    bump = 0.0 if neutral else home_bump
    p_home = elo.expected(r_home, r_away, home_bump=bump)
    home_won = home_score > away_score
    w = 1.0 if home_won else 0.0
    m = 1.0
    if mov:
        eff_home = r_home + bump
        winner_diff = (eff_home - r_away) if home_won else (r_away - eff_home)
        m = mov_multiplier(home_score - away_score, winner_diff)
    delta = k * m * (w - p_home)
    return r_home + delta, r_away - delta, p_home


def regress(rating: float, carry: float) -> float:
    return elo.regress(rating, carry=carry, mean=LEAGUE_MEAN)
