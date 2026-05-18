# Tilt — NHL Rating System

An interpretable Elo-variant rating system for NHL teams that produces calibrated, game-by-game win probabilities. The goal is **honest calibration reporting**, not beating Vegas.

> Student project. Not a betting tool. Not a power ranking. Not a Vegas competitor.
> Pre-1967 seasons are available in the dashboard for historical exploration only and are excluded from all model evaluation.

---

## What it does

For each NHL game from 1967-68 onward, Tilt maintains a rating per franchise (32 active + a small set of defunct franchises modeled for historical continuity). After each game, the home and away ratings are updated using a modified Elo rule that weights regulation / OT / shootout / tie outcomes differently (per `METHODOLOGY.md` §5). Between seasons, ratings are partially regressed toward the league mean (carry = 0.85). The model produces a single pre-game win-probability per matchup. The same parameters are used for live predictions and for the held-out test set, frozen before any test-set outcome was observed.

## Methodology

The complete methodology — pre-registered hypotheses, train/validation/test split, model spec, evaluation thresholds, failure modes, and binding constraints — is in **[`METHODOLOGY.md`](./METHODOLOGY.md)** (v1.2). It was written and frozen before any code; amendments are version-tagged and audit-logged. **The methodology is the source of truth** for v1 decisions; any disagreement between this document and the codebase is resolved in favor of the methodology unless a formal amendment is committed.

