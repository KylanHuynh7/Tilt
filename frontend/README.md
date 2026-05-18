# Tilt frontend — v1 thin vertical slice

Vite + React + TypeScript. Two surfaces only this milestone:

1. **Rating trajectories** — full-width line chart, all 32 franchises, season selector (2025-26 only in the slice).
2. **Today's games** — matchup cards with pre-game win-probability bars derived from current ratings.

Live in-game probabilities, the Cup-simulation hero updates, and historical seasons before 2025-26 are intentionally deferred per `../METHODOLOGY.md` (v1.1 §5 + appendix roadmap).

## Running locally

The backend must be running first on http://127.0.0.1:8000 (`cd ../backend && uv run uvicorn app.main:app --reload`).

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173.

## Configuration

`VITE_API_BASE` controls the backend URL (defaults to `http://127.0.0.1:8000`). Copy `.env.example` to `.env` and edit if needed.

## Build

```bash
npm run build
npm run preview
```

The Vercel deploy target uses this `build` script directly with no custom config — `vite build` outputs to `dist/`.
