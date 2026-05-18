# Tilt backend — v1 thin vertical slice

This is **milestone 1** of the v1 backend described in `../METHODOLOGY.md`. It is intentionally narrow:

- **In scope:** NHL API ingest for the current (2025-26) season only, in-memory Elo rating engine seeded at 1500 for every franchise, FastAPI app exposing the three priority endpoints (`/ratings/current`, `/ratings/history/{season}`, `/games/today`).
- **Out of scope (next milestone):** historical training back to 1967-68, the between-season decay rule, the walk-forward backtest, calibration evaluation, and the frozen-parameters artifact required by `/games/today` per `METHODOLOGY.md` v1.1 §5. Until that lands, `/games/today` returns `frozen_params: false` so the frontend can display an honest disclaimer.

## Running locally

Requires `uv` (already installed if you're reading this) and Python ≥ 3.11.

```bash
cd backend
uv sync                                # creates .venv and installs deps
uv run uvicorn app.main:app --reload   # serves on http://127.0.0.1:8000
```

Health check:

```bash
curl http://127.0.0.1:8000/healthz
```

## Tests

```bash
cd backend
uv run pytest
```

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | Liveness + last refresh timestamp |
| GET | `/ratings/current` | All 32 franchises, sorted by rating desc |
| GET | `/ratings/history/{season}` | Slice supports only `20252026` |
| GET | `/games/today` | Today's matchups with pre-game probabilities |
| POST | `/admin/refresh` | Manual refresh from the NHL API |
| GET | `/calibration/current` | **Not yet implemented** — needs historical training |

## Notes

- The NHL public API (`api-web.nhle.com`) is used directly without caching. This is fine for the slice and gets replaced by an idempotent cached pipeline in the next milestone.
- Refresh on app startup is best-effort — if the NHL API is unreachable, the app still serves seeded ratings and `/admin/refresh` can be retried later.
- Per `METHODOLOGY.md` §11, this codebase will not run `git add`, `git commit`, or `git push`. Commits are manual.
