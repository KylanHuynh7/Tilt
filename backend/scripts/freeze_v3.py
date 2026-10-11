"""Freeze NHL v3.0 then v3.1 on validation 2021-22 → 2025-26 (§17, §18, §20).

    uv run python -m scripts.freeze_v3

Writes artifacts/frozen_params_v3.json. Refuses to overwrite it (the v3 model
is frozen once) and refuses any season after 2025-26 (§20 V3-5).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app import backtest, boxscores, tuner_v3

OUT = Path(__file__).resolve().parent.parent / "artifacts" / "frozen_params_v3.json"
V2_PARAMS = dict(k_regular=10.0, k_playoff=10.0, decay_carry=0.85, home_bump=40.0)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if OUT.exists() and "--force" not in argv:
        print(f"REFUSED: {OUT} exists; v3 is frozen.", file=sys.stderr)
        return 3
    seasons = tuner_v3.TRAINING_SEASONS + tuner_v3.VALIDATION_SEASONS
    tuner_v3.check_quarantine(seasons)
    manifest = json.loads(boxscores.MANIFEST.read_text())
    missing = [s for s in seasons if str(s) not in manifest]
    if missing:
        print(f"REFUSED: box scores not ingested for {missing}", file=sys.stderr)
        return 4
    uncovered_val = [s for s in tuner_v3.VALIDATION_SEASONS if not manifest[str(s)]["covered"]]
    if uncovered_val:
        print(f"REFUSED: validation seasons without full box-score coverage: {uncovered_val}", file=sys.stderr)
        return 4
    t0 = time.time()
    events = tuner_v3.all_events()
    print(f"{len(events)} roster-move events across {len(seasons)} seasons", flush=True)

    print("v3.0 grid …", flush=True)
    rows30 = tuner_v3.v30(events)
    win30, free30 = tuner_v3.pick(rows30)
    v2_cell = next(r for r in rows30 if all(r[k] == v for k, v in V2_PARAMS.items()) and r["boost_amount"] == 0)
    print(f"v3.0 winner {win30}", flush=True)

    print("v3.1 sub-grid …", flush=True)
    rows31 = tuner_v3.v31(win30, events)
    win31, _ = tuner_v3.pick(rows31)
    print(f"v3.1 winner {win31}", flush=True)

    t_cov = {s: manifest[str(s)]["covered"] for s in tuner_v3.TRAINING_SEASONS}
    payload = {
        "methodology_version": "3.1", "frozen_at": datetime.now(timezone.utc).isoformat(),
        "training_seasons": tuner_v3.TRAINING_SEASONS, "validation_seasons": tuner_v3.VALIDATION_SEASONS,
        "test_seasons_do_not_touch": tuner_v3.TEST_SEASONS_DO_NOT_TOUCH,
        "n_roster_events": len(events),
        "training_seasons_without_full_boxscore_coverage": [s for s, ok in t_cov.items() if not ok],
        "winner": win31, "v30_winner": win30, "v30_unconstrained_winner": free30,
        "v2_params_on_v3_validation": v2_cell,
        "expectations": {
            "v30_improves_ll_vs_v2_by_0_002": v2_cell["log_loss"] - win30["log_loss"] >= 0.002,
            "boost_window_in_5_15": 5 <= win30["boost_window"] <= 15 if win30["boost_amount"] else None,
            "boost_amount_in_0_25_0_75": 0.25 <= win30["boost_amount"] <= 0.75,
            "v31_improves_ll_vs_v30_by_0_0005": win30["log_loss"] - win31["log_loss"] >= 0.0005,
            "round_scale_in_0_05_0_15": 0.05 <= win31["round_scale"] <= 0.15,
            "elim_bump_in_0_10_0_30": 0.10 <= win31["elim_bump"] <= 0.30,
        },
        "wall_seconds": round(time.time() - t0, 1),
        "v30_grid": rows30, "v31_grid": rows31,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT} ({payload['wall_seconds']}s)")
    for k, v in payload["expectations"].items():
        print(f"  {k}: {v}")
    print(f"  v2 params on v3 validation: LL {v2_cell['log_loss']:.5f} · v3.0 {win30['log_loss']:.5f} · v3.1 {win31['log_loss']:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
