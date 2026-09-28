# Deploying FloorReplay on free hosting

The public demo runs in **public mode**: imports, floor notes, and fork
endpoints are absent (not hidden), suite/comparison execution is local-only,
and single replay executions are rate limited per client with the
saved-report fallback available. Everything below fits the free tiers.

## Topology

| Piece | Service | Plan |
|---|---|---|
| PostgreSQL 17 | [Neon](https://neon.tech) | Free (always on) |
| FastAPI backend | [Render](https://render.com) web service | Free |
| React frontend | Render static site | Free |

## 1. Create the Neon database

1. Create a Neon project (region closest to your Render region).
2. Copy the **pooled** connection string. It looks like
   `postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`.
3. Convert it to the SQLAlchemy form by replacing the scheme:
   `postgresql+psycopg://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`.

## 2. Deploy the backend on Render

1. Push this repository to GitHub, then in Render choose **New → Blueprint**
   and point it at the repo — `render.yaml` defines both services.
2. Fill in the sync variables when prompted:
   - `FLOORREPLAY_DATABASE_URL`: the Neon URL from step 1.
   - `FLOORREPLAY_CORS_ORIGINS`: JSON array with your frontend URL, e.g.
     `["https://flooreplay-frontend.onrender.com"]`.
   - `VITE_API_BASE` (frontend service): `https://<your-api>.onrender.com/api/v1`.
   - `FLOORREPLAY_OPENAI_API_KEY`: optional; leave empty to use the offline
     rule-baseline parser.
3. The backend start command runs `alembic upgrade head`, seeds the synthetic
   fixtures (`FLOORREPLAY_SEED_ON_START=1`, idempotent and content-addressed),
   then starts uvicorn. Startup recovery marks any attempt left `RUNNING` by
   a crashed process as `INTERRUPTED`.

Notes on the free tier:

- Render free services sleep after ~15 minutes idle; the first request pays a
  cold start. The saved-report fallback exists precisely so a sleeping API
  never blocks reading a persisted result once the service wakes.
- Neon's free tier auto-suspends after inactivity; the first connection wakes
  it. `/api/v1/health/ready` surfaces database state honestly.

## 3. Verify the public mode surfaces

- `GET /api/v1/capabilities` reports `"mode": "public"` plus the execution
  limits the UI renders.
- `POST /api/v1/comparisons` answers `405` (the route is not registered);
  saved comparison reports stay readable.
- The 33rd replay execution within an hour from one client answers `429`
  with a `Retry-After` header; `/api/v1/replays/latest` keeps working.

## 4. Running the local owner deployment anywhere

The local mode (imports, notes, forks, comparison execution) is the same
image with `FLOORREPLAY_MODE=local`. Point it at any reachable PostgreSQL 17
and keep it private — that mode is for the owner's workbench, not the demo.
