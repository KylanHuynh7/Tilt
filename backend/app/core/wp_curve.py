"""Full-game win-probability curves with the biggest swings labelled.

No new model: each sport's frozen live model (v1.1 / NHL v2.2) is evaluated at
every play of the game, from play-by-play fetched on demand. Reads only game
state and play descriptions; never any odds / win-probability / predictor block.

Point = {x: game progress 0–1, wp: P(home), label: clock + score, text: the play
that LED to this point}. Swings = the 3 largest |Δwp| between consecutive points.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

ESPN_SUMMARY = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
}
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _clock(display: str | None) -> float:
    if not display:
        return 0.0
    if ":" in display:
        m, s = display.split(":")
        return int(m) * 60 + float(s)
    return float(display)


_ADMIN = ("END ", "Timeout", "Two-Minute", "Two Minute", "Start of", "End of", "Official")


def swings(points: list[dict], k: int = 3) -> list[dict]:
    """Largest moves attributed to real plays (period ends / timeouts aren't plays)."""
    deltas = [(abs(b["wp"] - a["wp"]), i) for i, (a, b) in enumerate(zip(points, points[1:]))
              if b.get("text") and not b["text"].strip().startswith(_ADMIN)]
    out = []
    for _, i in sorted(deltas, reverse=True)[:k]:
        a, b = points[i], points[i + 1]
        out.append({"x": b["x"], "from": a["wp"], "to": b["wp"], "label": b["label"], "text": b["text"]})
    return sorted(out, key=lambda s: s["x"])


def _football(sport: str, payload: dict, pre: float, home_id: str) -> list[dict]:
    from ..nfl import live_wp as lw
    beta = lw.load()
    f = lambda q, c, d, s, y: lw.predict(beta, pre_game_p=pre, qtr=q, qsr=c, d=d, s=s, y=y)  # noqa: E731
    plays = [p for d in ((payload.get("drives") or {}).get("previous") or []) for p in (d.get("plays") or [])]
    pts = [{"x": 0.0, "wp": f(1, 900, 0, 0, 50), "label": "Kickoff", "text": None}]
    hs = as_ = 0
    for p in plays:
        q = int((p.get("period") or {}).get("number") or 1)
        c = _clock((p.get("clock") or {}).get("displayValue"))
        hs, as_ = int(p.get("homeScore") or hs), int(p.get("awayScore") or as_)
        end = p.get("end") or {}
        team = str(((end.get("team") or {}).get("id")) or "")
        s = 1 if team == home_id else (-1 if team else 0)
        y = end.get("yardsToEndzone") if isinstance(end.get("yardsToEndzone"), int) and 1 <= end["yardsToEndzone"] <= 99 else 50
        elapsed = (min(q, 4) - 1) * 900 + (900 - c) if q <= 4 else 3600
        pts.append({"x": min(elapsed / 3600, 1.0), "wp": f(q, c, hs - as_, s, y),
                    "label": f"Q{q if q <= 4 else 'OT'} {int(c // 60)}:{int(c % 60):02d} · {as_}–{hs}",
                    "text": (p.get("text") or "")[:160]})
    return pts


def _nba(payload: dict, pre: float) -> list[dict]:
    from ..nba import live_wp as lw
    model = lw.load()
    pts = [{"x": 0.0, "wp": lw.predict(model, pre_game_p=pre, period=1, sec_left=720, d=0), "label": "Tip-off", "text": None}]
    last = (0, 0)
    for p in payload.get("plays") or []:
        sc = (int(p.get("homeScore") or 0), int(p.get("awayScore") or 0))
        if sc == last:
            continue                       # only plays that change the score move the curve much
        last = sc
        per = int((p.get("period") or {}).get("number") or 1)
        c = _clock((p.get("clock") or {}).get("displayValue"))
        elapsed = (per - 1) * 720 + (720 - c) if per <= 4 else 2880
        pts.append({"x": min(elapsed / 2880, 1.0), "wp": lw.predict(model, pre_game_p=pre, period=per, sec_left=c, d=sc[0] - sc[1]),
                    "label": f"{'Q' + str(per) if per <= 4 else 'OT'} {int(c // 60)}:{int(c % 60):02d} · {sc[1]}–{sc[0]}",
                    "text": (p.get("text") or "")[:160]})
    return pts


def _mlb(payload: dict, pre: float) -> list[dict]:
    from ..mlb import live_wp as lw
    beta, re = lw.load()
    f = lambda inn, bot, outs, bases, d: lw.predict(beta, re, pre_game_p=pre, inning=inn, bottom=bot,  # noqa: E731
                                                    outs=outs, bases=bases, d=d)
    pts = [{"x": 0.0, "wp": f(1, False, 0, 0, 0), "label": "First pitch", "text": None}]
    for p in (payload.get("liveData") or {}).get("plays", {}).get("allPlays", []) or payload.get("allPlays", []):
        ab, res, m = p.get("about") or {}, p.get("result") or {}, p.get("matchup") or {}
        if not ab.get("isComplete", True):
            continue
        inn, bot = int(ab.get("inning") or 1), ab.get("halfInning") == "bottom"
        outs = int((p.get("count") or {}).get("outs") or 0)
        bases = (1 if m.get("postOnFirst") else 0) | (2 if m.get("postOnSecond") else 0) | (4 if m.get("postOnThird") else 0)
        d = int(res.get("homeScore") or 0) - int(res.get("awayScore") or 0)
        label = f"{'Bot' if bot else 'Top'} {inn} · {res.get('awayScore', 0)}–{res.get('homeScore', 0)}"
        if outs >= 3:                      # half over: next half starts empty
            inn, bot, outs, bases = (inn, True, 0, 0) if not bot else (inn + 1, False, 0, 0)
        x = min(((inn - 1) * 6 + (3 if bot else 0) + outs) / 54, 1.0)
        pts.append({"x": x, "wp": f(inn, bot, outs, bases, d),
                    "label": label, "text": (res.get("description") or "")[:160]})
    return pts


def _nhl(payload: dict) -> list[dict]:
    from .. import live_wp as nhl_wp
    from ..main import _wp_model_or_503
    model = _wp_model_or_503()
    pts = []
    hs = as_ = 0
    for p in payload.get("plays") or []:
        per = int((p.get("periodDescriptor") or {}).get("number") or 1)
        if per > 4:
            continue
        rem = int(_clock(p.get("timeRemaining")))
        if p.get("typeDescKey") == "goal":
            det = p.get("details") or {}
            hs, as_ = int(det.get("homeScore", hs)), int(det.get("awayScore", as_))
            text = f"Goal · {as_}–{hs}"
        elif not pts or p.get("typeDescKey") in ("period-start", "period-end"):
            text = None
        else:
            continue
        wp = nhl_wp.query(model, period=per, time_remaining_s=rem, score_diff=hs - as_).home_win_prob
        pts.append({"x": min(((per - 1) * 1200 + (1200 - rem)) / 3600, 1.0), "wp": wp,
                    "label": f"P{per if per <= 3 else 'OT'} {rem // 60}:{rem % 60:02d} · {as_}–{hs}", "text": text})
    return pts


async def build(sport: str, game_id: str, *, pre_game_p: float, home_espn_id: str | None = None,
                final_home_won: bool | None = None) -> dict | None:
    """Curve + swings for one game, or None if no plays yet. Cached 60 s."""
    key = (sport, str(game_id))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    async with httpx.AsyncClient(headers={"User-Agent": f"tilt-{sport}"}) as client:
        if sport in ESPN_SUMMARY:
            r = await client.get(ESPN_SUMMARY[sport], params={"event": game_id}, timeout=30)
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            if sport == "nba":
                pts = _nba({"plays": data.get("plays")}, pre_game_p)
            else:
                home = home_espn_id or next((c["id"] for c in data["header"]["competitions"][0]["competitors"]
                                             if c.get("homeAway") == "home"), "")
                pts = _football(sport, {"drives": data.get("drives")}, pre_game_p, str(home))
        elif sport == "mlb":
            r = await client.get(f"https://statsapi.mlb.com/api/v1/game/{game_id}/playByPlay", timeout=30)
            r.raise_for_status()
            pts = _mlb(r.json(), pre_game_p)
        else:
            r = await client.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play", timeout=30)
            r.raise_for_status()
            pts = _nhl(r.json())
    if len(pts) < 2:
        out = None
    else:
        if final_home_won is not None:
            pts.append({"x": 1.0, "wp": 1.0 if final_home_won else 0.0, "label": "Final", "text": None})
        out = {"points": pts, "swings": swings(pts)}
    _cache[key] = (time.time(), out)
    return out


async def for_matchup(sport: str, m: dict) -> dict | None:
    """Curve for a live or finished game on a sport's slate; None otherwise or on any error."""
    state = m.get("state")
    done = state in ("FINAL", "OFF")            # NHL uses its raw states (OFF / LIVE / CRIT)
    if not done and state not in ("LIVE", "CRIT"):
        return None
    pre = m.get("raw_home_win_prob", m.get("home_win_prob", 0.5))
    hs, as_ = m.get("home_score"), m.get("away_score")
    final = (int(hs) > int(as_)) if done and hs is not None and as_ is not None and hs != as_ else None
    try:
        return await build(sport, str(m["game_id"]), pre_game_p=float(pre), final_home_won=final)
    except Exception as exc:  # noqa: BLE001 — the chart is optional
        print(f"[wp_curve] {sport} {m.get('game_id')}: {exc!r}")
        return None
