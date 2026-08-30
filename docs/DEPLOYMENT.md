# Deployment Guide: Render (backend) + Vercel (frontend)

Manual, one-time setup steps to do yourself on the Render and Vercel dashboards.
The code is already prepped (CORS, env vars, startup DB seeding) - you just need
to connect accounts and set values. Follow in order; step 3 needs a URL from
step 2, and step 4 needs a URL from step 3.

## 0. Prerequisites

- This repo pushed to GitHub (it already is).
- An OpenAI API key (used by the agent policy for LLM decisions).

## 1. Deploy the backend on Render

1. Go to https://render.com and sign up / log in (GitHub login is easiest).
2. Click **New +** -> **Blueprint**.
3. Connect your GitHub account if prompted, then select this repository.
4. Render will detect `backend/render.yaml` and propose a service named
   `revenue-recovery-api`. Click through to create it.
   - If Render doesn't auto-detect the blueprint, instead click **New +** ->
     **Web Service**, pick this repo, set:
     - **Root Directory**: `backend`
     - **Runtime**: Python 3
     - **Build Command**: `pip install -r requirements.txt && python db.py`
     - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Before the first deploy finishes, open the service's **Environment** tab
   and add:
   - `OPENAI_API_KEY` = your real OpenAI key
   - `ALLOWED_ORIGINS` = `http://localhost:5173` for now (you'll update this
     in step 4 once you have your Vercel URL)
6. Save and let it deploy. Once live, copy the service's public URL, shown at
   the top of the Render dashboard - it looks like:
   `https://revenue-recovery-api.onrender.com`
7. Sanity check: open `https://revenue-recovery-api.onrender.com/api/health`
   in a browser. You should see `{"status":"ok"}`.

**Note on the free plan:** Render's free tier disk is ephemeral - the SQLite
database is wiped on every redeploy, and also whenever the instance spins
down from inactivity and later restarts. This is a known limitation of the
free tier, not a bug. The backend already handles it: on every startup, if
`revenue_recovery.db` is missing, it automatically re-initializes the schema
and re-seeds it from the CSV files committed under `backend/data/` (see the
`_ensure_db` startup hook in `backend/main.py`). This means:
- The dashboard will never come up empty/broken after a restart.
- Any decisions/outcomes/audit history from before the restart will be gone -
  there is no persistent volume on the free plan. If you need durability,
  upgrade to a paid Render plan and attach a persistent disk, or move to a
  managed Postgres database (out of scope for this setup).

## 2. Deploy the frontend on Vercel

1. Go to https://vercel.com and sign up / log in (GitHub login is easiest).
2. Click **Add New...** -> **Project**.
3. Import this same GitHub repository.
4. When configuring the project:
   - **Root Directory**: click "Edit" and set it to `frontend`
   - Vercel should auto-detect the **Framework Preset** as "Vite" (it reads
     `frontend/vercel.json`, which already sets the build command to
     `npm run build` and output directory to `dist`). Leave these as detected.
5. Before deploying, expand **Environment Variables** and add:
   - `VITE_API_BASE_URL` = `https://revenue-recovery-api.onrender.com/api`
     (use the exact URL you copied from Render in step 1.6, **with the `/api`
     suffix** - all backend routes are mounted under `/api`)
6. Click **Deploy**.
7. Once live, copy the project's public URL from the Vercel dashboard - it
   looks like: `https://your-project-name.vercel.app`

## 3. Connect the two: update CORS on Render

1. Go back to the Render dashboard -> your `revenue-recovery-api` service ->
   **Environment** tab.
2. Update `ALLOWED_ORIGINS` to the Vercel URL you copied in step 2.7, e.g.:
   `https://your-project-name.vercel.app`
   - If you want to keep testing locally against the deployed backend too,
     comma-separate multiple origins, no spaces needed around commas:
     `http://localhost:5173,https://your-project-name.vercel.app`
3. Save - Render will automatically redeploy the service with the new value.

## 4. Verify end to end

1. Open your Vercel URL in a browser.
2. The dashboard should load with data already populated (health chart,
   metrics) - this is the automatic startup seeding described above, no
   manual "Diagnose" click needed on a fresh deploy.
3. Open the browser DevTools Network tab and confirm API calls go to your
   Render URL and return `200`, not CORS errors. If you see a CORS error in
   the console, double check `ALLOWED_ORIGINS` on Render exactly matches your
   Vercel URL (including `https://`, no trailing slash).
4. Try the "1. Diagnose" / "2. Run baseline" / "3. Run agent" buttons to
   confirm the OpenAI-backed agent path works (needs `OPENAI_API_KEY` set
   correctly on Render).

## Redeploying after future code changes

- **Backend**: push to the connected branch (default `main`) - Render
  auto-deploys on push. Remember the DB resets on every redeploy (see the
  ephemeral-disk note above); this is expected.
- **Frontend**: push to the connected branch - Vercel auto-deploys on push.
- If you change `VITE_API_BASE_URL` or `ALLOWED_ORIGINS` after the fact,
  update them in the respective dashboard's Environment Variables and
  trigger a redeploy (Vercel requires a redeploy to pick up new env vars;
  Render picks them up automatically on save).
