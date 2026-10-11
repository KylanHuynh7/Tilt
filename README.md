# Tilt — Sports Rating System

Interpretable rating systems that produce calibrated, game-by-game win probabilities, one pre-registered model per sport. The goal is **honest calibration reporting**, not beating Vegas.

| Sport | Status | Methodology |
|---|---|---|
| **NHL** | Live — v2 (evaluated, see below) | [`METHODOLOGY.md`](./METHODOLOGY.md) |
| **NBA** | Live — v1.1: pre-game model (all §6 targets PASS on test) + live in-game win probability | [`methodology/NBA.md`](./methodology/NBA.md) |
| **NFL** | Live — v1.1: pre-game model (all §6 targets PASS; playoff ECE flagged) + live win probability (4 of 5 live targets PASS) | [`methodology/NFL.md`](./methodology/NFL.md) |
| **MLB** | Live — v1.1: pre-game model (all §6 targets PASS; postseason flagged) + live win probability (**5 of 5** live targets PASS) | [`methodology/MLB.md`](./methodology/MLB.md) |
| **College football** | Live — v1.1: pre-game model (all §6 targets PASS; postseason flagged) + live win probability (4 of 5 live targets PASS; unreliable in overtime) | [`methodology/CFB.md`](./methodology/CFB.md) |

Everything below this table describes the NHL model unless stated otherwise. Each sport gets its own methodology document, written and approved before that sport's model code, with its own train/validation/test split and §13-style limitations.

> Student project. Not a betting tool. Not a power ranking. Not a Vegas competitor.
> Pre-1967 seasons are available in the dashboard for historical exploration only and are excluded from all model evaluation.

## Status

- **v1 — shipped and locked** (commit `f7548f6`, 2026-05-18). The v1 model, v1 freeze, and v1 test-set evaluation are immutable per `METHODOLOGY.md` §10 #2.
- **v2 — shipped and evaluated** (2026-10-10). All four pre-registered v2 features have landed: home-ice advantage (v2.0), Monte Carlo Cup probabilities (v2.1), live in-game win probability (v2.2), and live polling + hero-chart updates (v2.3). The one-shot test evaluation on 2025-26 **failed all three §6 targets** — see below.
- **Live season: 2026-27.** The dashboard's "current season" is now derived from the latest ingested parquet, not hardcoded.

## What it does

For each NHL game from 1967-68 onward, Tilt maintains a rating per franchise (32 active + a small set of defunct franchises modeled for historical continuity). After each game, the home and away ratings are updated using a modified Elo rule that weights regulation / OT / shootout / tie outcomes differently (per `METHODOLOGY.md` §5). Between seasons, ratings are partially regressed toward the league mean (carry = 0.85). The model produces a single pre-game win probability per matchup.

**v2 additions on top of that core:**

- **Home-ice advantage (v2.0 §12).** The home team gets a `+40` Elo bump added to its rating inside the win-probability formula. Tuned on the v2 validation window; pre-registered to fix v1's systematic under-prediction of home wins.
- **Monte Carlo Cup probabilities (v2.1 §14).** For every team in the current playoff field, a 10,000-run simulation of the remaining bracket produces a Cup-winning probability. In-progress series resume from current state; ratings evolve per simulated game (hot/cold streaks possible).
- **Live in-game win probability (v2.2 §15).** A separate empirical lookup `P(home wins | period, time remaining, score diff)` built from 15 seasons of historical play-by-play (1.17M minute-by-minute samples across 19,092 games). Independent of the Elo rating model.
- **Live polling integration (v2.3 §16).** For any in-progress game in `/games/today`, the backend fetches the current play-by-play, extracts the live state, and includes the live WP alongside the pre-game WP. The frontend polls every 60s while games are in progress; the trajectory chart auto-refreshes on the same cadence for the current season.

## Methodology

The complete methodology — pre-registered hypotheses, train/validation/test splits, model spec, evaluation thresholds, failure modes, and binding constraints — is in **[`METHODOLOGY.md`](./METHODOLOGY.md)** (v2.3). It was written and frozen before any code; every amendment is version-tagged and audit-logged. **The methodology is the source of truth** for all decisions; any disagreement between this document and the codebase is resolved in favor of the methodology unless a formal amendment is committed.

Key methodology commitments (unchanged from v1):

