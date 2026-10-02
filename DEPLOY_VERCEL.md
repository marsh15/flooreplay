# Deploy FloorReplay online

Deploy the frontend to Vercel, the API to Render and PostgreSQL to Neon. The repository contains the build configuration for all three. You provide the hosting accounts, repository and secrets. Historical public-hosted checks are retained in `docs/evidence/`. They do not verify the current source or authenticated hosted flows.

You can host the app as a demonstration with AI drafts that require review. Live evidence-only smoke and pilot passed, and hybrid smoke passed. Locked model acceptance stopped at a validation failure; manufacturing-expert claim review remains pending. These limits do not prevent hosting the app, but do not describe its suggestions as validated factory decisions.

## 1. Put the repository on GitHub

Create a private or public GitHub repository and push this checkout. Use the branch containing the deployment configuration as the production branch, or merge it into your default branch. Enable the included verification workflow and wait for it to pass. Confirm the repository remote and deployment branch for your checkout.

The OpenAI key stays in your ignored `backend/.env`. Do not upload that file. Vercel receives no provider key, database URL or account password.

## 2. Create Neon and preserve the current database

Create a Neon PostgreSQL project near your Render service. Confirm pgvector is supported and enable `CREATE EXTENSION IF NOT EXISTS vector`. Obtain both the direct and pooled connection URLs. The API uses a URL beginning `postgresql+psycopg://` with `?sslmode=require`; migration, backup and restore commands use the direct connection.

Transfer the existing database to preserve your reports, real provider receipts, embeddings and the allowance ledger, including ₹7.05 already spent. Follow the backup/restore section in [DEPLOY.md](DEPLOY.md), using the existing local database as the source and a new empty Neon database as the destination. Then run migration and readiness checks. Use a direct `postgresql://` URL for `pg_dump`/`pg_restore`, not the SQLAlchemy URL. Never copy your local `.env` file into the repository.

Do not run the integration tests against Neon: they require a disposable `_test` database. A fresh seed does not transfer the existing spending ledger. Use the restored database to continue this project's ₹500 allowance.

## 3. Deploy the API on Render

In Render, create a Blueprint from your repository using `render.yaml`. It creates one Python API service. Its build installs the locked dependencies; startup applies migrations and seeds without paid provider calls.

Set these API environment variables:

| Variable | Value |
|---|---|
| `FLOORREPLAY_DATABASE_URL` | Neon SQLAlchemy URL with TLS; use pooled for runtime |
| `FLOORREPLAY_OPENAI_API_KEY` | Your OpenAI project key, entered as a secret |
| `FLOORREPLAY_CORS_ORIGINS` | Initially `[]`; replace with your exact Vercel origin in step 4 |
| `FLOORREPLAY_MODE` | `public` (already in the Blueprint) |

Keep the model settings from the Blueprint. Select the deployment branch in Render. Wait until `https://YOUR-API.onrender.com/api/v1/health/ready` returns `{"status":"ready"}`. The readiness check includes the database migration. A free Render service can sleep; its first request may take longer. Choose an always-running service if cold starts are unsuitable.

## 4. Deploy the frontend on Vercel

Import the same GitHub repository into Vercel:

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Framework Preset | Vite |
| Node.js | 22.x (at least 22.12) or 24.x |
| Install Command | `pnpm install --frozen-lockfile` |
| Build Command | `pnpm build` |
| Output Directory | `dist` |
| Production Branch | Branch containing the deployment configuration |
| Environment variable | `VITE_API_BASE=https://YOUR-API.onrender.com/api/v1` |

Set `VITE_API_BASE` in Production for production deployments and in Preview for branch deployments. Production variables are not available to Preview builds. It is a public URL, not a secret. The Vercel build rejects a missing or malformed API URL. `frontend/vercel.json` supplies the build settings, browser-route rewrites and basic response headers. Select the frontend directory, not the repository root.

After Vercel gives you the production URL, set Render's `FLOORREPLAY_CORS_ORIGINS` to `["https://YOUR-PROJECT.vercel.app"]` and redeploy the API. Use only the origin: no trailing slash or `/api/v1`. A custom frontend domain requires adding its exact HTTPS origin as well. The browser sends its in-memory bearer token directly to the API.

