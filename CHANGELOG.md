# Changelog

All meaningful code and methodology changes are recorded here, per Section 11 of `METHODOLOGY.md`.

## 2026-05-19 — METHODOLOGY.md v3.0-draft + v3.1-draft (PRE-CODE DRAFT, branch `v3-draft`)

**Branch:** `v3-draft`. Not merged to `main`. Drafted for review after v2's test evaluation locks (gated on the 2026 Stanley Cup Final).

Pre-code methodology draft for both pre-registered v3 features from the appendix:

- **§17 — v3.0-draft: roster-shock modeling.** Adds a transaction-driven dynamic K-factor boost. When a roster event (trade, FA signing, waiver claim) lands, the affected teams' K is temporarily elevated for the next `BOOST_WINDOW` games (default 10) by `BOOST_AMOUNT` (default 0.5), decaying linearly. Heuristic, low-data-dependency approach that deliberately avoids building a player-rating system (deferred to v4 as "Interpretation P"). New v3 train/val/test split: train 1967-2020 (unchanged), validation 2021-22 → 2025-26 (folds v2's test into v3 validation), test **2026-27** (held out, one full season wait after v2 lock). 6-D freeze grid (~9.6 k cells, ~5-6 h wall time). Open questions: NHL transactions data source, definition of "transaction," multi-trade days. None of these block the methodology; they block the code.

- **§18 — v3.1-draft: series-context K adjustment.** `K_playoff` becomes a function `K(round, series_state) = K_base * (1 + round_factor + elimination_factor)`. Resolves the v1/v2 tension where the unconstrained grid wanted `K_playoff < K_regular` — v3.1 hypothesis is that the unconstrained preference was masking *which* playoff games matter, not whether they matter overall. Sequential nested freeze: v3.0 first, then v3.1's 2-D sub-grid (24 cells, ~1 min) layered on top — the two features are nearly orthogonal, joint optimization deferred unless v3.0 lock shows it's needed.

- **§19 — v3.x candidate parking lot.** Four non-pre-registered ideas that surfaced during scoping: team-specific home advantage, schedule context, goalie-aware predictions, head-to-head UI explorer. Each gets its own numbered section if and when promoted to v3 scope.

No code written. No tests added. v1 and v2 artifacts untouched on `main`.

## 2026-05-19 — UI: NHL "broadcast graphics" dark theme

Theme refresh per user request after seeing the deployed dashboard looked flat. Adopts an NHL-branded dark aesthetic: charcoal background, silver-white text, NHL red (`#c8102e`) as the accent. Header gains a small red signal dot before the title, a 56px accent underline, and an uppercase wordmark feel. Tabs uppercase + spaced for a broadcast vibe; active tab gets red underline and a subtle background highlight. Probability bars get a slight inset shadow and bigger height for depth. Live games get a red glow + box-shadow ring. Team badges get a soft ring + drop shadow for premium feel.

Team color palette retuned for the dark theme (`frontend/src/teamColors.ts`):
- **BOS / PIT / LAK** flip back to their published gold/silver secondaries (their primary blacks vanish on dark).
- **COL / DAL / FLA / WPG / STL / TBL / TOR / VAN / MIN** get slightly lightened variants of their dark navy / green / burgundy primaries so the lines read against the dark bg.
- 23 other teams keep their original published primaries — they already read fine on dark.

METHODOLOGY.md §13.I: added a bullet documenting the theme + team-color coupling so a future contributor restoring the light theme also knows to restore the published primaries.

No methodology amendment. No backend code touched.

## 2026-05-19 — DEPLOY.md flipped to Render-first (free tier, no CC)

User constraint: no paid platforms for the backend. Render's free Web Service tier is still available and supports Dockerfile deploys directly, so it's now the primary walkthrough in `DEPLOY.md` (replacing Railway, which removed its free tier in 2023). Alternatives reordered:

