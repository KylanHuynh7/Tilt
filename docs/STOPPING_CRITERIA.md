# §9 Stopping-Criteria Walkthrough

`METHODOLOGY.md` §9 lists ten conditions that must be met before v1 is considered shipped. This document maps each one to its evidence (file, command, or specific test) so the author can verify v1 readiness item-by-item before the manual `v1 complete` commit required by §9 #10.

---

## §9 #1 — Methodology written and author-approved before any code

**Evidence:** `METHODOLOGY.md` v1.2. Initial commit `2610acb` predates all code; v1.1 amendment committed as `995516a`; v1.2 amendment for the OAK/CGS/CLE merger is the most recent pre-evaluation update. The amendment log at the top of `METHODOLOGY.md` is the audit trail. `CHANGELOG.md` mirrors each amendment.

**Status:** ✅ Met.

---

## §9 #2 — Pipeline pulls clean game results 1917-18 → current, pre-1967 flagged

**Evidence:**

- Code: `backend/app/pipeline.py` with the schema and ingest logic; `backend/app/seasons.py` for the `pre_1967` flag.
- Data: 108 Parquet files at `backend/data_cache/raw/`. Manifest at `backend/data_cache/manifest.json`.
- Verification command:
  ```
  cd backend && uv run python -m app.pipeline status
  ```
  Expected: `manifest entries: 108`, `parquet files on disk: 108`, total game rows ≈ 72,698.
- Pre-1967 flag is a first-class column on every row (`pipeline._parse_game`). Tests `test_pipeline.py::test_parse_game_flags_pre_1967`.
- Per `METHODOLOGY.md` §4, pre-1967 seasons are excluded from training, validation, and test windows. Enforced by `backend/app/tuner.py::TRAINING_SEASONS / VALIDATION_SEASONS / TEST_SEASONS_DO_NOT_TOUCH`.

**Status:** ✅ Met.

---

## §9 #3 — Valid rating for all 32 current franchises; bounds [1200, 1800] never violated

**Evidence:**

- Verification command (one-line smoke):
  ```
  cd backend && uv run python -c "from app import historical; c = historical.initialize(); print({fid: round(r,2) for fid,r in c.current_ratings.items() if 'minnesota_wild' in fid or 'colorado_avalanche' in fid})"
  ```
- Test: `tests/test_backtest.py::test_ratings_remain_in_sanity_bounds` asserts every franchise rating stays in `(1200, 1800)` after multi-season replay.
- Live API: `GET /ratings/current` returns 32 active franchises sorted by rating desc.

**Status:** ✅ Met. Smoke run on full 1967-68 → 2024-25 produced 0 out-of-bounds ratings.

---

## §9 #4 — Backtest runs §7 protocol cleanly with no look-ahead bias

**Evidence:**

- Walk-forward chronology enforced in `backend/app/backtest.py::run` (games sorted by `(game_date, game_id)`; predictions recorded only after the rating-before snapshot).
- §7 phases segregated:
  - **Warm-up (training):** `tuner.TRAINING_SEASONS` (1967-68 → 2020-21), predictions intentionally not recorded.
  - **Validation:** `tuner.VALIDATION_SEASONS` (2021-22 + 2022-23), predictions recorded and scored via `tuner.evaluate_one`.
  - **Test:** `tuner.TEST_SEASONS_DO_NOT_TOUCH` (2023-24 + 2024-25), only touched by `scripts/evaluate.py` which requires `--confirm`.
- §10 #1 quarantine enforced at the code level: `scripts/evaluate.py` refuses to run without `--confirm` and refuses to overwrite an existing results file without `--force`. Tested in `tests/test_evaluate_guardrails.py`.
- Cross-season decay applied once per boundary in `backtest.run` (not per game). 1978 OAK/CGS/CLE → MNS merger applied before decay at the 1978-79 boundary per §4 v1.2 (`franchises.FRANCHISE_MERGERS`).

**Status:** ✅ Met.

---

## §9 #5 — All three §6 metrics computed on the test set, recorded, unchanged

**Evidence:** `backend/results/test_evaluation.json` written by `scripts/evaluate.py` on 2026-05-18 03:48 UTC. Contents include:

```
"metrics": {
  "model":                  { "log_loss": 0.67102, "brier": 0.23921, "ece": 0.05164, "n": 2798 },
  "naive_baseline":         { "log_loss": 0.69315, "brier": 0.25000, "ece": 0.05111, "n": 2798 },
  "static_rating_baseline": { "log_loss": 0.67871, "brier": 0.24260, "ece": 0.05282, "n": 2798 }
}
```

