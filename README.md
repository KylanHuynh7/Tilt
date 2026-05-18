# Tilt — NHL Rating System

An interpretable Elo-variant rating system for NHL teams that produces calibrated, game-by-game win probabilities. The goal is honest calibration reporting, not beating Vegas.

## Status

**v1 — pre-release, thin vertical slice.** The methodology document is frozen at [v1.1](./METHODOLOGY.md) ([changelog](./CHANGELOG.md)). The first build milestone is a current-season slice: real NHL API ingest for 2025-26, the rating engine from Section 5, and the dashboard's two priority surfaces (full-width ratings trajectory chart + today's games card). Historical training from 1917-18, the walk-forward backtest, calibration evaluation, and the frozen-parameters artifact for `/games/today` land in the next milestone.

What v1 will deliver when complete is documented in `METHODOLOGY.md` Sections 3, 6, 7, and 9.

## Architecture

Decoupled three layers, per Section 3:

| Layer | Tech | Path |
|---|---|---|
| Data + model | Python 3.11+, uv | [`backend/`](./backend/) |
| API | FastAPI on Railway/Render | [`backend/app/main.py`](./backend/app/main.py) |
| Frontend | React + Vite, deployed on Vercel | [`frontend/`](./frontend/) |

## Running locally

```bash
# Backend (port 8000)
cd backend && uv sync && uv run uvicorn app.main:app --reload

# Frontend (port 5173) — separate terminal
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>.

See [`backend/README.md`](./backend/README.md) and [`frontend/README.md`](./frontend/README.md) for milestone-specific notes.

## Methodology

The complete methodology — pre-registered hypotheses, train/validation/test split, model specification, evaluation thresholds, failure modes, and binding constraints — is in [`METHODOLOGY.md`](./METHODOLOGY.md). It is the source of truth for v1 decisions; disagreements between this document and the codebase are resolved in favor of the methodology unless a formal amendment is committed.

## Disclaimer

This is a student project for the author's own learning. It is not a betting tool, not a power ranking, and not a Vegas competitor. Pre-1967 seasons are available in the dashboard for historical exploration only and are excluded from all model evaluation.