For preview deployments, use a separate staging API/database and add the exact preview origin. Do not use wildcard CORS or point untrusted preview branches at the production database/key. Redeploy Vercel after changing `VITE_API_BASE`; it is compiled into the frontend.

### Build fails with a missing API URL

If the build logs contain `Set VITE_API_BASE to the hosted HTTPS API URL ending /api/v1 before deploying.`:

1. Open the frontend project's Settings → Environment Variables in Vercel.
2. Add or edit `VITE_API_BASE` with your Render API URL, such as `https://YOUR-API.onrender.com/api/v1`, with no trailing slash. Use the backend URL, not the frontend's Vercel URL.
3. Enable the environment shown on the failed deployment. A deployment from a non-production branch needs Preview. Check for a branch-specific override if the variable already exists.
4. Save the variable and redeploy. Changes apply to new deployments only.

The Node.js `engines` warning does not cause this missing-variable failure. To reproduce the hosted build locally, run `VERCEL=1 VITE_API_BASE=https://YOUR-API.onrender.com/api/v1 pnpm build` from `frontend`.

## 5. Create your real sign-in accounts

From a trusted terminal, connect the backend CLI to Neon's direct connection through `FLOORREPLAY_DATABASE_URL`. Set the environment explicitly so it overrides your local `.env`, then run:

```sh
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run python -m flooreplay account-create owner --role owner
uv run python -m flooreplay account-create reviewer --role reviewer
uv run python -m flooreplay usage
```

Each account command securely prompts for a password of at least twelve characters. Share reviewer credentials only with the invited reviewer. The existing `evaluation-owner` is a CLI evaluation identity with an unrecorded random password; create your own owner account for browser access. Check that the restored usage ledger still shows the previous spending. No public registration endpoint exists.

If you restored the working database, `openai-live-history-v1` is already indexed. Do not reindex it unnecessarily. Publishing and indexing another corpus are explicit commands documented in [DEPLOY.md](DEPLOY.md).

## 6. Verify the actual URLs

From the repository root:

```sh
python3 scripts/deployment_smoke.py \
  --api https://YOUR-API.onrender.com/api/v1 \
  --frontend https://YOUR-PROJECT.vercel.app \
  --check-cors
```

The checks make no paid calls. They verify database readiness, JSON API responses, anonymous denial of paid endpoints, allowed and denied CORS preflight, and browser deep links.

Then open the deployed app and check: sign in as owner; investigate a seeded incident; inspect citations; submit and review a proposal using the reviewer account; download its report; refresh a deep link; sign out. If you choose to run a paid generation, inspect the usage panel first, use one request identity, and confirm its receipt and ledger entry. Retry by that identity after a network interruption.

The application stores all live data in Neon. Restart Render and confirm reports, reviews, embeddings and spending persist. Take and verify a database backup before using real incident data. Hosted browser checks and restart evidence can only be recorded after you create the hosting services.

## References

[Vercel Vite setup and SPA routing](https://vercel.com/docs/frameworks/frontend/vite), [Render FastAPI deployment](https://render.com/docs/deploy-fastapi), [Render free service behavior](https://render.com/docs/free), [Neon pgvector](https://neon.com/docs/extensions/pgvector).

## Browser and request policies

Vercel and nginx send framing, content-type, referrer, permissions and content-security policies. Vercel's CSP permits HTTPS connections because the API origin is supplied at build time. Before a confidential deployment, restrict `connect-src` to the exact configured API origin. nginx uses same-origin connections through its API proxy. Inline styles are permitted for the component library; scripts must come from the application origin.

The API caps the complete JSON envelope at 16 MiB, including streamed requests; source-text and row limits remain tighter at their import boundary. nginx accepts the same envelope size. Early API errors expose CORS only for the configured exact origins. Check these headers on success, validation errors, oversized requests and server errors during hosted acceptance. HSTS is sent by the API only when its ASGI scheme is HTTPS; confirm trusted proxy/TLS settings. Local HTTP containers rely on the deployment TLS terminator.

Use uv 0.12.19 and pnpm 10.30.0 for the committed dependency policy. CI runs both native audits. Frontend lifecycle scripts are disabled, and Python dependencies install without source builds. Do not enable scripts or source builds as a blanket workaround for an installation failure. Review the failing package and rerun a clean frozen install, build and browser acceptance before release.
