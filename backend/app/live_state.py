"""Live in-game state extraction from the NHL play-by-play feed — v2.3 §16.

For a game whose `gameState` is LIVE or CRIT, this module fetches the current
play-by-play, picks out the latest play's `(period, time remaining)`, and
sums home/away scores from goal events. The output feeds directly into the
v2.2 `live_wp` lookup.

Failure is contained: if the fetch errors or the payload is malformed, this
module returns `None` and the caller (engine.todays_matchups) falls back to
the pre-game WP only. A single bad game must not break `/games/today`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

BASE = "https://api-web.nhle.com/v1"
HTTP_TIMEOUT = 8.0  # tighter than the historical pipeline; live calls block the request

LIVE_STATES = {"LIVE", "CRIT"}
PREGAME_STATES = {"FUT", "PRE"}
COMPLETED_STATES = {"FINAL", "OFF"}


@dataclass(frozen=True)
class LiveState:
    game_state: str  # raw NHL state string
    period: int  # 1, 2, 3, or 4 (any OT/SO bucketed to 4)
    time_remaining_s: int
    home_score: int
    away_score: int

    @property
    def is_live(self) -> bool:
        return self.game_state in LIVE_STATES

    @property
    def score_diff(self) -> int:
        return self.home_score - self.away_score


def _mmss_to_seconds(s: str) -> int:
    if not s or ":" not in s:
        return 0
    try:
        mm, ss = s.split(":")
        return int(mm) * 60 + int(ss)
    except (ValueError, TypeError):
        return 0


def _period_bucket(period_number: int, period_type: str) -> int:
    if period_type in ("OT", "SO"):
        return 4
    if period_number in (1, 2, 3):
        return period_number
    return 4


def parse_live_state(payload: dict[str, Any]) -> LiveState | None:
    """Pull (period, time_remaining_s, home_score, away_score, game_state) out
    of a play-by-play payload. Returns None if the payload doesn't contain
    enough to reconstruct a live state.
    """
    game_state = payload.get("gameState")
    if not game_state:
        return None

    plays = payload.get("plays") or []

    # Score: scan all goal events, take the max-after values from each side.
    home_score = 0
    away_score = 0
    for p in plays:
        if p.get("typeDescKey") != "goal":
            continue
        details = p.get("details") or {}
        h = details.get("homeScore")
        a = details.get("awayScore")
        if isinstance(h, int) and h > home_score:
            home_score = h
        if isinstance(a, int) and a > away_score:
            away_score = a

    # Period + time remaining: take the latest play that has the field.
    period = 1
    time_remaining_s = 20 * 60  # default to "game just started" if no plays
    for p in reversed(plays):
        pd = p.get("periodDescriptor") or {}
        n = pd.get("number")
        ptype = pd.get("periodType") or "REG"
        if not isinstance(n, int):
            continue
        period = _period_bucket(n, ptype)
        tr = p.get("timeRemaining")
        if tr:
            time_remaining_s = _mmss_to_seconds(tr)
        break

    # If a completed game's payload comes through here, normalize time_remaining_s to 0.
    if game_state in COMPLETED_STATES:
        time_remaining_s = 0

    return LiveState(
        game_state=game_state,
        period=period,
        time_remaining_s=time_remaining_s,
        home_score=home_score,
        away_score=away_score,
    )


async def fetch_live_state(client: httpx.AsyncClient, game_id: int) -> LiveState | None:
    """One-shot fetch + parse. Returns None on any HTTP / parse failure."""
    try:
        r = await client.get(
            f"{BASE}/gamecenter/{game_id}/play-by-play",
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        return parse_live_state(r.json())
    except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError):
        return None
