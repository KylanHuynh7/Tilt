# Tilt — NHL Rating System

An interpretable Elo-variant rating system for NHL teams that produces calibrated, game-by-game win probabilities. The goal is **honest calibration reporting**, not beating Vegas.

> Student project. Not a betting tool. Not a power ranking. Not a Vegas competitor.
> Pre-1967 seasons are available in the dashboard for historical exploration only and are excluded from all model evaluation.

## Status

- **v1 — shipped and locked** (commit `f7548f6`, 2026-05-18). The v1 model, v1 freeze, and v1 test-set evaluation are immutable per `METHODOLOGY.md` §10 #2.
- **v2 — feature-complete, evaluation pending.** All four pre-registered v2 features have landed: home-ice advantage (v2.0), Monte Carlo Cup probabilities (v2.1), live in-game win probability (v2.2), and live polling + hero-chart updates (v2.3). v2's final test-set evaluation against the 2025-26 season is gated on the 2026 Stanley Cup Final completing; `scripts/evaluate.py --confirm` runs that pass exactly once.

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

## v2 status — frozen, evaluation pending

Frozen v2 parameters (active artifact at [`backend/artifacts/frozen_params.json`](./backend/artifacts/frozen_params.json)):

```
K_regular   = 10.0
K_playoff   = 10.0
decay_carry = 0.85
home_bump   = 40.0   ← v2.0 §12 addition
```

Validation metrics on 2021-22 → 2024-25 (n = 5,594 predictions):

| | log-loss | Brier | ECE |
|---|---:|---:|---:|
| v2 model | 0.66219 | 0.23495 | **0.01528** |
| Static-rating baseline | 0.67872 | 0.24276 | 0.02368 |
| §6 target | < 0.685 | 0.235–0.245 | < 0.04 |

The validation ECE collapsed from v1's 0.0422 (on v1 validation) to v2's 0.0153 (on the larger v2 validation window) — confirming the §15 pre-registration that home-ice modeling would resolve v1's primary calibration failure.

**v2 test evaluation has not been run.** It is gated on the 2025-26 Stanley Cup Final completing per §12. When that happens, one invocation of:

```
uv run python -m scripts.evaluate --confirm
```

…produces `results/test_evaluation.json` (the v1 file is preserved as `test_evaluation_v1.json`) and locks the v2 numbers per §10 #2.

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
| `main.py` | FastAPI app + endpoints. | v1 + v2 |

### Scripts (`backend/scripts/`)

- `freeze_params.py` — runs the validation grid search, applies the §5 K_playoff≥K_regular constraint, writes `artifacts/frozen_params.json`. Auto-snapshots prior versions to `frozen_params_v{1,2}.json`.
- `evaluate.py` — **§10 #1 quarantined.** Loads frozen params, runs test seasons exactly once with `--confirm`, writes `results/test_evaluation.json`. Refuses to re-run without `--force`.
- `build_live_wp.py` — builds the `live_wp_v2.json` empirical lookup from ingested play-by-play.

### Endpoints

| | Path | Notes |
|---|---|---|
| GET | `/healthz` | Cache status + frozen params metadata |
| GET | `/seasons` | All 108 ingested seasons with pre-1967 flag |
| GET | `/ratings/current` | 32 active franchises sorted by rating desc |
| GET | `/ratings/history/{season}` | Per-game trajectory for any season; includes `cup_winner` + `cup_winner_franchise` |
| GET | `/games/today` | Today's matchups with pre-game WP; in-progress games also carry `live_state` + `live_wp` |
| GET | `/simulation/cup` | v2.1 Monte Carlo Cup probabilities for all 32 active franchises (0% for non-playoff teams) |
| GET | `/wp` | v2.2 stateless empirical WP: `?period=&time_remaining_s=&score_diff=` |
| GET | `/calibration/current` | §6 metrics + bucket data + targets (v1 results until v2 eval runs) |
| POST | `/admin/refresh` | Re-ingest current season + rebuild cache + invalidate Cup-sim cache |

### Frontend tabs (`frontend/src/App.tsx`)

- **Trajectories.** Full-width trajectory chart of every team's rating across the selected season. Cup-winning team's line is thicker / full-opacity with a `{TEAM} 👑` label at the endpoint. Hover tooltip flags the cup winner in their team color. When viewing 2025-26 (in-progress), a vertical bar chart of all 32 teams' Stanley Cup probabilities sits under the trajectory plot. Auto-refresh every 60s for the current season.
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

The repo is set up for one-click deploy to Vercel (frontend) + Railway/Render/Fly (backend) via the included `backend/Dockerfile`. The parquet cache (~2 MB) and all artifacts ship in the repo so the backend boots in ~1.5 s with no build-time data ingest. See **[`DEPLOY.md`](./DEPLOY.md)** for the step-by-step walkthrough including env vars (`CORS_ALLOWED_ORIGINS`, `VITE_API_BASE`) and the `/admin/refresh` ephemerality caveat for free-tier hosts.

### One-time setup for a fresh clone

```bash
cd backend
uv sync
uv run python -m app.pipeline ingest --all --skip-existing   # ~10 min  (score data, 108 seasons)
uv run python -m app.pbp_pipeline ingest --all               # ~15 min  (play-by-play goals, 15 seasons)
uv run python -m scripts.freeze_params --quiet               # ~25 min  (4-D v2 grid, 600 cells)
uv run python -m scripts.build_live_wp                       # ~5 s     (WP lookup from PBP)
# v2 test eval — only after the 2026 Cup Final completes:
# uv run python -m scripts.evaluate --confirm                # exactly once per §10 #1
```

After this the dashboard backend boots in ~1.5 s with full historical ratings, current ratings, today's games (with live WP for in-progress games), Cup probabilities, and the calibration tab populated.

## Tests

```bash
cd backend && uv run pytest
```

**154 tests** across pipeline, lineage, ratings, backtest, metrics, tuner, API, evaluate guardrails, V2.A home_bump, V2.B standings + cup_simulator, V2.C live_wp, and V2.D live_state.

## Disclaimer

Student project for the author's own learning. Not a betting tool, not a power ranking, not a Vegas competitor. The author makes no claim that this model beats market lines and is not responsible for any decisions made using its output.

**v1**: Brier on test set sits inside the pre-registered band; ECE target is missed. The miss is the documented systematic under-prediction of home wins (every calibration bucket below the diagonal), pre-registered as the expected signature of omitting home ice.

**v2**: Validation metrics suggest the home-ice fix resolves the v1 ECE issue, but the test evaluation is pending the 2026 Cup Final per §12 and that's the number that will count. Until then, all v2 claims should be read as "pre-registered expectations, not yet validated on held-out data."
