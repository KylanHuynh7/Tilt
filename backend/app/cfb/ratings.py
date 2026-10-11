"""College football rating rule (methodology/CFB.md §5): the NFL Elo form
exactly (neutral-aware home bump, W ∈ {1, 0.5, 0}, FiveThirtyEight MOV with
ties at M = 1), plus the pooled-FCS parameters.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nfl.ratings import outcome, regress, update, win_probability  # noqa: F401  (same approved form)

FCS = "FCS"   # the pooled opponent key


@dataclass(frozen=True)
class Params:
    k_regular: float = 30.0
    k_post: float = 20.0
    carry: float = 0.5
    home_bump: float = 60.0
    mov: bool = True
    fcs_init: float = 1200.0
