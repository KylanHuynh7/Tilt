"""Elo primitives shared across sports.

    expected(R_home, R_away, home_bump) = 1 / (1 + 10^((R_away - R_home - home_bump) / divisor))
    regress(R, carry, mean)             = mean + carry * (R - mean)

These are the formulas in NHL METHODOLOGY.md §5 / §12 / §4, written without
any hockey-specific constants so other sports can reuse them.
"""

from __future__ import annotations

DEFAULT_DIVISOR: float = 400.0


def expected(
    rating_home: float,
    rating_away: float,
    *,
    home_bump: float = 0.0,
    divisor: float = DEFAULT_DIVISOR,
) -> float:
    """P(home wins). The bump is added to the home side's effective rating;
    for the away side's probability use `1 - expected(...)`, never swap args.
    """
    return 1.0 / (1.0 + 10.0 ** ((rating_away - rating_home - home_bump) / divisor))


def regress(rating: float, *, carry: float, mean: float) -> float:
    """Between-season regression toward the league mean."""
    return mean + carry * (rating - mean)
