"""Derive regular-season standings and playoff bracket state from the parquet.

Used by the v2.1 Cup simulator (§14) to know:
  - what the playoff field is (the 16 teams that played a Round 1 game),
  - which teams are still alive vs eliminated,
  - which series are in progress and at what score,
  - what the next-round matchups will be once in-progress series finish.

The bracket structure is read from the actual data (the empirical Round 1
matchups define the bracket tree), not re-derived from divisional seeding.
This is simpler and robust to the NHL's bracket-format changes over the years.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

import pyarrow.parquet as pq
import pyarrow.compute as pc

from . import pipeline

REGULAR = 2
PLAYOFF = 3

# 2 points per regulation/OT/SO win; 1 point for OT loss or SO loss (per NHL
# point system since 2005-06). The Cup-sim consumer only uses points as a
# tiebreaker for home-ice within a series, so this is good enough.
POINTS_WIN = 2
POINTS_OT_LOSS = 1


@dataclass(frozen=True)
class Standing:
    team: str
    wins: int
    losses: int  # regulation losses
    ot_losses: int  # combined OT + SO losses (point-eligible)
    points: int


@dataclass
class Series:
    """One best-of-7 playoff series.

    `team_a` and `team_b` are the two participants. Wins are tracked per team.
    `higher_seed` is the team that hosted Game 1 — used to assign home ice for
    any remaining games per the 2-2-1-1-1 pattern. If the series is over,
    `winner` is set.
    """

    team_a: str
    team_b: str
    games_completed: int
    wins_a: int
    wins_b: int
    higher_seed: str  # the team that had Game 1 at home
    winner: str | None = None  # None if in progress

    @property
    def is_complete(self) -> bool:
        return self.winner is not None

    @property
    def is_in_progress(self) -> bool:
        return self.winner is None and self.games_completed > 0

    def opponent_of(self, team: str) -> str:
        if team == self.team_a:
            return self.team_b
        if team == self.team_b:
            return self.team_a
        raise ValueError(f"{team!r} not in this series")


@dataclass
class PlayoffState:
    """Snapshot of the 2025-26 playoff bracket at the moment of derivation."""

    season_id: int
    playoff_field: list[str] = field(default_factory=list)
    round1_series: list[Series] = field(default_factory=list)
    round2_series: list[Series] = field(default_factory=list)
    cf_series: list[Series] = field(default_factory=list)
    scf_series: list[Series] = field(default_factory=list)
    eliminated: list[str] = field(default_factory=list)
    alive: list[str] = field(default_factory=list)
    cup_champion: str | None = None  # set if SCF complete

    @property
    def current_round(self) -> int:
        """1, 2, 3 (CF), or 4 (SCF). 0 = playoffs not started; 5 = Cup awarded."""
        if self.cup_champion is not None:
            return 5
        if self.scf_series:
            return 4
        if self.cf_series:
            return 3
        if self.round2_series:
            return 2
        if self.round1_series:
            return 1
        return 0

    def all_series(self) -> list[Series]:
        return [
            *self.round1_series, *self.round2_series,
            *self.cf_series, *self.scf_series,
        ]


# ---- Loading helpers ----------------------------------------------------------


def _load_season(season_id: int):
    path = pipeline.RAW_DIR / f"{season_id}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"missing parquet for season {season_id}")
    return pq.read_table(path)


def compute_standings(season_id: int) -> dict[str, Standing]:
    """Walk the regular-season games for one season and tally W / L / OT-L / pts.

    Skips games that haven't been played yet (state not in OFF/FINAL) so the
    standings reflect "what we know so far" rather than projected schedules.
    """
    t = _load_season(season_id)
    reg = t.filter(pc.equal(t.column("game_type"), REGULAR))

    wins: Counter[str] = Counter()
    losses: Counter[str] = Counter()
    ot_losses: Counter[str] = Counter()
    teams: set[str] = set()

    for r in reg.to_pylist():
        if r["state"] not in ("OFF", "FINAL"):
            continue
        if r["home_score"] is None or r["away_score"] is None:
            continue
        home, away = r["home"], r["away"]
        teams.add(home)
        teams.add(away)
        if r["home_score"] > r["away_score"]:
            winner, loser = home, away
        else:
            winner, loser = away, home
        wins[winner] += 1
        # NHL's "loser point" system: any non-regulation loss gives 1 point.
        if r["period_type"] in ("OT", "SO"):
            ot_losses[loser] += 1
        else:
            losses[loser] += 1

    out: dict[str, Standing] = {}
    for team in teams:
        w = wins[team]
        l = losses[team]
        ol = ot_losses[team]
        out[team] = Standing(
            team=team,
            wins=w,
            losses=l,
            ot_losses=ol,
            points=POINTS_WIN * w + POINTS_OT_LOSS * ol,
        )
    return out


# ---- Playoff state derivation -------------------------------------------------


def _group_series_games(playoff_rows: list[dict]) -> dict[frozenset, list[dict]]:
    """Group all playoff games by team pair, preserving chronological order."""
    series: dict[frozenset, list[dict]] = defaultdict(list)
    for r in sorted(playoff_rows, key=lambda r: (r["game_date"], r["game_id"])):
        if r["state"] not in ("OFF", "FINAL"):
            continue
        if r["home_score"] is None or r["away_score"] is None:
            continue
        series[frozenset({r["home"], r["away"]})].append(r)
    return series


def _build_series(games: list[dict]) -> Series:
    if not games:
        raise ValueError("series with no games")
    first = games[0]
    higher_seed = first["home"]  # Game 1 is at the higher seed's arena
    other = first["away"]
    wins: Counter[str] = Counter()
    for g in games:
        winner = g["home"] if g["home_score"] > g["away_score"] else g["away"]
        wins[winner] += 1
    w_a = wins[higher_seed]
    w_b = wins[other]
    winner: str | None = None
    if w_a >= 4:
        winner = higher_seed
    elif w_b >= 4:
        winner = other
    return Series(
        team_a=higher_seed,
        team_b=other,
        games_completed=len(games),
        wins_a=w_a,
        wins_b=w_b,
        higher_seed=higher_seed,
        winner=winner,
    )


def _opponents_in_round(
    series_set: list[Series],
    winners: set[str],
) -> list[Series]:
    """Among `series_set`, return the ones whose participants are both in
    `winners`. Used to identify which series belong to a given round.
    """
    return [
        s for s in series_set
        if {s.team_a, s.team_b} <= winners
    ]


def derive_playoff_state(season_id: int) -> PlayoffState:
    """Reconstruct the bracket from the parquet's playoff games.

    Algorithm (chronology-based, replaces an earlier subset-based version
    that mis-bucketed CF/SCF series as R2 once all rounds had played out
    — R1 winners are technically in every later round too, so subset
    membership alone can't distinguish rounds):

      1. Group games into series by team-pair.
      2. Sort series by first-game date (earliest first).
      3. The first 8 = R1, next 4 = R2, next 2 = CF, last 1 = SCF.
         Modern NHL bracket has exactly 15 series; partial-season states
         bucket whatever is present.
      4. A series can be "in progress" — recorded but with winner=None.
      5. For pre-modern eras with different bracket formats, the buckets
         may not cleanly fit; documented in §13.J as a known limitation.
    """
    t = _load_season(season_id)
    po = t.filter(pc.equal(t.column("game_type"), PLAYOFF))
    rows = po.to_pylist()
    grouped = _group_series_games(rows)
    if not grouped:
        return PlayoffState(season_id=season_id)

    # Build series with their first-game date so we can sort chronologically.
    series_with_start: list[tuple[date, Series]] = []
    for teams, games in grouped.items():
        s = _build_series(games)
        series_with_start.append((games[0]["game_date"], s))
    series_with_start.sort(key=lambda x: x[0])
    ordered_series = [s for _, s in series_with_start]

    # Bucket by round per the modern bracket layout (8 / 4 / 2 / 1).
    round1 = ordered_series[:8]
    round2 = ordered_series[8:12]
    cf = ordered_series[12:14]
    scf = ordered_series[14:15]

    # Playoff field = anyone who played at least one playoff game.
    field_set: set[str] = set()
    for s in ordered_series:
        field_set.add(s.team_a)
        field_set.add(s.team_b)

    cup_champion: str | None = None
    if scf and scf[0].winner is not None:
        cup_champion = scf[0].winner

    eliminated_set: set[str] = set()
    for s in ordered_series:
        if s.winner is not None:
            eliminated_set.add(s.opponent_of(s.winner))
    alive_set = field_set - eliminated_set

    return PlayoffState(
        season_id=season_id,
        playoff_field=sorted(field_set),
        round1_series=round1,
        round2_series=round2,
        cf_series=cf,
        scf_series=scf,
        eliminated=sorted(eliminated_set),
        alive=sorted(alive_set),
        cup_champion=cup_champion,
    )


# ---- Higher-level convenience -------------------------------------------------


# Hand-curated overrides for seasons where the chronological "8/4/2/1" bracket
# bucketing breaks down. The COVID bubble (2019-20) used a 24-team play-in
# round before the standard bracket; the 2020-21 season used realigned all-
# divisional brackets with different series counts. For these, the algorithm
# can't reliably derive the SCF winner from chronology alone — overrides
# below carry the ground truth.
CUP_WINNER_OVERRIDES: dict[int, str] = {
    20192020: "TBL",  # Tampa Bay Lightning, COVID bubble in Edmonton
    20202021: "TBL",  # Tampa Bay Lightning, realigned-division playoffs
}


def cup_winner(season_id: int) -> str | None:
    """The Stanley Cup champion team code for a season, or None if the SCF
    hasn't completed (in-progress season) or the season has no playoff data.

    Looks up `CUP_WINNER_OVERRIDES` first for known non-standard bracket years;
    otherwise derives from `derive_playoff_state(...).cup_champion`.

    For very early seasons (pre-1942) when the Cup was sometimes decided via
    inter-league challenge series, this function only knows about NHL playoff
    games (gameType=3) and may report the NHL playoff winner rather than the
    actual Stanley Cup holder. Documented in §13.J.
    """
    if season_id in CUP_WINNER_OVERRIDES:
        return CUP_WINNER_OVERRIDES[season_id]
    state = derive_playoff_state(season_id)
    return state.cup_champion


def remaining_regular_season_games(season_id: int) -> list[dict]:
    """Games scheduled but not yet complete in the regular season. Empty list
    if the regular season is over.
    """
    t = _load_season(season_id)
    reg = t.filter(pc.equal(t.column("game_type"), REGULAR))
    out: list[dict] = []
    for r in reg.to_pylist():
        if r["state"] in ("OFF", "FINAL"):
            continue
        if r["home_score"] is not None:
            continue  # data present but state isn't final — skip
        out.append(r)
    return sorted(out, key=lambda r: (r["game_date"], r["game_id"]))