- **Walk-forward backtest**, no future information used at any point (§7).
- **Test set touched exactly once** per model version (§10 #1).
- **All metrics reported regardless of which is most flattering** (§10 #5).
- **No silent exclusion** of seasons or game subsets to improve numbers (§10 #4).

`METHODOLOGY.md` §13 consolidates every known limitation across the model, data, lineage choices, Cup-sim approximations, and live-polling layer.

## MLB v1 results — held-out test set (2022–2025)

Frozen on validation 2015–2021 (`K_regular 4, K_playoff 2, carry 0.60, home bump 25, margin-of-victory on, starting-pitcher scale c 3.0, α 0.1`), evaluated once on 2026-10-11.

| | log-loss | Brier | ECE | n | §6 verdict |
|---|---:|---:|---:|---:|:---:|
| **MLB model** | **0.67805** | **0.24258** | **0.01112** | 9,890 | log-loss **PASS**, Brier **PASS**, ECE **PASS** |
| Team-only Elo (no pitcher term) | 0.67880 | 0.24294 | 0.00860 | 9,890 | — |
| Home-rate baseline | 0.69152 | 0.24919 | 0.00730 | 9,890 | beaten (**PASS**) |
| Naive 50% | 0.69315 | 0.25000 | 0.02910 | 9,890 | beaten |
| §6 target | < 0.685 | 0.235–0.248 | < 0.03 | — | — |

> **⚠ Postseason:** on 171 playoff games the model's log-loss is **0.711, worse than a coin flip** (ECE 0.103). Treat October probabilities with caution. The starting-pitcher term helps only slightly overall (−0.0008 LL) and costs a little calibration.

## NFL v1 results — held-out test set (2022–2025)

Frozen on validation 2015–2021 (`K_regular 20, K_playoff 10, carry 0.60, home bump 35, margin-of-victory on`), evaluated once on 2026-10-11.

| | log-loss | Brier | ECE | n | §6 verdict |
|---|---:|---:|---:|---:|:---:|
| **NFL model** | **0.63440** | **0.22135** | **0.02870** | 1,139 | log-loss **PASS**, Brier **PASS**, ECE **PASS** |
| Home-rate baseline | 0.68768 | 0.24661 | 0.00620 | 1,139 | beaten on log-loss (**PASS**) |
| Naive 50% | 0.69315 | 0.24934 | 0.05360 | 1,139 | beaten |
| Static rating | 0.72076 | 0.25866 | 0.11050 | 1,139 | beaten |
| §6 target | < 0.660 | 0.200–0.235 | < 0.05 | — | — |

> **⚠ Playoff calibration flag:** playoff ECE is **0.170** (n = 52), above the 0.08 threshold. The sample is tiny, but per the pre-registered rule it is reported here rather than buried. Other caveats: 2023 alone has ECE 0.063, and early-season (weeks 1–4) ECE is 0.059.

## NBA v1 results — held-out test set (2024-25 + 2025-26)

Frozen on validation 2018-19 → 2023-24 (`K_regular 15, K_playoff 10, carry 0.65, home bump 40, margin-of-victory on`), evaluated once on 2026-10-10. Full breakdowns in [`backend/results/nba/test_evaluation.json`](./backend/results/nba/test_evaluation.json) and `methodology/NBA.md` §13.

| | log-loss | Brier | ECE | n | §6 verdict |
|---|---:|---:|---:|---:|:---:|
| **NBA model** | **0.60744** | **0.20991** | **0.02590** | 2,643 | log-loss **PASS**, Brier **PASS**, ECE **PASS** |
| Home-rate baseline | 0.68834 | 0.24760 | 0.01118 | 2,643 | beaten on log-loss (**PASS**) |
| Naive 50% | 0.69315 | 0.25000 | 0.05010 | 2,643 | beaten |
| Static rating | 0.70867 | 0.25345 | 0.09957 | 2,643 | beaten |
| §6 target | < 0.640 | 0.200–0.225 | < 0.04 | — | — |

Caveats reported alongside the pass: 2025-26 alone has ECE 0.0419 (just over target); the pre-registered late-season flag fired (late ECE 2.85× mid), but the model is *under*confident late (consistent with tanking), the opposite of the predicted rest effect; the pre-registered home-bump range (50–110) was missed at validation (chosen 40).

### NBA v1.1 — live in-game win probability

`logit P = β0 + β1·pre·(τ/2880) + β2·d/√(m+1)`, fitted on 2009-10 → 2017-18 play-by-play (11,488 games): β0 +0.151, β1 +1.478, β2 +0.665. Evaluated once on 2024-25 + 2025-26 (126,786 game-minute samples):

| | Q1 | Q2 | Q3 | Q4 | All |
|---|---:|---:|---:|---:|---:|
| Live log-loss | 0.599 | 0.533 | 0.438 | 0.283 | **0.464** |
| Pre-game held, log-loss | 0.608 | 0.608 | 0.608 | 0.608 | 0.608 |
| Live ECE | **0.050** | 0.032 | 0.017 | 0.011 | 0.026 |

Two of three §12 checks pass; **the tip-off check fails** (the model recalibrates the pre-game probability by up to 0.105 instead of echoing it), and Q1 calibration is worse than simply holding the pre-game number. Details in `methodology/NBA.md` §13.

## v1 results — held-out test set (2023-24 + 2024-25)

The v1 numbers below are **locked at their as-of-2026-05-18 values** per §10 #2 and remain the canonical v1 record regardless of any v2 changes.

Frozen v1 parameters: `K_regular = 10.0`, `K_playoff = 10.0`, `decay_carry = 0.85`, `home_bump = 0.0` (preserved at [`backend/artifacts/frozen_params_v1.json`](./backend/artifacts/frozen_params_v1.json)).

| | log-loss | Brier | ECE | n | §6 verdict |
|---|---:|---:|---:|---:|:---:|
| **v1 model** | **0.67102** | **0.23921** | **0.05164** | 2,798 | log-loss **PASS**, Brier **PASS**, ECE **FAIL** |
| Static-rating baseline | 0.67871 | 0.24260 | 0.05282 | 2,798 | beaten on LL and Brier |
| Naive 50% baseline | 0.69315 | 0.25000 | 0.05111 | 2,798 | beaten on LL and Brier |
| §6 target | < 0.685 | 0.235–0.245 | < 0.04 | — | — |

The v1 ECE miss is driven almost entirely by 2024-25 (ECE 0.0654); 2023-24 alone meets the target at 0.0382. Every calibration bucket showed the v1 model under-predicting the home team's win rate by 3–8 percentage points — the exact pre-registered signature (§5/§8) of omitting home ice. **v2.0 fixes this** by tuning a `home_bump` parameter on the v2 validation window.

## v2 results — held-out test set (2025-26)

Evaluated once on 2026-10-10 against the completed 2025-26 season (regular season + playoffs, Cup Final ended 2026-06-14). Locked per §10 #2; v1's record is preserved at [`backend/results/test_evaluation_v1.json`](./backend/results/test_evaluation_v1.json).

Frozen v2 parameters (active artifact at [`backend/artifacts/frozen_params.json`](./backend/artifacts/frozen_params.json)):

```
K_regular   = 10.0
K_playoff   = 10.0
decay_carry = 0.85
home_bump   = 40.0   ← v2.0 §12 addition
```

| | log-loss | Brier | ECE | n | §6 verdict |
|---|---:|---:|---:|---:|:---:|
| **v2 model** | **0.69315** | **0.24982** | **0.05851** | 1,394 | log-loss **FAIL**, Brier **FAIL**, ECE **FAIL** |
| Static-rating baseline | 0.70979 | 0.25747 | 0.08150 | 1,394 | beaten on all three |
| Naive 50% baseline | 0.69315 | 0.25000 | 0.01937 | 1,394 | tied on LL, beaten on Brier by 0.0002 |
| §6 target | < 0.685 | 0.235–0.245 | < 0.04 | — | — |

**v2 fails every pre-registered target on its test season and does no better than a coin flip on log-loss.** Reported as-is; no parameter is re-tuned (§10 #2). What the data shows (full write-up in `METHODOLOGY.md` §13.C):

- **Home ice shrank.** Regular-season home win rate: 52.4% (2022-23), 54.1% (2023-24), 56.3% (2024-25), then **52.2% in 2025-26**. `home_bump = 40` was tuned on a window that leaned on the high years; on the test season the model's mean home prediction was ~55.6% against an actual ~51.9%.
- **Overconfident at the extremes.** Games predicted at 70–80% for the home team were won 59% of the time (n = 58); 60–70% predictions were won 59% (n = 375).
- **The league reshuffled.** End-of-2024-25 ratings held static score *worse than a coin flip* on 2025-26 (LL 0.710), so carry-over information was unusually misleading this season. The model's in-season updates recovered most — but not all — of that.

Validation metrics for context (2021-22 → 2024-25, n = 5,599): LL 0.66219, Brier 0.23495, ECE 0.01531 (per `artifacts/frozen_params.json`; earlier README text quoted n = 5,594 / ECE 0.01528 in error). The gap between validation and test is the overfitting-to-validation risk §13.J flagged in advance.

## Architecture

Decoupled three-layer per [`METHODOLOGY.md`](./METHODOLOGY.md) §3:

| Layer | Tech | Path |
|---|---|---|
| Data + model | Python 3.11+, uv | [`backend/`](./backend/) |
| API | FastAPI | [`backend/app/main.py`](./backend/app/main.py) |
| Frontend | React + Vite | [`frontend/`](./frontend/) |

### Backend modules (`backend/app/`)

| Module | Responsibility | Added in |
|---|---|---|
| `pipeline.py` | Idempotent NHL `/score` ingest → one Parquet per season at `data_cache/raw/`. | v1 |
| `pbp_pipeline.py` | NHL `/gamecenter/play-by-play` goal-event ingest → `data_cache/pbp_goals/{season}.parquet`. | v2.2 |
| `seasons.py` | Season-id parsing, date range, pre-1967 flag. | v1 |
| `franchises.py` | Hand-curated lineage table covering relocations, rebrands, and the 1978 OAK/CGS/CLE → MNS merger. | v1 |
| `ratings.py` | Elo primitives: `win_probability` (with v2.0 `home_bump`), `apply_game`, `apply_decay`, `classify_outcome`. | v1 + v2.0 |
| `backtest.py` | Walk-forward replay across all seasons; applies decay + merger at boundaries. | v1 + v2.0 |
| `metrics.py` | §6 scoring: Brier, log-loss, ECE, calibration buckets, naive + static-rating baselines. | v1 |
| `tuner.py` | 4-D grid search over `(K_regular, K_playoff, decay_carry, home_bump)` against validation. | v1 + v2.0 |
| `standings.py` | Regular-season standings + playoff bracket state derivation from parquet (used by Cup sim). | v2.1 |
| `cup_simulator.py` | Monte Carlo Cup probabilities; per-game rating updates within a sim run. | v2.1 |
| `live_wp.py` | Empirical state-aware WP lookup; minute-by-minute sample expansion + Bayesian smoothing. | v2.2 |
| `live_state.py` | Async PBP fetch + parse for live in-progress games. | v2.3 |
| `historical.py` | Loads frozen params, runs full backtest at startup, caches per-season trajectories. | v1 |
| `engine.py` | Live NHL-API integration for `/games/today` (with v2.3 live WP enrichment) and `/admin/refresh`. | v1 + v2.3 |
| `main.py` | FastAPI app. NHL endpoints live on a router mounted at the root (original contract) **and** under `/nhl`; `GET /sports` lists sports. | v1 + v2 + Phase 0 |
| `core/elo.py` | Sport-agnostic Elo primitives (`expected`, `regress`). NHL `ratings.py` delegates to it. | Phase 0 |

### Scripts (`backend/scripts/`)

- `freeze_params.py` — runs the validation grid search, applies the §5 K_playoff≥K_regular constraint, writes `artifacts/frozen_params.json`. Auto-snapshots prior versions to `frozen_params_v{1,2}.json`.
- `evaluate.py` — **§10 #1 quarantined.** Loads frozen params, runs test seasons exactly once with `--confirm`, writes `results/test_evaluation.json`. Refuses to re-run without `--force`.
- `build_live_wp.py` — builds the `live_wp_v2.json` empirical lookup from ingested play-by-play.

### Endpoints

| | Path | Notes |
|---|---|---|
| GET | `/sports` | Every sport with its status (`live` / `in_development` / `planned`) |
| GET | `/healthz` | Cache status + frozen params metadata |
| GET | `/seasons` | All 108 ingested seasons with pre-1967 flag |
| GET | `/ratings/current` | 32 active franchises sorted by rating desc |
| GET | `/ratings/history/{season}` | Per-game trajectory for any season; includes `cup_winner` + `cup_winner_franchise` |
| GET | `/games/today` | Today's matchups with pre-game WP; in-progress games also carry `live_state` + `live_wp` |
| GET | `/simulation/cup` | v2.1 Monte Carlo Cup probabilities for all 32 active franchises (0% for non-playoff teams); `playoffs_started: false` with no teams before the bracket exists |
| GET | `/wp` | v2.2 stateless empirical WP: `?period=&time_remaining_s=&score_diff=` |
| GET | `/calibration/current` | §6 metrics + bucket data + targets (v2 test results on 2025-26) |
| POST | `/admin/refresh` | Re-ingest current season + rebuild cache + invalidate Cup-sim cache |

Every NHL path above is also served under `/nhl` (e.g. `/nhl/games/today`).

NBA endpoints (`backend/app/nba/api.py`) use the same response shapes under `/nba`: `/nba/seasons`, `/nba/ratings/current`, `/nba/ratings/history/{season}`, `/nba/games/today` (pre-game probability + live score/clock from ESPN), `/nba/calibration/current` (adds the home-rate baseline, §8 flags and breakdowns), `POST /nba/admin/refresh`. The NBA cache is built lazily on first request (~0.6 s).

### Frontend

`frontend/src/App.tsx` is the multi-sport shell: header + sport switcher (NHL / NBA / NFL / MLB), path-based routing (`/nhl`, `/nba`, …; `/` is NHL), and a per-sport accent color via `data-sport` on `<html>`. Each sport lives in `frontend/src/sports/{sport}/`. Shared pieces: `frontend/src/http.ts` (fetch), `frontend/src/types.ts` (response shapes), `frontend/src/components/` (trajectory chart, game cards, calibration panel, parameterized by color lookup / league / period labels).

### NHL tabs (`frontend/src/sports/nhl/NhlDashboard.tsx`)

- **Trajectories.** Full-width trajectory chart of every team's rating across the selected season. Cup-winning team's line is thicker / full-opacity with a `{TEAM} 👑` label at the endpoint. Hover tooltip flags the cup winner in their team color. When viewing the in-progress season and its playoff bracket exists, a vertical bar chart of all 32 teams' Stanley Cup probabilities sits under the trajectory plot. Auto-refresh every 60s for the current season.
- **Today's games.** Card per matchup: team-colored badges (primary brand colors, no trademarked logos — see §13.H), pre-game probability bar, plus a live probability bar + period/clock for any in-progress game. Polls every 60s when there are live games.
- **Calibration.** §6 metrics table for the model + both baselines, calibration plot rendered from the bucket data.

## Running locally

```bash
# Backend (port 8000)
cd backend && uv sync && uv run uvicorn app.main:app --reload

# Frontend (port 5173) — separate terminal
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>.

## Deploying

The repo is set up for free-tier deploy to **Vercel** (frontend) + **Render** (backend) via the included `backend/Dockerfile` — no credit card required for either. The parquet cache (~2 MB) and all artifacts ship in the repo so the backend boots in ~1.5 s once awake. See **[`DEPLOY.md`](./DEPLOY.md)** for the step-by-step walkthrough, alternative hosts (Hugging Face Spaces, Fly.io, Railway), env-var reference, and the `/admin/refresh` ephemerality caveat for free-tier hosts.

### One-time setup for a fresh clone

```bash
cd backend
uv sync
uv run python -m app.pipeline ingest --all --skip-existing   # ~10 min  (score data, 108 seasons)
uv run python -m app.pbp_pipeline ingest --all               # ~15 min  (play-by-play goals, 15 seasons)
uv run python -m scripts.freeze_params --quiet               # ~25 min  (4-D v2 grid, 600 cells)
uv run python -m scripts.build_live_wp                       # ~5 s     (WP lookup from PBP)
# v2 test eval has already run (2026-10-10) — do NOT re-run; results are locked per §10 #2
```

After this the dashboard backend boots in ~1.5 s with full historical ratings, current ratings, today's games (with live WP for in-progress games), Cup probabilities, and the calibration tab populated.

## Tests

```bash
cd backend && uv run pytest
```

**158 tests** across pipeline, lineage, ratings, backtest, metrics, tuner, API, evaluate guardrails, V2.A home_bump, V2.B standings + cup_simulator, V2.C live_wp, and V2.D live_state.

## Disclaimer

Student project for the author's own learning. Not a betting tool, not a power ranking, not a Vegas competitor. The author makes no claim that this model beats market lines and is not responsible for any decisions made using its output.

**v1**: Brier on test set sits inside the pre-registered band; ECE target is missed. The miss is the documented systematic under-prediction of home wins (every calibration bucket below the diagonal), pre-registered as the expected signature of omitting home ice.

**v2**: Validation metrics suggested the home-ice fix resolved the v1 ECE issue, but on the held-out 2025-26 season v2 failed all three §6 targets and tied the coin-flip baseline on log-loss. The pre-registered expectation did not hold up; that is the result.