- **Primary:** Render (free, no credit card, sleeps after 15 min idle with ~30-60 s cold start).
- **Alternative — always-on free:** Hugging Face Spaces with the Docker SDK. Free, no CC, code is public on the free tier.
- **Paid:** Fly.io (free monthly credit but requires CC) and Railway ($5/min) kept as honorable mentions.

No code changes. The `Dockerfile` was already host-agnostic (listens on `$PORT`), the CORS allow-list is already env-driven, and the parquet cache is already in the image. README's "Deploying" sentence updated to name Render as the recommended backend target.

No methodology amendment. §13.G "Deployment / operational limitations" already covers ephemeral container storage and idle-sleep cold start, which apply to Render the same way they applied to Railway.

## 2026-05-18 — Deploy-ready: Dockerfile + vercel.json + DEPLOY.md

The project now deploys cleanly to Vercel (frontend) + Railway/Render/Fly (backend) without per-deploy data ingest. The Parquet cache (~2 MB across 108 score seasons + 15 PBP seasons) is small enough to commit, so it's now tracked in git and ships in the container image. Backend cold start stays at ~1.5 s.

Backend:
  - `backend/Dockerfile`: python:3.12-slim, uv installed from the published image, layer-cached dep install before app code is copied. Listens on `$PORT` (Railway/Render/Fly inject it; defaults to 8000 locally).
  - `backend/.dockerignore`: excludes .venv, tests, scripts, caches.
  - `main.py`: CORS `allow_origins` is now read from the `CORS_ALLOWED_ORIGINS` env var (comma-separated), defaulting to the local-dev URLs. Existing tests still pass.

Frontend:
  - `frontend/vercel.json`: Vite preset, build/install commands, SPA rewrites.
  - No code changes; existing `VITE_API_BASE` handling already works against any backend URL.

Repo:
  - `.gitignore`: un-ignored `backend/data_cache/` with a note explaining why (deploy-ready snapshot).
  - All 123 parquet files now tracked (~2 MB total).

Docs:
  - `DEPLOY.md`: full walkthrough for Railway / Render / Fly + Vercel including env-var reference, post-deploy refresh procedure, free-tier ephemerality caveats, and a troubleshooting table.
  - `README.md`: added a "Deploying" section linking to DEPLOY.md.
  - `METHODOLOGY.md` §13: new subsection G "Deployment / operational limitations" documenting ephemeral container storage, idle-sleep cold start, and CORS-allowlist requirements. Subsequent subsections renumbered (G→H, H→I, I→J).

No methodology change; pure infra/operational addition. Tests: 154 still passing.

## 2026-05-18 — README refreshed for v2

Project README updated to reflect the v2 feature set. Added a Status block making the v1-locked / v2-evaluation-pending split unambiguous. v1 metrics table relabeled as the canonical v1 record per §10 #2; new v2 status block reports the validation numbers (LL 0.66219, Brier 0.23495, ECE 0.01528 across n=5,594) and explicitly notes that the v2 test evaluation is gated on the 2026 Stanley Cup Final.