Key methodology commitments:
- **Walk-forward backtest**, no future information used at any point (§7).
- **Test set touched exactly once** at the end of model development (§10 #1).
- **All metrics reported regardless of which is most flattering** (§10 #5).
- **No silent exclusion** of seasons or game subsets to improve numbers (§10 #4).

## Final §6 results — held-out test set (2023-24 + 2024-25)

Frozen parameters used: `K_regular = 10.0`, `K_playoff = 10.0`, `decay_carry = 0.85`.
Frozen on **2026-05-18 03:36 UTC** from validation on 2021-22 + 2022-23 ([`backend/artifacts/frozen_params.json`](./backend/artifacts/frozen_params.json)).
Evaluated on **2026-05-18 03:48 UTC**, `n = 2,798` test predictions ([`backend/results/test_evaluation.json`](./backend/results/test_evaluation.json)).

| | log-loss | Brier | ECE | n | §6 verdict |
|---|---:|---:|---:|---:|:---:|
| **Model** | **0.67102** | **0.23921** | **0.05164** | 2,798 | log-loss **PASS**, Brier **PASS**, ECE **FAIL** |
| Static-rating baseline | 0.67871 | 0.24260 | 0.05282 | 2,798 | beaten on LL and Brier |
| Naive 50% baseline | 0.69315 | 0.25000 | 0.05111 | 2,798 | beaten on LL and Brier |
| §6 target | < 0.685 | 0.235–0.245 | < 0.04 | — | — |

**Per-season:**

| Season | log-loss | Brier | ECE | n |
|---|---:|---:|---:|---:|
| 2023-24 | 0.66568 | 0.23663 | **0.0382** ✓ | 1,400 |
| 2024-25 | 0.67637 | 0.24180 | **0.0654** ✗ | 1,398 |

**Honest reading:**

1. **The rating system has signal.** The model beats the naive 50% baseline on log-loss by 0.022 and on Brier by 0.011. It also beats the static-rating baseline by 0.008 log-loss, indicating that updating ratings during the test window adds value over end-of-validation static ratings.
2. **Brier landed inside the pre-registered band** of [0.235, 0.245] — the model is performing roughly as the v1.2 methodology predicted.
3. **ECE missed its §6 target** (0.0516 vs 0.04). The miss is driven almost entirely by 2024-25 (ECE 0.0654); 2023-24 alone meets the target at 0.0382. Reported as-is per §10 #5 — not tuned away. See "Known limitations" below.
4. **Constrained tuning.** During validation, the grid search would have picked `K_playoff = 6 < K_regular = 12`, which contradicts the pre-registered §5 claim that playoff games carry more information. The grid was constrained to `K_playoff ≥ K_regular` to honor §5. The unconstrained winner is preserved in the frozen-params artifact for transparency.

## Calibration

Bucketed predicted-vs-actual on the held-out test set (buckets with n < 30 hidden per §9 #6):

| Predicted prob. range | n | Mean predicted | Mean actual | Gap |
|---|---:|---:|---:|---:|
| 0.20 – 0.30 | 125 | 0.264 | 0.344 | **−0.080** |
| 0.30 – 0.40 | 445 | 0.358 | 0.413 | **−0.055** |
| 0.40 – 0.50 | 833 | 0.455 | 0.522 | **−0.068** |
| 0.50 – 0.60 | 815 | 0.546 | 0.574 | **−0.028** |
| 0.60 – 0.70 | 452 | 0.641 | 0.684 | **−0.043** |
| 0.70 – 0.80 | 125 | 0.734 | 0.816 | **−0.082** |

Every bucket shows the model under-predicting the actual home-team win rate by roughly 3–8 percentage points. This is the **calibration-plot systematic-skew finding** anticipated in `METHODOLOGY.md` §8: a consistent below-the-diagonal pattern across all buckets is the expected signature of the v1 model's omission of home-ice advantage (`METHODOLOGY.md` §5 — "All win probabilities are computed as if games were played on neutral ice. … home/away splits in the calibration plot may reveal systematic miscalibration as a direct result. Home ice adjustment is a candidate for v2."). Reported as a primary finding rather than fixed mid-evaluation.

The live calibration plot is rendered in the dashboard under the **Calibration** tab.

## Known limitations (pre-registered in §2 / §5 / §8)

- **No home-ice advantage modeling.** Most likely cause of the systematic under-prediction visible in every calibration bucket. Slated for v2.
- **No live in-game win probability.** `/games/today` returns pre-game probabilities only; live updates as the score moves are v2 scope.
- **No roster shock from trades or free agency.** A team's rating evolves through results alone, not transactions. v3 scope.
- **Early-season miscalibration.** Pre-registered as an expected weakness. Ratings carry over at 0.85 from the prior season; the model has no mechanism to express genuine roster-change uncertainty.
- **Pre-1967 data is best-effort.** Data consistency in that era is not guaranteed; those seasons are available for dashboard exploration only and excluded from all training/evaluation.

## Architecture

Decoupled three-layer per [`METHODOLOGY.md`](./METHODOLOGY.md) §3:

| Layer | Tech | Path |
|---|---|---|
| Data + model | Python 3.11+, uv | [`backend/`](./backend/) |
| API | FastAPI | [`backend/app/main.py`](./backend/app/main.py) |
| Frontend | React + Vite | [`frontend/`](./frontend/) |

### Backend modules (`backend/app/`)

| Module | Responsibility |
|---|---|
| `pipeline.py` | Idempotent NHL API ingest → one Parquet per season at `data_cache/raw/`. CLI: `python -m app.pipeline ingest --all`. |
| `seasons.py` | Season-id parsing, date range, pre-1967 flag. |
| `franchises.py` | Hand-curated lineage table: maps `(team_code, season)` → stable `franchise_id` across relocations, rebrands, and the 1978 OAK/CGS/CLE → MNS merger. |
| `ratings.py` | Elo primitives: `win_probability`, `apply_game`, `apply_decay`, `classify_outcome` (era-gated TIE detection). |
| `backtest.py` | Walk-forward replay across all seasons; applies decay + merger at boundaries; records snapshots + predictions. |
| `metrics.py` | §6 scoring: Brier, log-loss, ECE, calibration buckets, naive + static-rating baselines. |
| `tuner.py` | Grid search over `(K_regular, K_playoff, decay_carry)` against validation. |
| `historical.py` | Loads frozen params, runs full backtest at startup, caches per-season trajectories. |
| `engine.py` | Live NHL-API integration for `/games/today` and `/admin/refresh`. |
| `main.py` | FastAPI app + endpoints. |

### Scripts (`backend/scripts/`)

- `freeze_params.py` — runs the validation grid search, applies the §5 K_playoff≥K_regular constraint, writes `artifacts/frozen_params.json`.
- `evaluate.py` — **§10 #1 quarantined.** Loads frozen params, runs test seasons exactly once with `--confirm`, writes `results/test_evaluation.json`. Refuses to re-run without `--force`.

### Endpoints

| | Path | Notes |
|---|---|---|
| GET | `/healthz` | Cache status + frozen params metadata |
| GET | `/seasons` | All 108 ingested seasons with pre-1967 flag |
| GET | `/ratings/current` | 32 active franchises sorted by rating desc |
| GET | `/ratings/history/{season}` | Per-game trajectory for any season; defunct franchises tagged |
| GET | `/games/today` | Today's matchups with pre-game probabilities; `frozen_params: true` |
| GET | `/calibration/current` | §6 metrics + bucket data + targets |
| POST | `/admin/refresh` | Re-ingest current season + rebuild cache |

## Running locally

```bash
# Backend (port 8000)
cd backend && uv sync && uv run uvicorn app.main:app --reload

# Frontend (port 5173) — separate terminal
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>.

### One-time setup for a fresh clone

```bash
cd backend
uv sync
uv run python -m app.pipeline ingest --all --skip-existing   # ~10 min
uv run python -m scripts.freeze_params --quiet               # ~2.5 min
uv run python -m scripts.evaluate --confirm                  # exactly once per §10 #1
```

After this the dashboard backend can boot in ~1.5 s with full historical ratings, current ratings, today's games, and the calibration tab populated.

## Tests

```bash
cd backend && uv run pytest
```

**106 tests** across pipeline, lineage, ratings, backtest, metrics, tuner, API, and guardrails.

## Disclaimer

This is a student project for the author's own learning. It is not a betting tool, not a power ranking, and not a Vegas competitor. The author makes no claim that this model beats market lines and is not responsible for any decisions made using its output. The Brier score on the test set sits inside the pre-registered band; the ECE target is missed. The model has documented systematic miscalibration (consistent under-prediction of home wins) that is anticipated as a v2 fix candidate.
