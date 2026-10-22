# Deployment guide

Tilt deploys cleanly as a two-piece app: the FastAPI backend behind a container host and the Vite/React frontend on Vercel. Total managed setup time: ~15 minutes if you already have accounts.

The backend image carries all data and frozen artifacts (about 35 MB), refreshed at build time, so a cold start needs no network ingest.

This guide previously led with **Render**; the backend now runs on **Google Cloud Run** (first section). The Render notes are kept as a fallback. Render was chosen originally because it's truly free, doesn't require a credit card, and supports our `Dockerfile` directly. Alternatives are listed at the bottom.

---

## Backend — Google Cloud Run (current, since 2026-10-11)

The backend runs on **Cloud Run** in project `tilt-sports-kylan` (region `us-central1`), service `tilt-backend`, at <https://tilt-backend-xp2vlopuya-uc.a.run.app>.

- **Auto-deploy:** `.github/workflows/deploy-backend.yml` runs on every push to `main` that touches `backend/`, `cloudbuild.yaml` or the workflow itself. It authenticates with **Workload Identity Federation** (no keys or secrets; only `KylanHuynh7/Tilt` may impersonate `github-deployer@…`), runs `gcloud builds submit` with `cloudbuild.yaml` (build image → Artifact Registry `tilt` → `gcloud run deploy`), then smoke-tests `/health` and `/sports`.
- **Manual deploy:** `gcloud builds submit --config cloudbuild.yaml .` from the repo root (`.gcloudignore` keeps the upload to the backend).
- **Service settings:** 1 GiB memory, 1 vCPU, **min 0 / max 2 instances** (scales to zero when idle; at most 2 instances bounds cost), `CORS_ALLOWED_ORIGINS=https://tilt-nhl.vercel.app`.
- **Billing:** billing account "My Billing Account 1" with **Budget1 = $1/month**, alerting at 50 / 90 / 100%. Budgets alert; they do not cap spend. The instance cap is the hard limit.
- **Health check path:** use **`/health`**. Cloud Run reserves paths ending in `z`, so `/healthz` returns Google's 404 there.
- **Frontend:** Vercel's `VITE_API_BASE` points at the Cloud Run URL.
- **Nightly data refresh (since 2026-10-12):**
  - The same workflow also runs **every night at 11:00 UTC**. Each run executes `scripts/refresh_current.py` (the current season for all four sports, NHL box scores and the skater-projection state), then the **full test suite**, then builds. A failing test blocks the deploy.
  - Refreshed data is baked into the image, not committed: Cloud Run's disk is ephemeral, so the image's data *is* the site's data.
  - GitHub disables scheduled workflows after 60 days without repository activity; a push or a manual run restarts them.
- **Image cleanup:** Artifact Registry keeps the 5 newest images (cleanup policy), keeping storage inside the free tier.
- **Admin endpoints are locked:** every `/admin/refresh` returns 403 unless `ADMIN_TOKEN` is set, and production doesn't set it. Large or forced Cup simulations also need the token. This keeps strangers from burning CPU against the budget.
- **Cost target: ≤ $1/month.** Expected spend is about $0: Cloud Run, Cloud Build and Artifact Registry all sit inside their free tiers.

The Render instructions below are kept for reference only. Render hosted the backend until 2026-10-11 and its service is now suspended.

## Backend — Render (historical; suspended since 2026-10-12)

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

### Refreshing data

Production refreshes itself every night (above). To refresh **now**, run the **"Deploy backend (Cloud Run)"** workflow from the repository's Actions tab ("Run workflow"): refresh → tests → build → deploy, about 5 minutes.

Locally, either run the refresh script:

```bash
cd backend
uv run python -m scripts.refresh_current
```

or start the server with a token and call the per-sport endpoints:

```bash
ADMIN_TOKEN=pick-something uv run uvicorn app.main:app
curl -X POST -H 'X-Admin-Token: pick-something' localhost:8000/admin/refresh        # NHL
curl -X POST -H 'X-Admin-Token: pick-something' localhost:8000/nba/admin/refresh    # also /nfl, /mlb
```

### Pending one-shot test evaluations

Each script runs exactly once (`--confirm`, never `--force`) and refuses to run before its season's final is in the data. Google Calendar reminders exist for each.

| When | Command (from `backend/`) |
|---|---|
| After the 2026 World Series | `uv run python -m scripts.mlb_v2_evaluate --confirm` and `uv run python -m scripts.postseason_evaluate --sport mlb --confirm` |
| After Super Bowl LXI | `uv run python -m scripts.postseason_evaluate --sport nfl --confirm` (layer off; records n/a) |
| After the 2027 Stanley Cup Final | `uv run python -m scripts.evaluate_v3 --confirm` |

After each test: document the result in the sport's methodology and CHANGELOG, and remove that season from `QUARANTINE` in `backend/app/core/report_card.py` so the report card shows its totals.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| First load after idle takes a few seconds | Cloud Run scaled to zero; cold start | Expected (min instances 0 keeps cost at ~$0). Subsequent loads are fast. |
| Site data looks a day or more stale | Nightly workflow failed or was disabled | Check the Actions tab; a red run shows which sport's refresh or which test failed. Re-run it. |
| `POST /admin/refresh` returns 403 | Admin endpoints are disabled in production | Intended. Use the Actions workflow (above). |
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
| `PORT` | Backend | `8000` | Cloud Run (and Render / HF Spaces / Fly / Railway) inject this. |
| `ADMIN_TOKEN` | Backend | unset | Enables the `/admin/refresh` endpoints and large/forced Cup sims; unset in production. |
| `TILT_SKIP_PROJECTIONS` | Backend | unset | Set to skip the NHL projection-state background build (tests set this automatically). |
| `TILT_WORKERS` | Scripts | CPU count | Worker processes for the v3 / projection freezes. |
| `VITE_API_BASE` | Frontend (build-time) | `http://127.0.0.1:8000` | The backend URL. No trailing slash. |
