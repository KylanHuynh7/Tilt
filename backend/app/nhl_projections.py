"""Live NHL skater projections (methodology/NHL_PLAYERS.md §5, §7).

Frozen params from artifacts/nhl_players_v1.json, served only because the
one-shot test passed (P-7). State = replay of every box score on disk from
1998-99 (including the live season). Candidates = the team's current NHL roster
minus players ESPN rules out (matched by name); "lineup not confirmed" until
puck drop.
"""

from __future__ import annotations

import json
import threading
import unicodedata
from pathlib import Path

import httpx

from . import boxscores, pipeline
from . import projections as pj

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "nhl_players_v1.json"
RESULTS = Path(__file__).resolve().parent.parent / "results" / "nhl_players_test_evaluation.json"
FIRST = 19981999

_lock = threading.Lock()
_cache: dict | None = None


def available() -> bool:
    if not (ARTIFACT.exists() and RESULTS.exists()):
        return False
    return bool(json.loads(RESULTS.read_text()).get("all_pass"))     # P-7: hide unless it passed


def _build() -> dict:
    frozen = json.loads(ARTIFACT.read_text())["winners"]
    seasons = sorted(int(p.stem) for p in boxscores.BOX_DIR.glob("*.parquet") if int(p.stem) >= FIRST)
    rows = pj.load_sorted(seasons)
    priors = pj.priors_for(rows)
    last = seasons[-1]
    # Priors for the NEXT game: the season in progress uses the previous season's
    # stats (as in the replay); if the newest season on disk is complete, use it.
    current = pipeline.read_season(max(int(p.stem) for p in pipeline.RAW_DIR.glob("*.parquet"))).to_pylist()
    current_sid = current[0]["season_id"] if current else last
    pr = priors[last] if current_sid == last else pj.season_priors([r for r in rows if r.season == last], {})
    out = {"priors": pr, "params": {}, "state": {}}
    for e in pj.EVENTS:
        params = {k: frozen[e][k] for k in ("H", "m", "H_toi", "gamma", "home")}
        st: dict = {}
        pj.replay(rows, e, params, priors, set(), state_out=st)
        out["params"][e], out["state"][e] = params, st
    return out


def get() -> dict | None:
    """The built state, or None while the background build runs (~15-40 s)."""
    return _cache


def start_build() -> None:
    """Build (or rebuild) the state in a background thread; requests never wait."""
    def run():
        global _cache
        if not _lock.acquire(blocking=False):
            return
        try:
            _cache = _build()
        except Exception as exc:  # noqa: BLE001
            print(f"[projections] build failed: {exc!r}")
        finally:
            _lock.release()
    import os
    if available() and "PYTEST_CURRENT_TEST" not in os.environ and not os.environ.get("TILT_SKIP_PROJECTIONS"):
        threading.Thread(target=run, daemon=True).start()


def norm(name: str | None) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum())


async def nhl_roster(client: httpx.AsyncClient, team: str) -> list[dict]:
    r = await client.get(f"{pipeline.BASE}/roster/{team}/current", timeout=20, follow_redirects=True)
    r.raise_for_status()
    d = r.json()
    out = []
    for group, pos in (("forwards", "F"), ("defensemen", "D")):
        for p in d.get(group, []):
            out.append({"player_id": int(p["id"]), "pos": pos,
                        "name": f"{p['firstName']['default']} {p['lastName']['default']}",
                        "headshot": p.get("headshot")})
    return out


def project_team(skaters: list[dict], *, opponent: str, is_home: bool, ruled_out_names: set[str],
                 c: dict) -> list[dict]:
    out = []
    for s in skaters:
        if norm(s["name"]) in ruled_out_names:
            continue
        pp = pj.predict_live(c["state"]["points"], "points", c["params"]["points"], c["priors"],
                             player_id=s["player_id"], pos=s["pos"], opponent=opponent, is_home=is_home)
        pg = pj.predict_live(c["state"]["goals"], "goals", c["params"]["goals"], c["priors"],
                             player_id=s["player_id"], pos=s["pos"], opponent=opponent, is_home=is_home)
        out.append({**s, "p_point": round(pp, 4), "p_goal": round(pg, 4)})
    return sorted(out, key=lambda x: -x["p_point"])


async def for_game(client: httpx.AsyncClient, home: str, away: str, ruled_out: dict[str, set[str]]) -> dict | None:
    c = get()
    if c is None:
        return None
    rh, ra = await nhl_roster(client, home), await nhl_roster(client, away)
    return {
        "home": project_team(rh, opponent=away, is_home=True, ruled_out_names=ruled_out.get(home, set()), c=c),
        "away": project_team(ra, opponent=home, is_home=False, ruled_out_names=ruled_out.get(away, set()), c=c),
        "note": "Lineup not confirmed: projections cover every rostered skater not ruled out; scratches are "
                "announced near puck drop. Players in their first ~20 NHL games are over-projected (§13).",
        "model": "NHL skater projections v1 (passed its one-shot test, 2023-24 → 2025-26)",
    }