Backend module table extended with `pbp_pipeline`, `standings`, `cup_simulator`, `live_wp`, `live_state`, marked by version of introduction. Scripts section lists `build_live_wp.py`. Endpoint table adds `/simulation/cup`, `/wp`, plus the new `cup_winner` fields on `/ratings/history`. Frontend section rewritten as a per-tab description with the new behaviors (cup-winner 👑 + crown, all-32 Cup odds bar chart on Trajectories; live WP overlay + period/clock on Today's games; team-colored badges for trademark-safe identity).

One-time-setup section now includes `pbp_pipeline ingest --all` (~15 min) and `build_live_wp` (~5 s) steps. Test count refreshed: 106 → 154. Disclaimer split into a v1 paragraph (numbers locked) and v2 paragraph (validation-only, test pending).

No methodology change; this is documentation refresh. No new §13 limitations introduced.

## 2026-05-18 — Cup probability panel below the trajectory chart

User-visible: when viewing the 2025-26 season on the Trajectories tab, a 32-team vertical bar chart now sits under the trajectory plot showing each team's Stanley Cup win probability from the v2.1 Monte Carlo sim. Bars sorted desc; teams not in the playoff field render at 0% with low opacity. Bars colored by each team's primary brand color (same palette as the trajectory lines and the Today's Games badges).

Backend (main.py):
  - `/simulation/cup` response extended to include all 32 active franchises rather than just the playoff field. Each row gets a `status` field with one of `alive`, `eliminated`, or `not_in_playoffs`. Teams not in the playoff field have `cup_probability: 0.0`. The change is additive; existing callers that read the `teams` array still work.

Frontend:
  - New `CupOdds` component (recharts BarChart, 260px tall, X-axis = team abbreviations rotated -45° for readability, Y-axis = Cup %).
  - `App.tsx` fetches `/simulation/cup` when entering the Trajectories tab and re-polls every 5 minutes (the sim is cheap but not free — 60s polling matches games/today's "I need to see this change fast" cadence, while Cup probabilities only move on completed games, so 5min is enough).
  - Panel hidden when viewing any season other than 2025-26 (no live Cup race for completed seasons; the 👑 marker on the trajectory chart is the historical analogue).
  - `api.ts`: new `CupTeam` + `CupResponse` types and `fetchCup()` helper.

No methodology change — the underlying Cup sim and rating model are unchanged. The panel is a new view on existing data, scoped to the in-progress season.

## 2026-05-18 — Cup winner 👑 marker on the trajectory chart

User-visible: when viewing a completed season's ratings trajectory, the Stanley Cup winner now gets a 👑 emoji at the end of their line, plus a thicker / higher-opacity line for visual prominence. In-progress seasons show no crown.

Backend:
  - `standings.cup_winner(season_id)`: returns the team-code champion for a season, derived from the SCF winner in the playoff bracket. Falls back to a hand-curated `CUP_WINNER_OVERRIDES` for the COVID-era bracket weirdness (2019-20, 2020-21 — both TBL, the published 8/4/2/1 chronological bucket can't disambiguate the non-standard formats).
  - `derive_playoff_state` rewritten from subset-membership (which mis-bucketed CF/SCF as R2 once all rounds completed — R1 winners are technically in every later round) to chronological bucketing (first 8 series = R1, next 4 = R2, etc.). All seasons since 2013 verified correct except the two COVID years handled via overrides.
  - `/ratings/history/{season}` adds `cup_winner` (team code) and `cup_winner_franchise` (stable franchise_id for chart join).

Frontend:
  - `TrajectoryChart`: when `cup_winner_franchise` matches a team, that line gets thicker (2.25 vs 1.5 stroke), full opacity, and a 👑 emoji rendered via `LabelList` at the line's last data point only.
  - `api.ts`: new `cup_winner` + `cup_winner_franchise` fields on `RatingsHistoryResponse`.

METHODOLOGY.md §13.D: added a bullet documenting the cup_winner derivation rule, the 8/4/2/1 bracket assumption, the COVID-era overrides, and the pre-1942 challenge-series caveat. Notes that the limitation affects only the dashboard's visual marker, not the rating model.

## 2026-05-18 — UI polish: center Today's Games card, colored team badges

Frontend tweaks to make the Today's Games tab feel less cramped and add team-color identity without trademark risk. Layout change: `.games-grid` switched from a 2-column grid to `flex-wrap: wrap` with `justify-content: center` so a single matchup centers cleanly and multiple matchups flow naturally as a row. Cards bumped to padding 22/28, max-width 640px, abbrev font 18px. New `TeamBadge` component renders a 44px circle filled with the team's primary color (already in `teamColors.ts`) with the three-letter abbreviation in white.

§13.H added documenting why we don't embed NHL team logos: registered trademarks, takedown risk on a student project. The colored-badge approach is the safe substitute. Previous §13.H "Methodology process limitations" renumbered to §13.I; content unchanged.

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
