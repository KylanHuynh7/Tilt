"""One-shot test of the NHL skater projections (methodology/NHL_PLAYERS.md §6).

Per event (points, goals) on 2023-24 → 2025-26:
  1. beats Baseline A (previous season's position rate) on log-loss
  2. beats Baseline B (last-82-games rate via Poisson) on log-loss
  3. ECE < 0.02
  4. top-decile |mean predicted − observed| < 0.03
Reported: F vs D, first 20 career games vs rest, each season, regular vs playoffs.
Flags: any group ECE > 0.04; playoffs worse than regular season by > 0.01 LL.

    uv run python -m scripts.players_evaluate --confirm
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app import projections as pj

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "artifacts" / "nhl_players_v1.json"
OUT = ROOT / "results" / "nhl_players_test_evaluation.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scripts.players_evaluate")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the held-out test seasons (§10). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists() and not a.force:
        print(f"REFUSED: results already exist at {a.out}.", file=sys.stderr)
        return 3
    frozen = json.loads(ARTIFACT.read_text())
    rows = pj.load_sorted(pj.WARMUP + pj.VALIDATION + pj.TEST_DO_NOT_TOUCH)
    priors = pj.priors_for(rows)
    test = set(pj.TEST_DO_NOT_TOUCH)
    career: dict[int, int] = defaultdict(int)
    meta = []                       # (season, pos, rookie, playoff) aligned with recorded predictions
    for r in rows:
        if r.season in test:
            meta.append((r.season, r.pos, career[r.player_id] < 20, (r.game_id // 10000) % 100 == 3))
        career[r.player_id] += 1

    payload = {"evaluated_at": datetime.now(timezone.utc).isoformat(), "test_seasons": pj.TEST_DO_NOT_TOUCH,
               "events": {}, "verdict": {}, "flags": []}
    for e in pj.EVENTS:
        w = frozen["winners"][e]
        params = {k: w[k] for k in ("H", "m", "H_toi", "gamma", "home")}
        preds = pj.replay(rows, e, params, priors, test)
        pa, pb = pj.baselines(rows, e, priors, test)
        p = [x.p for x in preds]
        y = [x.y for x in preds]
        assert len(p) == len(pa) == len(meta)
        model, A, B = pj.score(p, y), pj.score(pa, y), pj.score(pb, y)

        def group(fn):
            idx = defaultdict(list)
            for i, m in enumerate(meta):
                idx[fn(m)].append(i)
            return {str(k): pj.score([p[i] for i in v], [y[i] for i in v]) for k, v in sorted(idx.items())}

        groups = {"position": group(lambda m: m[1]), "first_20_career_games": group(lambda m: m[2]),
                  "season": group(lambda m: m[0]), "playoffs": group(lambda m: m[3])}
        verdict = {"beats_baseline_A": model["log_loss"] < A["log_loss"],
                   "beats_baseline_B": model["log_loss"] < B["log_loss"],
                   "ece_below_0_02": model["ece"] < 0.02,
                   "top_decile_gap_below_0_03": model["top_decile_gap"] < 0.03}
        for gname, g in groups.items():
            for k, sc in g.items():
                if sc["ece"] > 0.04:
                    payload["flags"].append(f"{e}: {gname}={k} ECE {sc['ece']:.4f} > 0.04")
        po = groups["playoffs"]
        if "True" in po and po["True"]["log_loss"] - po["False"]["log_loss"] > 0.01:
            payload["flags"].append(f"{e}: playoffs LL worse than regular season by > 0.01")
        payload["events"][e] = {"params": params, "model": model, "baseline_A": A, "baseline_B": B, "groups": groups}
        payload["verdict"][e] = {k: "PASS" if v else "FAIL" for k, v in verdict.items()}
        print(f"{e}: model LL {model['log_loss']:.5f} ECE {model['ece']:.4f} top-decile gap {model['top_decile_gap']:.4f}"
              f" | A {A['log_loss']:.5f} | B {B['log_loss']:.5f}")
        print("   ", payload["verdict"][e])
    payload["all_pass"] = all(v == "PASS" for ev in payload["verdict"].values() for v in ev.values())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    print("flags:", payload["flags"] or "none", "| all pass:", payload["all_pass"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
