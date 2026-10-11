"""Sport-agnostic game-detail payload (shared by NHL / NBA / NFL).

Each sport adapter normalizes its data into simple shapes and this module
assembles the "why these odds" breakdown, form, head-to-head, calibration
context, trend lines, rosters and live history. Nothing here creates a new
probability: every number comes from that sport's frozen model or its
locked one-shot test evaluation.
"""

from __future__ import annotations

from typing import Iterable

from . import elo

# A normalized completed game: {"date": "YYYY-MM-DD", "season_label": str,
#   "home": code, "away": code, "home_score": int, "away_score": int}


def team_form(code: str, games: Iterable[dict], n: int = 10) -> list[dict]:
    out = []
    for g in sorted(games, key=lambda g: g["date"], reverse=True):
        if code not in (g["home"], g["away"]):
            continue
        home = g["home"] == code
        us, them = (g["home_score"], g["away_score"]) if home else (g["away_score"], g["home_score"])
        out.append({
            "date": g["date"], "season": g.get("season_label"), "opponent": g["away"] if home else g["home"],
            "at_home": home, "for": us, "against": them,
            "result": "W" if us > them else ("L" if us < them else "T"),
        })
        if len(out) == n:
            break
    return out


def head_to_head(a: str, b: str, games: Iterable[dict], n: int = 5) -> list[dict]:
    meets = [g for g in games if {g["home"], g["away"]} == {a, b}]
    meets.sort(key=lambda g: g["date"], reverse=True)
    return [{"date": g["date"], "season": g.get("season_label"), "home": g["home"], "away": g["away"],
             "home_score": g["home_score"], "away_score": g["away_score"]} for g in meets[:n]]


def probability_breakdown(r_home: float, r_away: float, *, home_bump: float, neutral: bool,
                          p_home: float, divisor: float = 400.0) -> dict:
    p_no_bump = elo.expected(r_home, r_away, home_bump=0.0, divisor=divisor)
    return {
        "home_win_prob": p_home,
        "rating_gap": r_home - r_away,                 # positive = home rated higher
        "p_home_without_home_edge": p_no_bump,
        "home_edge_elo": 0.0 if neutral else home_bump,
        "home_edge_prob_points": 0.0 if neutral else p_home - p_no_bump,
        "neutral": neutral,
        "favorite": "home" if p_home > 0.5 else ("away" if p_home < 0.5 else None),
    }


def calibration_context(p_home: float, buckets: list[dict], source: str) -> dict | None:
    for b in buckets:
        if b["lo"] <= p_home < b["hi"] or (b["hi"] >= 1.0 and p_home >= b["lo"]):
            if not b["n"]:
                return None
            return {"lo": b["lo"], "hi": b["hi"], "n": b["n"],
                    "mean_predicted": b["mean_predicted"], "home_win_rate": b["mean_actual"],
                    "source": source}
    return None


def trend(points: list[dict], season_label: str | None) -> dict:
    return {"season": season_label, "points": points}
