"""Fit the postseason λ per sport on its fitting window (methodology/POSTSEASON.md §3).

    uv run python -m scripts.postseason_fit
Refuses to overwrite artifacts/postseason/lambdas.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.core import postseason as ps


def postseason_predictions(sport: str, seasons):
    if sport == "nfl":
        from app.nfl import live_wp
        return [p for p in live_wp.pregame_predictions(seasons).values() if p.is_playoff]
    if sport == "mlb":
        from app.mlb import live_wp
        return [p for p in live_wp.pregame(seasons).values() if p.is_playoff]
    from app.cfb import live_wp
    return [p for p in live_wp.pregame(seasons).values() if p.postseason]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if ps.ARTIFACT.exists() and "--force" not in argv:
        print(f"REFUSED: {ps.ARTIFACT} exists; λ is frozen.", file=sys.stderr)
        return 3
    for sport, seasons in ps.FIT_SEASONS.items():
        assert ps.TEST_SEASON[sport] not in seasons
    out = {"fitted_at": datetime.now(timezone.utc).isoformat(), "grid": ps.GRID}
    for sport, seasons in ps.FIT_SEASONS.items():
        preds = postseason_predictions(sport, seasons)
        p = [x.home_win_prob for x in preds]
        y = [x.outcome for x in preds]
        lam, table = ps.fit(p, y)
        expect = (lam >= 0.9) if sport == "nfl" else (0.5 <= lam <= 0.85)
        out[sport] = {"lambda": lam, "active": lam < 1.0, "fit_seasons": seasons, "n": len(p),
                      "ll_raw": table[1.0], "ll_shrunk": table[lam], "ll_by_lambda": table,
                      "expectation_met": expect, "test_season": ps.TEST_SEASON[sport]}
        print(f"{sport}: n={len(p)} λ={lam} LL {table[1.0]:.5f} → {table[lam]:.5f} (expectation met: {expect})")
    ps.ARTIFACT.write_text(json.dumps(out, indent=2))
    print(f"wrote {ps.ARTIFACT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