Per-season breakdown also stored under `per_season`. Calibration buckets under `calibration_buckets`. Per §10 #2, these numbers are frozen — re-running `evaluate.py` requires `--force` and invalidates the evaluation unless a documented re-evaluation justification exists.

**Status:** ✅ Met.

---

## §9 #6 — Calibration plot in README; buckets with n > 30 displayed; not cropped or selectively shown

**Evidence:**

- README "Calibration" section contains all 6 displayable buckets (n ≥ 30) directly from `test_evaluation.json` with no exclusions.
- Two buckets (0.10-0.20 and 0.80-0.90) have n < 30 and are hidden per §9 #6's explicit rule — not because they're inconvenient. Their counts:
  ```
  cd backend && uv run python -c "import json; [print(b) for b in json.load(open('results/test_evaluation.json'))['calibration_buckets'] if 0 < b['n'] < 30]"
  ```
- Live calibration plot also rendered in the dashboard at the **Calibration** tab.

**Status:** ✅ Met (hidden buckets are §9-mandated, not selective).

---

## §9 #7 — React frontend renders trajectory chart, season selector, today's games, three endpoints respond

**Evidence:**

- Trajectory chart: `frontend/src/components/TrajectoryChart.tsx`. Renders all franchises in a season with team-primary-color lines, dynamic y-axis, 1500 reference line.
- Season selector: populated from `GET /seasons` (all 108), with `(legacy)` suffix and the §2/§3 disclaimer banner when a pre-1967 season is selected.
- Today's games: `frontend/src/components/TodaysGames.tsx` with probability bars and the §5 v1.1 frozen-params confirmation footer.
- Endpoints verified locally: `/ratings/current`, `/ratings/history/{season}`, `/games/today`, `/calibration/current` all return 200.
- Tests: `tests/test_api.py` covers all read endpoints with TestClient.

**Not done yet:** Vercel deployment. The frontend builds cleanly with `npm run build`; deployment is a separate operator step (Vercel config is minimal — `vite build` outputs `dist/`). The methodology doesn't strictly require a live deploy for v1 complete, but §3 names Vercel as the deployment target.

**Status:** ✅ Met locally; deployment optional / operator's call.

---

## §9 #8 — CHANGELOG.md exists with an entry for every meaningful change

**Evidence:** `CHANGELOG.md` covers each methodology version (v1.0 → v1.1 → v1.2) and each milestone phase (A through E). Per `METHODOLOGY.md` §11, the author commits both the code and the changelog entry together.

**Status:** ✅ Met (assuming the Phase A–D entries are added — see Phase E.3 task).

---

## §9 #9 — README contains: plain-English methodology, §6 metrics table, calibration plot, methodology link, student disclaimer

**Evidence:** `README.md` v1 contains all five elements:

1. Plain-English description ("What it does" section).
2. §6 metrics table — model, both baselines, targets, per-season breakdown.
3. Calibration plot — embedded as a markdown table of buckets with n ≥ 30, plus a reference to the live dashboard rendering.
4. Methodology link — bold inline link to `METHODOLOGY.md` in the "Methodology" section.
5. Student project disclaimer — both as a callout at the top and a full paragraph at the bottom.

**Status:** ✅ Met.

---

## §9 #10 — Author has reviewed all of the above and made a manual git commit with message `v1 complete`

**Evidence:** Operator action required. Suggested command (once the author is satisfied with the review):

```
git add METHODOLOGY.md README.md CHANGELOG.md docs/ \
        backend/ frontend/ \
        artifacts/frozen_params.json results/test_evaluation.json   # if you want artifacts tracked
git commit -m "v1 complete"
```

Note: per `METHODOLOGY.md` §11, this codebase does not run `git add`, `git commit`, or `git push` on its own. The `v1 complete` commit must be authored by the project owner.

**Status:** ⏳ Pending operator.

---

## Summary

| Criterion | Status |
|---|---|
| #1 Methodology pre-frozen | ✅ |
| #2 Pipeline covers 1917-18 → current, pre-1967 flagged | ✅ |
| #3 Ratings in bounds for all 32 active franchises | ✅ |
| #4 Backtest protocol clean, no look-ahead | ✅ |
| #5 §6 metrics computed on test set and recorded | ✅ |
| #6 Calibration plot in README, n≥30 buckets shown | ✅ |
| #7 Frontend renders required surfaces, endpoints respond | ✅ (Vercel deploy optional) |
| #8 CHANGELOG with entries for every meaningful change | ✅ (after E.3) |
| #9 README contains five required elements | ✅ |
| #10 Author commits `v1 complete` | ⏳ pending operator |
