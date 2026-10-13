"""One-shot test of the postseason layer on a sport's next postseason (POSTSEASON.md §4).

    uv run python -m scripts.postseason_evaluate --sport mlb --confirm

Refuses: without --confirm; if that sport's result exists; until the sport's
final is in the ingested data with no unplayed postseason games remaining.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from app.core import postseason as ps
from scripts.postseason_fit import postseason_predictions

OUT = ps.ROOT / "results" / "postseason"


def season_complete(sport: str, season: int) -> bool:
    if sport == "mlb":
        import pyarrow.parquet as pq
        from app.mlb import pipeline
        rows = pq.read_table(pipeline.DATA_DIR / "games" / f"{season}.parquet").to_pylist()
        ws = [r for r in rows if r["game_type"] == "W" and r.get("home_score") is not None]
        wins: dict = {}
        for r in ws:
            if r["home_score"] != r["away_score"]:
                w = r["home_id"] if r["home_score"] > r["away_score"] else r["away_id"]
                wins[w] = wins.get(w, 0) + 1
        return any(v >= 4 for v in wins.values())
    if sport == "nfl":
        from app.nfl import backtest
        rows = backtest.rows_by_season(through=season).get(season, [])
        return any(r.get("game_type") == "SB" and r.get("home_score") is not None for r in rows)
    from app.cfb import pipeline
    rows = pipeline.read_games(season)
    post = [r for r in rows if r.get("season_type") == 3]
    done = pipeline.completed_games(post)
    return bool(post) and len(done) == len(post) and max(str(r.get("date", "")) for r in done) >= f"{season + 1}-01-05"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scripts.postseason_evaluate")
    ap.add_argument("--sport", required=True, choices=["nfl", "mlb", "cfb"])
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args(argv)
    out = OUT / f"{a.sport}_{ps.TEST_SEASON[a.sport]}.json"
    if not a.confirm:
        print("REFUSED: reads the held-out postseason. Re-run with --confirm.", file=sys.stderr)
        return 2
    if out.exists():
        print(f"REFUSED: {out} exists (one-shot).", file=sys.stderr)
        return 3
    season = ps.TEST_SEASON[a.sport]
    if not season_complete(a.sport, season):
        print(f"REFUSED: the {season} {a.sport.upper()} postseason is not finished in the ingested data.", file=sys.stderr)
        return 4
    frozen = json.loads(ps.ARTIFACT.read_text())[a.sport]
    preds = postseason_predictions(a.sport, [season])
    p = [x.home_win_prob for x in preds]
    y = [x.outcome for x in preds]
    lam = frozen["lambda"]
    raw, shr = ps.log_loss(p, y), ps.log_loss([ps.shrink(v, lam) for v in p], y)
    payload = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "sport": a.sport, "season": season,
               "lambda": lam, "n": len(p), "ll_raw": raw, "ll_shrunk": shr,
               "verdict": ("n/a (λ = 1, layer off)" if lam >= 1 else ("PASS" if shr < raw else "FAIL"))}
    OUT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
