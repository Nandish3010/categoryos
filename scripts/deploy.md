# Deploying CategoryOS

Backend on Modal (replay mode, no keys needed to serve the demo), frontend on Vercel. Deploying is a deliberate manual
step; CI never deploys.

## 0. Before you deploy

```bash
make test lint          # backend + frontend green
make record             # only if fixtures or metrics changed (the drift test tells you); commit the result
make requirements       # only if backend/uv.lock changed; commit backend/requirements.txt
```

## 1. Create the Modal secret (once)

Type the values yourself; they are never stored in the repo, the image or a file. Placeholders below.

```bash
modal secret create categoryos-secrets \
  MODEL_API_KEY=<meta model api key> \
  BASETEN_API_KEY=<baseten key> \
  DEMO_KEY=<a long random string>
```

Replay mode never calls a model, so the keys only matter if you later flip the deploy to live. `DEMO_KEY` unlocks live
calls (`X-Demo-Key`) and `/api/ledger` / `/api/admin/reset`.

## 2. Deploy the backend

```bash
# FRONTEND_ORIGIN is the Vercel URL (CORS). Use the production URL once it exists, then redeploy.
FRONTEND_ORIGIN=https://<your-app>.vercel.app modal deploy backend/modal_app.py
```

Defaults baked into the image: `MODEL_MODE=replay`, `DATA_DIR=/root/data/synthetic`, `FIXTURES_DIR=/root/fixtures`,
`DB_PATH` and `LEDGER_PATH` on the `categoryos-state` Volume (`/state`). The function runs with `max_containers=1`,
`scaledown_window=600` and `min_containers=0` (set `MIN_CONTAINERS=1` at deploy time to keep it warm for the judging
window). Modal prints the web URL, `https://<workspace>--categoryos-backend-fastapi-app.modal.run`.

Replay sessions are in memory and write nothing; the Volume is only used if a vendor's golden run fails validation (it is
then served from the mock fixtures, flagged `degraded` in `GET /api/mode`) or you switch the deploy to `MODEL_MODE=live`.

## 3. Deploy the frontend (Vercel)

1. Import the GitHub repo in Vercel. **Root Directory: `frontend/`**. Framework preset: Next.js.
2. Environment variable (Production and Preview): `NEXT_PUBLIC_BACKEND_URL=<the Modal URL from step 2>`.
   Never put `DEMO_KEY` or any model key in a `NEXT_PUBLIC_*` variable.
3. Deploy. If the Vercel URL differs from the `FRONTEND_ORIGIN` you used, redeploy the backend with the right one.

## 4. Smoke test

```bash
make smoke URL=https://<workspace>--categoryos-backend-fastapi-app.modal.run FRONTEND_URL=https://<your-app>.vercel.app
```

Checks `/health`, 8 stages, `mode=replay` (not degraded), 4 vendors, the lever and claims endpoints, a replay run streamed
to `done`, an asset, and that the built JS bundles contain no `DEMO_KEY` / `MODEL_API_KEY` strings. Exit code is non-zero
on any failure. The first request may take up to a minute while a scaled-to-zero container wakes (`COLD_START=120` to
wait longer). Re-run it after every deploy.

## Recording live runs later (optional, costs credits)

```bash
cd backend && MODEL_MODE=live RECORD=1 uv run python -m app.record --vendor V001   # needs keys in .env
```

This overwrites `backend/fixtures/golden/runs/V001.json` with `meta.source: "live"` and real timings. Commit it, redeploy,
smoke. Spend is counted against `MAX_SPEND_USD`.
