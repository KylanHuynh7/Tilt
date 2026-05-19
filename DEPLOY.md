# Deployment guide

Tilt deploys cleanly as a two-piece app: the FastAPI backend behind a container host (Railway, Render, Fly — anything that runs Docker images) and the Vite/React frontend on Vercel. Total managed setup time: ~15 minutes if you already have accounts.

The backend ships with the full parquet cache committed (~2 MB), so cold start is ~1.5 s — no build-time data ingest needed.

---

## Backend — Railway, Render, or Fly

This guide uses Railway as the running example. Render and Fly follow the same pattern with their respective dashboards; the `backend/Dockerfile` is portable across all three.

1. **Push to GitHub** (already done if you cloned and are following along).
2. **Create a Railway project.**
   - <https://railway.app> → New Project → Deploy from GitHub repo.
   - Select your fork of the Tilt repo.
3. **Configure the service.**
   - **Root directory:** `backend`
   - **Build:** Railway auto-detects `Dockerfile` — no extra config needed.
   - **Start command:** also auto-detected from the `CMD` in `Dockerfile`.
4. **Set the CORS env var.** In Railway → Variables, add:
   ```
   CORS_ALLOWED_ORIGINS=https://YOUR-VERCEL-URL.vercel.app
   ```
   You can leave this empty for now and come back after the frontend is up. The backend will work without it; the frontend just won't be able to call it from a browser.
5. **Generate a domain.** Railway → Settings → Networking → Generate Domain. You'll get something like `tilt-backend-production.up.railway.app`. **Save this URL — the frontend needs it.**
6. **Smoke check.** Hit `https://YOUR-RAILWAY-URL/healthz` in a browser. You should see:
   ```json
   {
     "ok": true,
     "seasons_in_cache": 108,
     "frozen_params": { "k_regular": 10.0, "k_playoff": 10.0, "decay_carry": 0.85, "home_bump": 40.0, "methodology_version": "2.0" }
   }
   ```

### Render

Same flow, different UI:

- **Web Service → New** → connect GitHub → pick the repo.
- **Root Directory:** `backend`
- **Runtime:** Docker (auto-detected from Dockerfile).
- **Environment:** add `CORS_ALLOWED_ORIGINS`.
- Render assigns a `*.onrender.com` URL.

### Fly

```bash
cd backend
fly launch  # accepts Dockerfile, creates fly.toml
fly secrets set CORS_ALLOWED_ORIGINS=https://YOUR-VERCEL-URL.vercel.app
fly deploy
```

---

## Frontend — Vercel

1. **Create a Vercel project.**
   - <https://vercel.com> → Add New → Project → Import the same GitHub repo.
2. **Configure the project.**
   - **Framework Preset:** Vite (auto-detected).
   - **Root Directory:** `frontend`
3. **Set the API base env var.** Vercel → Settings → Environment Variables, add:
   ```
   VITE_API_BASE = https://YOUR-RAILWAY-URL
   ```
   (No trailing slash. Apply to Production + Preview + Development.)
4. **Deploy.** Click Deploy. First build takes ~30 s.
5. **Note the Vercel URL.** Vercel assigns something like `tilt-nhl.vercel.app`. **Go back to your backend host's `CORS_ALLOWED_ORIGINS` env var and put this URL in.**
6. **Redeploy the backend** so the new CORS value takes effect.
7. **Open the Vercel URL.** Trajectories, Today's Games, Calibration, and Cup odds should all render against your live backend.

---

## Post-deploy operations

### Refreshing today's data

```bash
curl -X POST https://YOUR-RAILWAY-URL/admin/refresh
```

Re-ingests the current 2025-26 season parquet from the NHL API and rebuilds the historical cache. Takes ~10-30 s. The Cup-sim cache is also invalidated so the next `/simulation/cup` request returns fresh numbers.

**Storage caveat:** Railway and Render's default container storage is ephemeral. The new parquet from `/admin/refresh` will persist within the container's lifetime but disappears on redeploy or restart. If you want persistent updates between redeploys, mount a Railway Volume at `/app/data_cache/raw` (Railway → Settings → Volumes), or commit the updated parquet back to the repo and let your deploy hook pick it up.

### Updating the frozen v2 model

After the 2026 Stanley Cup Final concludes:

```bash
# Locally (assuming you have a local checkout with parquets up to date):
cd backend
uv run python -m app.pipeline ingest --season 20252026
uv run python -m scripts.evaluate --confirm   # writes results/test_evaluation_v2.json
git add data_cache/ results/ && git commit -m "v2 test eval"
git push
```

The backend host will auto-redeploy on push and serve the v2 test numbers under `/calibration/current`.

### Cold-start cost on free tiers

Both Render's free tier and Railway's trial put the container to sleep after ~15 minutes of inactivity. First request after sleep takes ~5-10 s to wake. Acceptable for a portfolio project; for production traffic, upgrade to a paid tier with always-on.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Frontend shows "Couldn't load …" for everything | Browser blocked by CORS | Confirm `CORS_ALLOWED_ORIGINS` on the backend includes the Vercel URL (no trailing slash) |
| `/games/today` returns 503 | Backend can't reach the NHL public API | Check the host's outbound network policy — Railway/Render/Fly all allow outbound HTTPS by default |
| Backend `/healthz` says `seasons_in_cache: 0` | `data_cache/raw/` is missing | Confirm `.dockerignore` doesn't exclude `data_cache`. The default project config ships parquets in the image |
| `/calibration/current` returns 503 | `results/test_evaluation.json` missing from the image | Confirm `results/` is COPYed in the Dockerfile (it is, by default) |

---

## Env vars reference

| Var | Where | Default | Notes |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | Backend | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated. Set the Vercel URL here in prod. |
| `PORT` | Backend | `8000` | Railway / Render / Fly all inject this. |
| `VITE_API_BASE` | Frontend (build-time) | `http://127.0.0.1:8000` | The Railway/Render/Fly URL of the backend. No trailing slash. |
