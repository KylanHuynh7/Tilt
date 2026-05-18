# Changelog

All meaningful code and methodology changes are recorded here, per Section 11 of `METHODOLOGY.md`.

## 2026-05-18 — v1 ready for `v1 complete` commit

All §9 stopping criteria met except #10 (operator-action commit). The frozen v1 model passes log-loss and Brier targets on the held-out test set, misses ECE by 0.012 (driven by 2024-25 alone; 2023-24 meets the target). Documented systematic under-prediction of home wins across all buckets — anticipated v2 fix is home-ice modeling. See [`docs/STOPPING_CRITERIA.md`](./docs/STOPPING_CRITERIA.md) for the per-criterion walkthrough.

Final test-set numbers (n=2,798): model LL=0.67102, Brier=0.23921, ECE=0.05164. Beats both baselines on LL and Brier.

## 2026-05-18 — Phase E (release prep)

- README assembled per §9 #9: methodology summary, §6 metrics table, calibration buckets (n ≥ 30), methodology link, student disclaimer.
- `docs/STOPPING_CRITERIA.md` walkthrough mapping each §9 criterion to its evidence.
- This changelog entry covering Phases A–D below.

## 2026-05-18 — Phase D (frontend + API wired to frozen model)

- New `backend/app/historical.py` loads `artifacts/frozen_params.json`, replays every ingested season with the v1.2 engine, caches per-season per-franchise trajectories at startup (~1.5 s).
- Rewrote `backend/app/engine.py` to delegate ratings to `historical` and own only the live `/games/today` NHL schedule lookup + on-demand refresh.
- New endpoints: `/seasons` (108 rows with `pre_1967` flag), `/calibration/current` (reads `test_evaluation.json`). `/games/today` flips `frozen_params: true`. `/ratings/history/{season}` extended to any season with defunct-franchise tagging.
- Frontend gained a third tab "Calibration" with the §6 metrics table + bucket plot. Season selector populates all 108 seasons; pre-1967 selection shows the §2/§3 disclaimer banner. Trajectory chart's y-axis now auto-scales.
- 7 new FastAPI TestClient tests in `tests/test_api.py`. 106 backend tests total.

## 2026-05-18 — Phase C (validation freeze + test-set evaluation)

- New `backend/app/metrics.py`: Brier, log-loss (with eps clipping), ECE, calibration buckets, naive and static-rating baselines per §6.
- New `backend/app/tuner.py`: grid search over (K_regular, K_playoff, decay_carry); selection by lowest log-loss with deterministic tiebreaks (ECE then Brier).
- New `backend/scripts/freeze_params.py`: runs the grid, applies the §5 K_playoff ≥ K_regular constraint, writes `artifacts/frozen_params.json`. Frozen winner: **K_regular=10.0, K_playoff=10.0, decay_carry=0.85**. The unconstrained winner (K=12/6/c=0.85) is preserved in the artifact for transparency.
- New `backend/scripts/evaluate.py`: §10 #1 quarantined test-set evaluator. Refuses to run without `--confirm`; refuses to overwrite existing results without `--force`. Run exactly once on 2026-05-18 03:48 UTC.
- Tests: 16 metrics tests + 4 tuner tests + 2 evaluate-guardrail tests.

## 2026-05-18 — Phase B (full rating engine: lineage, decay, ties, mergers)

- New `backend/app/franchises.py`: hand-curated lineage table covering 8 modern relocations, 2 multi-rebrand franchises (TOR/DET), 6 pre-1967 defunct franchises, and the OAK/CGS/CLE → MNS merger per §4 v1.2.
- New `backend/app/backtest.py`: walk-forward replay engine. Loads Parquet seasons in order, applies cross-season decay, joins to franchise lineage, seeds expansion teams at 1500 on first appearance, applies the 1978 merger (simple-average rule).
- Extended `backend/app/ratings.py`: `apply_decay()` per §4; `classify_outcome()` with era-gated TIE detection that raises `ValueError` on impossible post-2005-06 equal-score regulation games.
- Tests: 15 lineage transition tests + 17 ratings_v2 tests + 10 backtest integration tests. Full smoke replay 1967-68 → 2021-22 ran in ~1 s with 55,305 games processed and league mean exactly 1500.

## 2026-05-18 — Phase A (idempotent NHL API ingest)

- New `backend/app/pipeline.py`: pulls every game from `/v1/score/{date}` across each season's window and writes one Parquet per season to `backend/data_cache/raw/`. Atomic writes via tmp+rename. Manifest at `data_cache/manifest.json`.
- New `backend/app/seasons.py`: season-id parsing, date range, pre-1967 flag.
- CLI: `python -m app.pipeline ingest --season|--all|--since`, `list`, `status`.
- Tolerant of persistent 5xx errors (treats as empty day) so the NHL API serving 500 for some preseason dates doesn't kill a multi-season run.
- Ingested all **108 seasons** (1917-18 → 2025-26), ~72,698 total game rows on disk.

## 2026-05-17 — METHODOLOGY.md v1.2
Resolves a single ambiguity introduced in v1.1 §4: how the OAK / CGS / CLE → MNS merger of 1978 should affect the surviving franchise's rating. v1.2 specifies the **simple average** rule — at the start of 1978-79, the Dallas Stars lineage (then MNS) begins the season at the arithmetic mean of MNS's and the absorbed chain's final 1977-78 ratings, after which the standard between-season decay applies. Resolved before any backtest evaluation or parameter tuning; the held-out test set has not been touched. The same rule applies by default to any future merger.

## 2026-05-17 — METHODOLOGY.md v1.1
Folded six pre-code clarifications into the methodology document before any implementation work. No model behavior was introduced that was not implied by v1.0; all changes resolve ambiguities flagged during a methodology review:

1. Section 4 — Expansion teams start at exactly 1500 in their debut season with no decay step applied; the decay rule applies normally from season 2 onward. Applies uniformly to the 1967-68 expansion six, Vegas 2017-18, Seattle 2021-22, etc.
2. Section 4 — Franchise rating persists across relocations. The new-city team inherits the prior-city team's most recent rating with no reset. Documented examples cover Atlanta→Calgary, Colorado Rockies→New Jersey, Minnesota North Stars→Dallas, Quebec→Colorado, Hartford→Carolina, Atlanta Thrashers→Winnipeg, and the California/Cleveland→Minnesota merger.
3. Section 5 — Tie outcome weight is 0.50 for both teams (pre-2005-06 seasons only). Added as a row to the outcome weights table; fixed, not tunable.
4. Section 5 — Playoff K=10 is uniform across all playoff games regardless of round or series state. Series-context adjustment remains deferred to V3.
5. Section 5 — `/games/today` must compute live probabilities using the parameter set frozen at the end of validation. Rating state updates as new results land; parameters do not. Stated as a code-level invariant.
6. Sections 2 and 6 — Brier score upper bound tightened from 0.250 to 0.245, bringing Brier target stringency roughly in line with the log-loss target (<0.685).
