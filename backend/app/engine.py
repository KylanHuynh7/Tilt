"""Live-data engine for the API.

Rebuilt in Phase D to delegate historical rating computation to `historical`
(which loads frozen params and replays every ingested Parquet) and to keep
only the live NHL-API integration here: today's schedule and the on-demand
pipeline refresh that pulls in newly-completed games.

The old in-memory milestone-1 engine is gone — its responsibilities moved
into `historical` and the model is no longer seeded at 1500 with no history.
"""

from __future__ import annotations

from datetime import date

import httpx

import asyncio

from . import historical, live_state, live_wp, pipeline
from .franchises import current_code
from .nhl_api import fetch_today
from .ratings import win_probability


async def refresh_current_season(today: date | None = None) -> dict:
    """Re-ingest the current NHL season Parquet, then rebuild the rating
    cache. Returns a small status dict.

    The pipeline is async-aware and handles its own concurrency; we just
    await it and then trigger the cache rebuild (which is synchronous and
    sub-second at the current data scale).
    """
    today = today or date.today()
    current_sid = _current_season_id(today)
    await pipeline.ingest_one(current_sid, today=today, force=True)
    cache = historical.refresh()
    return {
        "current_season": current_sid,
        "seasons_replayed": len(cache.seasons_replayed),
        "last_built_at": cache.last_built_at.isoformat() if cache.last_built_at else None,
    }


def _current_season_id(today: date) -> int:
    """A season runs from October through June of the following year. Treat
    anything from July onward as the season that's about to start.
    """
    if today.month >= 9:
        start = today.year
    elif today.month >= 7:
        start = today.year  # July-August: next season's prep
    else:
        start = today.year - 1
    return start * 10000 + (start + 1)


async def todays_matchups(today: date | None = None) -> list[dict]:
    """For each game scheduled today, look up both teams' current ratings and
    compute a pre-game win probability using the frozen model.

    v2.3 §16 extension: for any matchup whose `gameState` is LIVE or CRIT,
    additionally fetch the play-by-play, extract the current (period, time
    remaining, score), and include the live WP from the v2.2 lookup. If the
    WP artifact is missing or the live PBP fetch fails, the matchup falls
    back to the pre-game WP only.
    """
    today = today or date.today()
    async with httpx.AsyncClient() as client:
        games = await fetch_today(client, today)

        cache = historical.get_cache()
        ratings = cache.current_ratings
        home_bump = cache.params.home_bump

        # Pre-compute the matchup base payload and identify which ones are live.
        live_indexes: list[int] = []
        out: list[dict] = []
        for g in games:
            home_fid = historical.franchise_for_active_code(g.home)
            away_fid = historical.franchise_for_active_code(g.away)
            if home_fid is None or away_fid is None:
                continue  # exhibition / international code we don't model
            r_home = ratings.get(home_fid, 1500.0)
            r_away = ratings.get(away_fid, 1500.0)
            p_home = win_probability(r_home, r_away, home_bump=home_bump)
            matchup = {
                "game_id": g.game_id,
                "game_date": g.game_date.isoformat(),
                "state": g.state,
                "home": g.home,
                "away": g.away,
                "home_rating": round(r_home, 2),
                "away_rating": round(r_away, 2),
                "home_win_prob": round(p_home, 4),
                "away_win_prob": round(1.0 - p_home, 4),
                "home_score": g.home_score,
                "away_score": g.away_score,
            }
            if g.state in live_state.LIVE_STATES:
                live_indexes.append(len(out))
            out.append(matchup)

        # Fan out PBP fetches for in-progress games, then enrich the payload.
        if live_indexes:
            live_results = await asyncio.gather(
                *[live_state.fetch_live_state(client, out[i]["game_id"])
                  for i in live_indexes],
                return_exceptions=False,  # fetch_live_state already swallows
            )
            try:
                wp_model = live_wp.get_model()
            except FileNotFoundError:
                wp_model = None
            for i, state in zip(live_indexes, live_results):
                if state is None:
                    continue
                out[i]["live_state"] = {
                    "game_state": state.game_state,
                    "period": state.period,
                    "time_remaining_s": state.time_remaining_s,
                    "home_score": state.home_score,
                    "away_score": state.away_score,
                }
                if wp_model is not None:
                    lookup = live_wp.query(
                        wp_model,
                        period=state.period,
                        time_remaining_s=state.time_remaining_s,
                        score_diff=state.score_diff,
                    )
                    out[i]["live_wp"] = {
                        "home_win_prob": lookup.home_win_prob,
                        "n_samples": lookup.n,
                        "smoothed": lookup.smoothed,
                    }
    return out
