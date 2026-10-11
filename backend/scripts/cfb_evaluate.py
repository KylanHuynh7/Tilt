"""College football one-shot test evaluation — methodology/CFB.md §6, §10 #1.

FBS-vs-FBS games only for every metric (DECISION 2); FBS-vs-FCS games are
reported separately. Every §6 breakdown in the same single pass.

    uv run python -m scripts.cfb_evaluate --confirm
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import metrics
from app.cfb import backtest, pipeline, ratings, tuner

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "artifacts" / "cfb" / "frozen_params.json"
OUT = ROOT / "results" / "cfb" / "test_evaluation.json"
TARGETS = {"log_loss_max": 0.600, "brier_band": [0.170, 0.210], "ece_max": 0.04}
POST_ECE_FLAG = 0.08


def block(preds, rate, static, params):
    if not preds:
        return {"n": 0}
    ys = [p.outcome for p in preds]
    probs = [p.home_win_prob for p in preds]
    return {"n": len(preds), "model": tuner.score(probs, ys),
            "naive_baseline": tuner.score([0.5] * len(ys), ys),
            "home_rate_baseline": tuner.score(tuner.home_rate_probs(preds, rate), ys),
            "static_rating_baseline": tuner.score(tuner.static_probs(preds, static, params), ys),
            "calibration_buckets": [{"lo": b.lo, "hi": b.hi, "n": b.n, "mean_predicted": b.mean_predicted,
                                     "mean_actual": b.mean_actual} for b in metrics.calibration_buckets(probs, ys)]}


def verdict(m, home_ll):
    lo, hi = TARGETS["brier_band"]
    return {"log_loss": "PASS" if m["log_loss"] < TARGETS["log_loss_max"] else "FAIL",
            "brier": "PASS" if lo <= m["brier"] <= hi else "FAIL",
            "ece": "PASS" if m["ece"] < TARGETS["ece_max"] else "FAIL",
            "beats_home_rate_on_log_loss": "PASS" if m["log_loss"] < home_ll else "FAIL"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scripts.cfb_evaluate")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    if not a.confirm:
        print("REFUSED: reads the held-out CFB test seasons (§10 #1). Re-run with --confirm.", file=sys.stderr)
        return 2
    if a.out.exists() and not a.force:
        print(f"REFUSED: results already exist at {a.out} (§10 #2).", file=sys.stderr)
        return 3
    art = json.loads(ARTIFACT.read_text())
    params = ratings.Params(**{f.name: art["winner"][f.name] for f in dataclasses.fields(ratings.Params)})
    test = tuner.TEST_SEASONS_DO_NOT_TOUCH
    for s in test:
        if not pipeline.coverage(s)["passes"]:
            raise SystemExit(f"ERROR: test season {s} fails coverage")
    seasons = list(range(2001, test[-1] + 1))
    data = backtest.load(seasons)
    print(f"CFB TEST-SET EVALUATION — §10 #1 quarantine\nFrozen: {params}\nTEST (read once): {test}")
    res = backtest.run(seasons, params, data=data, record_predictions_for=set(test))
    static = backtest.run([s for s in seasons if s <= tuner.VALIDATION_SEASONS[-1]], params, data=data).ratings
    rate = art["validation_baselines"]["home_rate"]["rate"]
    allp = res.predictions
    fbs = [x for x in allp if not x.fcs_game]
    fcs = [x for x in allp if x.fcs_game]

    def b(sub):
        return block(sub, rate, static, params)

    overall = b(fbs)
    bd = {"per_season": {str(s): b([x for x in fbs if x.season == s]) for s in test},
          "regular_season": b([x for x in fbs if not x.postseason]),
          "postseason": b([x for x in fbs if x.postseason]),
          "segments": {g: b([x for x in fbs if backtest.segment(x) == g]) for g in ("early", "mid", "late")},
          "neutral_site": b([x for x in fbs if x.neutral]),
          "conference": b([x for x in fbs if x.conference_game]),
          "non_conference": b([x for x in fbs if not x.conference_game])}
    seg = bd["segments"]
    ratio = seg["late"]["model"]["ece"] / seg["mid"]["model"]["ece"] if seg["mid"]["model"]["ece"] else None
    fcs_ys = [x.outcome for x in fcs]
    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "methodology_version": art["methodology_version"],
        "frozen_at": art["frozen_at"], "frozen_params": dataclasses.asdict(params), "test_seasons": test,
        "home_rate_baseline_constant": rate, "targets": TARGETS, "overall": overall,
        "verdict": verdict(overall["model"], overall["home_rate_baseline"]["log_loss"]),
        "flags": {"postseason_ece_above_0_08": bd["postseason"]["model"]["ece"] > POST_ECE_FLAG,
                  "late_segment_ece_over_2x_mid": bool(ratio and ratio > 2.0), "late_over_mid_ece_ratio": ratio},
        "breakdowns": bd,
        "fbs_vs_fcs_reported_separately": {"n": len(fcs), "model": tuner.score([x.home_win_prob for x in fcs], fcs_ys),
                                            "fbs_team_win_rate": round(sum((x.outcome if x.away == "FCS" else 1 - x.outcome) for x in fcs) / len(fcs), 4)},
        "notes": ["FBS-vs-FBS games only in every metric (DECISION 2).", "Per §10 #1 this script reads the test seasons exactly once."],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    for name in ("model", "home_rate_baseline", "naive_baseline", "static_rating_baseline"):
        m = overall[name]
        print(f"  {name:<24} LL={m['log_loss']:.5f} Brier={m['brier']:.5f} ECE={m['ece']:.4f} n={m['n']}")
    print("verdict:", payload["verdict"]); print("flags:", payload["flags"])
    for k in ("regular_season", "postseason", "neutral_site", "conference", "non_conference"):
        m = bd[k]["model"]; print(f"  {k:<16} n={m['n']:<5} LL={m['log_loss']:.5f} ECE={m['ece']:.4f}")
    for k, blk in {**bd["per_season"], **bd["segments"]}.items():
        m = blk["model"]; print(f"  {k:<16} n={m['n']:<5} LL={m['log_loss']:.5f} ECE={m['ece']:.4f}")
    f = payload["fbs_vs_fcs_reported_separately"]; print(f"  FBS-vs-FCS (separate): n={f['n']} LL={f['model']['log_loss']:.5f} FBS win rate {f['fbs_team_win_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
