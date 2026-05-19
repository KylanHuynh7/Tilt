# Deployment guide

Tilt deploys cleanly as a two-piece app: the FastAPI backend behind a container host and the Vite/React frontend on Vercel. Total managed setup time: ~15 minutes if you already have accounts.

The backend ships with the full parquet cache committed (~2 MB), so cold start is ~1.5 s once the container is awake — no build-time data ingest needed.

This guide leads with **Render** as the primary backend target because it's truly free, doesn't require a credit card, and supports our `Dockerfile` directly. Alternatives are listed at the bottom.

---

## Backend — Render (free tier, no credit card)

1. **Push to GitHub** (already done if you cloned and are following along).
2. **Create a Render account.**
   - <https://render.com> → Sign up with GitHub or email (no credit card required for free Web Services).
3. **New Web Service.**
   - Render dashboard → New + → Web Service → Connect your Tilt repo.
4. **Configure the service.**
   - **Name:** `tilt-backend` (or whatever).
   - **Root Directory:** `backend`
   - **Runtime:** select **Docker** (Render reads the `Dockerfile`).
   - **Instance Type:** **Free**.
   - Leave the rest at defaults.
5. **Add the CORS env var.** Render → Environment → Add Environment Variable:
   ```
   Key:   CORS_ALLOWED_ORIGINS
   Value: https://YOUR-VERCEL-URL.vercel.app
   ```
   You can leave this empty for now and fill it in after the frontend is up.
6. **Create Web Service.** First build takes ~3-5 minutes (downloading the Docker base image + uv-installing deps). Render assigns a URL like `https://tilt-backend-abc1.onrender.com`. **Save this URL — the frontend needs it.**
7. **Smoke check.** `https://YOUR-RENDER-URL/healthz` in a browser. You should see:
   ```json
   {
     "ok": true,
     "seasons_in_cache": 108,
     "frozen_params": { "k_regular": 10.0, "k_playoff": 10.0, "decay_carry": 0.85, "home_bump": 40.0, "methodology_version": "2.0" }
   }
   ```

**Render free-tier caveats:**
- The instance sleeps after ~15 minutes of inactivity. First request after sleep takes ~30-60 s to wake (Render pulls the image, starts the container, runs the lifespan startup that builds the in-memory cache from the 108 parquets — about 1.5 s once running).
- 512 MB RAM, 0.1 shared CPU. We use ~150 MB at rest; plenty of headroom.
- Filesystem is ephemeral. `/admin/refresh` updates the running container but the new parquet vanishes on restart. See "Refreshing data" below.

---

## Frontend — Vercel (free, no credit card)

1. **Create a Vercel project.**
   - <https://vercel.com> → Add New → Project → Import the same GitHub repo.
2. **Configure the project.**
   - **Framework Preset:** Vite (auto-detected).
   - **Root Directory:** `frontend`
3. **Set the API base env var.** Vercel → Settings → Environment Variables, add:
   ```
   Key:   VITE_API_BASE
   Value: https://YOUR-RENDER-URL.onrender.com
   ```
   (No trailing slash. Apply to Production + Preview + Development.)
4. **Deploy.** Click Deploy. First build takes ~30 s. Vercel assigns a URL like `tilt-nhl.vercel.app`.
5. **Go back to Render** → Environment → update `CORS_ALLOWED_ORIGINS` to your Vercel URL. Render redeploys automatically (~30 s).
6. **Open the Vercel URL.** Trajectories, Today's Games, Calibration, and Cup odds should all render against your live backend.

> **First-load tip:** if the Render instance has been sleeping, the first dashboard fetch takes ~30-60 s while it wakes. A loading spinner appears in each panel during that wait. Subsequent loads are fast.

---

## Alternative backend hosts

### Hugging Face Spaces (free, no credit card, always-on)

Free tier doesn't sleep. The catch is your code is **public** on the free tier and the URL ends up under `huggingface.co`.

