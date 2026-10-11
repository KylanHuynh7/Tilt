"""MLB Elo + starting-pitcher adjustment (methodology/MLB.md §5, v1.1).

    P(home) = expected(R_home + A_home, R_away + A_away, home_bump = H unless neutral)
    R_new   = R + K × M × (W − P),   W ∈ {1, 0.5, 0}
    M       = ln(|MOV| + 1) × 2.2 / (0.001 × D + 2.2)   (mov on; ties M = 1)
    A       = c × (rGS_pitcher − rGS_team)
    game score = 47.4 + 1.5·outs + K − 2·BB − 2·H − 3·R − 4·HR     (FiveThirtyEight)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core import elo

INITIAL_RATING = 1500.0
LEAGUE_MEAN = 1500.0
INITIAL_GAME_SCORE = 50.0


@dataclass(frozen=True)
class Params:
    k_regular: float = 4.0
    k_playoff: float = 4.0
    carry: float = 0.6
    home_bump: float = 25.0
    mov: bool = True
    c: float = 4.7        # pitcher adjustment scale (c = 0 → team-only Elo)
    alpha: float = 0.1    # EWMA weight of the newest start in rGS


def game_score(outs: int, k: int, bb: int, h: int, r: int, hr: int) -> float:
    return 47.4 + 1.5 * outs + k - 2 * bb - 2 * h - 3 * r - 4 * hr


def outcome(home: int, away: int) -> float:
    return 0.5 if home == away else (1.0 if home > away else 0.0)


def mov_multiplier(margin: int, winner_diff: float) -> float:
    return math.log(abs(margin) + 1) * 2.2 / (0.001 * winner_diff + 2.2)


def win_probability(r_home: float, r_away: float, *, a_home: float = 0.0, a_away: float = 0.0,
                    home_bump: float, neutral: bool) -> float:
    return elo.expected(r_home + a_home, r_away + a_away, home_bump=0.0 if neutral else home_bump)


def update(r_home: float, r_away: float, *, home_score: int, away_score: int, k: float,
           p_home: float, eff_diff_home: float, mov: bool) -> tuple[float, float]:
    """`eff_diff_home` = home effective rating − away effective rating (bump and
    pitcher terms included), used as D for the winner.
    """
    w = outcome(home_score, away_score)
    m = 1.0
    if mov and w != 0.5:
        m = mov_multiplier(home_score - away_score, eff_diff_home if w == 1.0 else -eff_diff_home)
    delta = k * m * (w - p_home)
    return r_home + delta, r_away - delta


def regress(rating: float, carry: float) -> float:
    return elo.regress(rating, carry=carry, mean=LEAGUE_MEAN)
