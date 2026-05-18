"""NHL season ID helpers.

The NHL identifies a season by an 8-digit integer like 20232024 (the 2023-24
season). The authoritative list is exposed by `/v1/season`; we mirror it here
with a tiny hand-maintained fallback so unit tests don't need network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx

# Hardcoded fallback used when /v1/season is unreachable. Every consecutive
# season from 1917-18 through 2025-26 except 2004-05 (cancelled by lockout).
# Kept in sync with the methodology's "108 seasons" figure (Section 3).
_KNOWN_SEASONS: list[int] = (
    [y * 10000 + (y + 1) for y in range(1917, 2026) if y != 2004]
)

CUTOFF_PRE_1967 = 19671968  # first modern-era season; see §3 and §4


@dataclass(frozen=True)
class Season:
    season_id: int  # e.g. 20232024
    start_year: int  # 2023
    end_year: int  # 2024

    @property
    def is_pre_1967(self) -> bool:
        return self.season_id < CUTOFF_PRE_1967

    @property
    def label(self) -> str:
        return f"{self.start_year}-{str(self.end_year)[-2:]}"


def parse(season_id: int) -> Season:
    s = int(season_id)
    if s < 10000000 or s > 99999999:
        raise ValueError(f"invalid season id: {season_id}")
    start, end = s // 10000, s % 10000
    if end != start + 1:
        raise ValueError(f"non-consecutive season years in {season_id}")
    return Season(season_id=s, start_year=start, end_year=end)


def date_range(season_id: int, today: date | None = None) -> tuple[date, date]:
    """Inclusive date window covering everything from the season's first possible
    preseason game through the latest possible Cup Final date.

    Sept 1 → Jul 31 is a safe overshoot. Empty days at the edges are cheap and
    keep us schedule-independent. For the in-progress current season the upper
    bound is clamped to `today` to avoid pointless future-date calls.
    """
    s = parse(season_id)
    start = date(s.start_year, 9, 1)
    end = date(s.end_year, 7, 31)
    if today is not None and end > today:
        end = today
    return start, end


async def fetch_all_season_ids(client: httpx.AsyncClient) -> list[int]:
    resp = await client.get("https://api-web.nhle.com/v1/season", timeout=10.0)
    resp.raise_for_status()
    ids = sorted(int(x) for x in resp.json())
    return ids


def known_season_ids() -> list[int]:
    """Offline fallback list — used by tests and as a bootstrap if the API is down."""
    return list(_KNOWN_SEASONS)