- <https://huggingface.co/new-space> → SDK: **Docker** → upload via Git: `huggingface.co/spaces/USERNAME/tilt`.
- Spaces uses port 7860 by default; the `Dockerfile` `$PORT` variable already handles this.
- Add a `README.md` to the Space root with the front-matter Spaces requires (the linked Tilt repo's README is fine).
- Set the CORS env var via the Space's **Settings → Variables and secrets**.
- URL becomes `https://USERNAME-tilt.hf.space`.

### Fly.io (free monthly credit, requires credit card)

Fly's "free allowance" is a monthly $5 credit applied to usage — covers one small always-on VM. They require a card on file even if you stay under the credit.

```bash
cd backend
fly launch                                                              # accepts Dockerfile, creates fly.toml
fly secrets set CORS_ALLOWED_ORIGINS=https://YOUR-VERCEL-URL.vercel.app
fly deploy
```

### Railway (paid, $5/month minimum)

Railway killed its free tier in 2023. Still a clean Dockerfile-deploy experience if you don't mind the cost.

- <https://railway.app> → New Project → Deploy from GitHub repo → Root Directory `backend`.
- Variables → `CORS_ALLOWED_ORIGINS=https://YOUR-VERCEL-URL.vercel.app`.
- Settings → Networking → Generate Domain.

---

## Post-deploy operations

### Refreshing today's data

```bash
curl -X POST https://YOUR-BACKEND-URL/admin/refresh
```

Re-ingests the current 2025-26 season parquet from the NHL API and rebuilds the historical cache (~10-30 s). The Cup-sim cache is also invalidated.

**Storage caveat:** free-tier container storage is ephemeral on every host listed above. The new parquet from `/admin/refresh` persists within the container's lifetime but disappears on idle-wake / redeploy. If you want updates to survive restarts, the simplest path is to refresh locally and push back to git:

```bash
cd backend
uv run python -m app.pipeline ingest --season 20252026 --force
git add data_cache/raw/20252026.parquet
git commit -m "data: refresh 20252026 ($(date -I))"
git push
```

Render auto-redeploys on push (~3 min), and the next dashboard load shows the fresh data.

### Updating the frozen v2 model

After the 2026 Stanley Cup Final concludes:

```bash
cd backend
uv run python -m app.pipeline ingest --season 20252026 --force
uv run python -m scripts.evaluate --confirm   # writes results/test_evaluation.json (snapshots v1 to test_evaluation_v1.json)
git add data_cache/ results/
git commit -m "v2 test eval — 2025-26"
git push
```

The backend host auto-redeploys and serves the v2 test numbers under `/calibration/current`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| First dashboard load hangs ~30-60 s | Render instance was sleeping; cold start | Expected on free tier. Subsequent loads are fast. |
| Frontend shows "Couldn't load …" for everything | Browser blocked by CORS | Confirm `CORS_ALLOWED_ORIGINS` on the backend includes the Vercel URL (no trailing slash) |
| `/games/today` returns 503 | Backend can't reach the NHL public API | Check the host's outbound network policy — Render/Fly/Spaces all allow outbound HTTPS by default |
| Backend `/healthz` says `seasons_in_cache: 0` | `data_cache/raw/` is missing from the image | Confirm `.dockerignore` doesn't exclude `data_cache`. The default project config ships parquets in the image. |
| `/calibration/current` returns 503 | `results/test_evaluation.json` missing | Confirm `results/` is COPYed in the Dockerfile (it is, by default) |
| Render build fails with "no Dockerfile detected" | Wrong root directory | Render → Settings → set Root Directory to `backend` |

---

## Env vars reference

| Var | Where | Default | Notes |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | Backend | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated. Set the Vercel URL here in prod. |
| `PORT` | Backend | `8000` | Render / HF Spaces / Fly / Railway all inject this. |
| `VITE_API_BASE` | Frontend (build-time) | `http://127.0.0.1:8000` | The backend URL. No trailing slash. |
