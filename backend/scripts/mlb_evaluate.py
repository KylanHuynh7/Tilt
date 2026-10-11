"""MLB one-shot test evaluation — methodology/MLB.md §6, §10 #1 quarantined.

Scores the frozen model on 2022–2025 exactly once, with every §6 breakdown in
the same pass and the team-only (c = 0) baseline at the frozen K/carry/H.

    uv run python -m scripts.mlb_evaluate --confirm
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import metrics
from app.mlb import backtest, pipeline, ratings, tuner

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "artifacts" / "mlb" / "frozen_params.json"
DEFAULT_OUT = ROOT / "results" / "mlb" / "test_evaluation.json"
TARGETS = {"log_loss_max": 0.685, "brier_band": [0.235, 0.248], "ece_max": 0.03}
PLAYOFF_ECE_FLAG = 0.08


def load_frozen():
    if not ARTIFACT.exists():
        raise SystemExit(f"ERROR: no frozen MLB artifact at {ARTIFACT}")
    a = json.loads(ARTIFACT.read_text())
    w = a["winner"]
    keys = [f.name for f in dataclasses.fields(ratings.Params)]
    return ratings.Params(**{k: w[k] for k in keys}), a


def block(preds, team_only_by_pk, rate, static, bump):
    if not preds:
        return {"n": 0}
    ys = [p.outcome for p in preds]
    probs = [p.home_win_prob for p in preds]
    return {
        "n": len(preds),
        "model": tuner.score(probs, ys),
        "naive_baseline": tuner.score([0.5] * len(ys), ys),
        "home_rate_baseline": tuner.score(tuner.home_rate_probs(preds, rate), ys),
        "static_rating_baseline": tuner.score(tuner.static_probs(preds, static, bump), ys),
        "team_only_baseline": tuner.score([team_only_by_pk[p.game_pk] for p in preds], ys),
        "calibration_buckets": [
            {"lo": b.lo, "hi": b.hi, "n": b.n, "mean_predicted": b.mean_predicted, "mean_actual": b.mean_actual}
            for b in metrics.calibration_buckets(probs, ys)
        ],
    }


def verdict(m, home_rate_ll):
    lo, hi = TARGETS["brier_band"]
    return {
        "log_loss": "PASS" if m["log_loss"] < TARGETS["log_loss_max"] else "FAIL",
        "brier": "PASS" if lo <= m["brier"] <= hi else "FAIL",
        "ece": "PASS" if m["ece"] < TARGETS["ece_max"] else "FAIL",
        "beats_home_rate_on_log_loss": "PASS" if m["log_loss"] < home_rate_ll else "FAIL",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scripts.mlb_evaluate")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = p.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the held-out MLB test seasons (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists() and not a.force:
        print(f"REFUSED: results already exist at {a.out} (§10 #2).", file=sys.stderr)
        return 3
    params, artifact = load_frozen()
    test = tuner.TEST_SEASONS_DO_NOT_TOUCH
    cov = pipeline.load_manifest()
    for s in test:
        if not cov[str(s)]["coverage"]["passes"]:
            raise SystemExit(f"ERROR: test season {s} fails coverage")
    seasons = list(range(2000, test[-1] + 1))
    data = backtest.load(seasons)
    print(f"MLB TEST-SET EVALUATION — §10 #1 quarantine\nFrozen: {params}\nTEST (read once): {test}")
    full = backtest.run(seasons, params, data=data, record_predictions_for=set(test))
    team_only = backtest.run(seasons, dataclasses.replace(params, c=0.0), data=data, record_predictions_for=set(test))
    t_only = {x.game_pk: x.home_win_prob for x in team_only.predictions}
    static = backtest.run([s for s in seasons if s <= tuner.LAST_VALIDATION], params, data=data).ratings
    rate = artifact["validation_baselines"]["home_rate"]["rate"]
    preds = full.predictions

    def b(sub):
        return block(sub, t_only, rate, static, params.home_bump)

    overall = b(preds)
    bd = {
        "per_season": {str(s): b([x for x in preds if x.season == s]) for s in test},
        "regular_season": b([x for x in preds if not x.is_playoff]),
        "postseason": b([x for x in preds if x.is_playoff]),
        "segments": {sg: b([x for x in preds if backtest.segment(x) == sg]) for sg in ("early", "mid", "late")},
        "neutral_site": b([x for x in preds if x.neutral]),
        "pitcher_first_start": b([x for x in preds if x.home_pitcher_first_start or x.away_pitcher_first_start]),
        "pitchers_established": b([x for x in preds if not (x.home_pitcher_first_start or x.away_pitcher_first_start)]),
    }
    seg = bd["segments"]
    ratio = seg["late"]["model"]["ece"] / seg["mid"]["model"]["ece"] if seg["mid"]["model"]["ece"] else None
    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": artifact["methodology_version"], "frozen_at": artifact["frozen_at"],
        "frozen_params": dataclasses.asdict(params), "test_seasons": test,
        "home_rate_baseline_constant": rate, "test_home_rate_observed": round(tuner.home_rate(preds), 4),
        "segment_rule": "months Mar-May / Jun-Aug / Sep-Oct; postseason separate",
        "targets": TARGETS, "overall": overall,
        "verdict": verdict(overall["model"], overall["home_rate_baseline"]["log_loss"]),
        "flags": {"postseason_ece_above_0_08": bd["postseason"]["model"]["ece"] > PLAYOFF_ECE_FLAG,
                  "late_segment_ece_over_2x_mid": bool(ratio and ratio > 2.0),
                  "late_over_mid_ece_ratio": ratio},
        "breakdowns": bd,
        "notes": ["Per §10 #1 this script reads the test seasons exactly once."],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    for name in ("model", "team_only_baseline", "home_rate_baseline", "naive_baseline", "static_rating_baseline"):
        m = overall[name]
        print(f"  {name:<24} LL={m['log_loss']:.5f} Brier={m['brier']:.5f} ECE={m['ece']:.4f} n={m['n']}")
    print("verdict:", payload["verdict"]); print("flags:", payload["flags"])
    for k in ("regular_season", "postseason", "neutral_site", "pitcher_first_start", "pitchers_established"):
        m = bd[k].get("model")
        if m:
            print(f"  {k:<22} n={m['n']:<5} LL={m['log_loss']:.5f} ECE={m['ece']:.4f}")
    for k, blk in {**bd["per_season"], **bd["segments"]}.items():
        m = blk["model"]
        print(f"  {k:<22} n={m['n']:<5} LL={m['log_loss']:.5f} ECE={m['ece']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
