# Changelog

All meaningful code and methodology changes are recorded here, per Section 11 of `METHODOLOGY.md`.

## 2026-05-18 — METHODOLOGY.md v2.3 + V2.D (live polling integration)

v2 continues. v2.3 wires the v2.2 stateless WP model into the dashboard's live flow. No new model logic; this is pure integration. New §16 documents the polling cadence (60 s, conditional on in-progress games), the live-state extraction rules, and the failure-containment story (a single bad PBP fetch never breaks `/games/today`). New §13.G consolidates the seven live-polling limitations (between-poll staleness, no SSE, per-request fan-out, intermission ambiguity, lazy re-engagement, no push notifications for state transitions, hero-chart depends on /admin/refresh).

Code:
  - `app/live_state.py`: NHL `/v1/gamecenter/{gid}/play-by-play` fetcher + parser, with score-max aggregation across goal events and time-remaining extraction from the latest play. Returns None on any failure so the caller can fall back.
  - `app/live_wp.py`: `get_model()` + `clear_cache()` for the runtime path.
  - `app/engine.py`: `todays_matchups` extended to fan out PBP fetches for LIVE/CRIT games and enrich each matchup with `live_state` and `live_wp` fields. Pre-game payload shape unchanged.
  - `frontend/src/api.ts`: new `LiveStateBlock` / `LiveWPBlock` types on Matchup.
  - `frontend/src/components/TodaysGames.tsx`: `GameCard` component now renders live period/clock, live score, and a second probability bar for the live WP when present. Pre-game bar dimmed; live bar full-opacity with a smoothing tag if the lookup hit a sparse bin.
  - `frontend/src/App.tsx`: 60 s polling for `/games/today` while any matchup is in progress; matching 60 s polling for `/ratings/history/20252026` while the Trajectories tab is viewing the current season.
  - 9 new tests in `test_live_state.py`.

Tests: 154 passing (was 145 at end of V2.C; 9 added).

## 2026-05-18 — METHODOLOGY.md v2.2 + V2.C (live in-game win probability)

v2 continues. v2.2 adds the third pre-registered v2 feature: live in-game win probability, implemented as **Interpretation B** — a separate empirical lookup model independent of the Elo rating engine. New §15 documents the bin structure (period × mins_remaining × clamped_score_diff), Bayesian smoothing for sparse bins (α=50, threshold=100), training window 2010-11 → 2024-25, and the relationship to §10 #1 (2025-26 is held out from the WP training corpus).

Code:
  - `app/pbp_pipeline.py`: async goal-event ingest from `/v1/gamecenter/{gameId}/play-by-play` per training-window game. Per-season parquet at `data_cache/pbp_goals/{season}.parquet` + manifest. CLI: `python -m app.pbp_pipeline ingest --all|--season|--since|--force`, `status`.
  - `app/live_wp.py`: minute-by-minute sample expansion, smoothed bin lookup, artifact roundtrip JSON.
  - `scripts/build_live_wp.py`: one-shot script that walks every PBP parquet, builds the model, writes `artifacts/live_wp_v2.json`, and prints spot-check WP at canonical states (game start, P3 with 1-goal lead, OT tied, etc.).
  - `app/main.py`: new endpoint `GET /wp?period=&time_remaining_s=&score_diff=` — stateless lookup returning home win probability + sample count + smoothing flag.
  - 11 new tests in `test_live_wp.py` covering clamp/bucket helpers, smoothing math, sample expansion for zero-goal and one-goal games, artifact roundtrip, integration sanity (home-win baseline, monotonicity in well-sampled bins).

V2.C results (15 training seasons, 19,092 games, 1.17M samples, 631 bins):
  - Game start (P1, 19:30 left, 0-0): WP=0.542 (matches empirical home win rate over 2010-2025)
  - P3 start with 1-goal lead: WP=0.772 (in §15 pre-registered [0.75, 0.85] band)
  - P3 1 min remaining, up 1: WP=0.933
  - P3 1 min remaining, up 5 (clamped): WP=1.000
  - All well-sampled bins monotone in score_diff at fixed (period, mins_remaining).

Live polling of in-progress games is deferred to v2.3 — V2.C exposes the stateless model only.

## 2026-05-18 — METHODOLOGY.md §13.F (Cup-sim approximations documented)

New subsection F under §13 (Known limitations) lists the five approximations the Cup simulator makes: rating-independent outcome-type sampling, hardcoded conference membership, regular-season-points-only higher-seed inference for not-yet-started series, single-season outcome distribution baseline, no special goalie/fatigue handling in playoff series. The original "F. Methodology process limitations" is renamed to G to preserve its content while making room.

## 2026-05-18 — METHODOLOGY.md v2.1 + V2.B (Monte Carlo Cup probabilities)

v2 continues. v2.1 adds the second pre-registered v2 feature: Monte Carlo Cup probabilities. New §14 documents the simulation algorithm (per-game rating updates within a single sim run, 10,000 sims per call, in-progress series resumed from current state), the §10 #1 quarantine reasoning (forward projection ≠ test evaluation), and pre-registered expectations (probabilities sum to 1.0, ±1% CI at N=10k). No change to the rating model itself — the frozen v2.0 artifact drives the sim.

## 2026-05-18 — METHODOLOGY.md §13 (known limitations consolidated)

New Section 13 collects every limitation surfaced during v1 development and v2.0 work into a single auditable page: scope-deferred features, design choices that bound expressivity, empirical tensions between methodology and data (notably the §5 K_playoff≥K_regular constraint cost), data-quality limitations including pre-1967 sparseness and isolated NHL API 5xx errors, franchise-lineage judgment calls (Hamilton→NY Americans, OAK/CGS/CLE merger, etc.), and methodology-process limitations (shrinking test sets, no cross-validation safety net, no external comparison anchor). Material is cross-referenced rather than duplicated; nothing already in §2/§4/§5/§8/§10/§12 was rewritten.

## 2026-05-18 — METHODOLOGY.md v2.0 + V2.A (home-ice advantage)

v2 begins. The v1 model is locked at commit `f7548f6`; v1 artifacts (`frozen_params_v1.json`, `test_evaluation_v1.json`) are preserved alongside the new v2 artifacts.

Methodology: new §12 introduces `HOME_BUMP` as a tunable rating-point bias applied to the home team in `win_probability`. The v1 calibration result (every bucket under-predicted home wins by 3-8 points) is the direct motivation — §5 explicitly predicted this would happen when omitting home ice. v2 train/val/test split: 1967-2020 train, 2021-22 → 2024-25 validation (former v1 test seasons folded in), **2025-26 as the new held-out test** (touched exactly once at v2 final evaluation after the 2026 Cup Final).

Code: `ratings.win_probability` accepts an optional `home_bump`. `backtest.BacktestParams` gains the field; `_apply_one_game` passes it through. `metrics.static_rating_probs` accepts it. `tuner.GridPoint` expands to four dimensions; `DEFAULT_GRID` grows from 100 cells to 600. `freeze_params.py` writes both `frozen_params.json` (latest) and `frozen_params_v2.json` (versioned snapshot) and preserves the v1 artifact untouched. `historical.FrozenParams` is backwards-compatible (defaults `home_bump` to 0 when missing).

V2.A pre-registered expectations (in §12): optimal HOME_BUMP ∈ [30, 70] Elo points; validation log-loss improves by ≥ 0.005 vs v1 on the same window; validation ECE drops below 0.04. v2 test-set evaluation is deferred until 2025-26 is complete.

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
