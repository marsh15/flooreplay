# Deployment and operations

The recommended deployment is the Vercel frontend, a Render API, and Neon PostgreSQL with pgvector. Start with [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md). Historical public-hosted checks are recorded in the release evidence; acceptance of the current release remains pending. Configure the server OpenAI key and hosting URLs before verifying its hosted behavior. Local Docker image builds and Compose configuration were verified before the final review fixes. Complete container startup remains blocked by a local Docker containerd metadata input/output error. The native application workflow is verified separately.

## Run the local stack

From the repository root:

```sh
docker compose up --build --wait
```

Open `http://localhost:5174`. The API is at `http://localhost:8001/api/v1`, and PostgreSQL is exposed only on loopback port 5434. These ports avoid the existing development servers. `FLOORREPLAY_DB_PORT`, `FLOORREPLAY_API_PORT`, and `FLOORREPLAY_FRONTEND_PORT` override them. Compose migrates and seeds before serving traffic. Migration, seeding and startup make no generation or embedding requests.

Create individual accounts with the prompted password:

```sh
docker compose exec api python -m flooreplay account-create owner --role owner
docker compose exec api python -m flooreplay account-create reviewer --role reviewer
```

Optional generation uses `FLOORREPLAY_OPENAI_API_KEY` from the host environment when starting Compose. The key belongs only to the API container. Use a dedicated OpenAI project, and retain the shared ₹500 allowance. Changing the key requires recreating the API container; historical reports and allowance records stay in PostgreSQL.

```sh
python3 scripts/deployment_smoke.py --api http://localhost:8001/api/v1 --frontend http://localhost:5174
docker compose stop
docker compose start
```

`stop` retains the database volume. Avoid `down --volumes` on a database containing work you need.

## Isolated verification database

The disposable test profile is separate from the application database:

```sh
docker compose --profile test up test-db --wait
export FLOORREPLAY_TEST_DATABASE_URL=postgresql+psycopg://flooreplay_test@localhost:5435/flooreplay_release_test
export FLOORREPLAY_DATABASE_URL="$FLOORREPLAY_TEST_DATABASE_URL"
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run python -m flooreplay seed
uv run python -m flooreplay seed
uv run pytest
uv run python -m flooreplay dataset-verify
```

The integration harness refuses database names that do not end in `_test`. It defaults to the independently provisioned development test database on port 5433; set the override above when using Compose. The test profile uses trust authentication on a loopback-only disposable service and stores no application credentials.

For browser tests, create an owner in this test database, start the API on port 8000, and run Playwright with `E2E_USERNAME` and `E2E_PASSWORD` set. The browser session token stays in memory. Playwright starts Vite on port 5173. Use the fresh test account, not an owner account from the working database.

The GitHub Actions workflow repeats lint/type/build checks, fresh migration, seed twice, backend integration tests, dataset validation, generated API/report consistency, frontend dependency audit, and browser tests. It supplies no OpenAI key and makes no paid calls. Branch-protection enforcement must be configured in the hosting repository; no remote is currently configured for this checkout.

## Render and Neon setup

1. Create the Neon database and verify that `CREATE EXTENSION IF NOT EXISTS vector` succeeds. Use the direct database connection for migration/owner commands; the API may use a transaction-pooled connection. The application uses transaction-level advisory locks, never a session lock that must survive pooling.
2. Connect the repository to a Render Blueprint using `render.yaml` to create the API. Import the same repository into Vercel with Root Directory `frontend` for the static frontend.
3. Set API `FLOORREPLAY_DATABASE_URL` to the SQLAlchemy URL, beginning `postgresql+psycopg://` with TLS required. Set `FLOORREPLAY_OPENAI_API_KEY` as a secret. Set `FLOORREPLAY_CORS_ORIGINS` to a JSON array containing the exact HTTPS frontend origin, such as `["https://YOUR-PROJECT.vercel.app"]`.
4. In Vercel, set frontend `VITE_API_BASE` to the public HTTPS API base ending `/api/v1`. Never put the provider key in a `VITE_*` variable. Redeploy the Vercel frontend after changing its API base.
5. Deploy the API; its start command migrates and seeds with frozen runtime dependencies. It records `RENDER_GIT_COMMIT` as the build identity. The readiness endpoint checks the expected migration revision before accepting traffic.
6. From a trusted terminal with the production backend database environment, run `uv run python -m flooreplay account-create owner --role owner`, then create invited reviewers. The free service need not provide an interactive shell: the CLI can connect directly to Neon from a trusted workstation.
7. Publish the corpus explicitly: `uv run python -m flooreplay corpus-publish release-v1 --cutoff 2026-09-30T00:00:00+00:00 --owner owner`. Indexing is a separate paid command: `uv run python -m flooreplay corpus-index release-v1 --owner owner`. Confirm allowance with `uv run python -m flooreplay usage` first.

Render's free web service can sleep after inactivity and has ephemeral local storage. Database reports, accounts, sessions, AI runs, embeddings, and allowance are therefore stored in PostgreSQL. Describe the first request after sleeping as a cold start; do not claim warm latency for it. See [Render free service behavior](https://render.com/docs/free). The frontend's `vercel.json` rewrites browser routes to `/index.html` for refresh and deep links.

## Hosted acceptance evidence

Run the read-only checks using actual deployment URLs:

```sh
python3 scripts/deployment_smoke.py --api https://YOUR-API.onrender.com/api/v1 --frontend https://YOUR-PROJECT.vercel.app
```

These checks prove database readiness, anonymous reads, anonymous denial of paid endpoints, and SPA deep-link delivery. They do not claim real OpenAI evaluation. Complete authenticated sign-in, a budgeted generation and query embedding, citation inspection, proposal submit/review, new-evidence stale rejection, export, restart persistence, exact-origin CORS, and API-outage saved-report behavior in the browser. Record attempts, failures, provider request IDs, usage, and warm/cold timings. The staged paid evaluation must stop on a blocking defect and stay within its allocation.

## Backup, restore, and rollback

Use Neon's direct connection for `pg_dump`. Set `FLOORREPLAY_BACKUP_DATABASE_URL` to its libpq `postgresql://` URL rather than the application's `postgresql+psycopg://` URL. Credentials should come from protected environment configuration or a local password file.

```sh
umask 077
pg_dump --format=custom --no-owner --no-acl --dbname "$FLOORREPLAY_BACKUP_DATABASE_URL" --file flooreplay-backup.dump
```

Backups contain account hashes and investigation data. Store them securely. Restore into a new empty database and verify it before changing the API connection:

```sh
pg_restore --no-owner --no-acl --exit-on-error --dbname "$FLOORREPLAY_RESTORE_DATABASE_URL" flooreplay-backup.dump
```

Ensure pgvector is available in the destination. Verify migration revision, report counts, AI-run identities, corpus digests, and the allowance ledger. Never drop uncertain spend reservations during restore: a provider call may already have been billed.

For an application rollback, redeploy the previous reviewed commit and restore its frontend build; retain the durable database. Check schema compatibility first. Prefer a forward repair migration; running a downgrade against the working database can remove new report/account/spending data. When compatibility requires restoring a backup, restore into another database, validate, and then change the connection. Reconcile provider usage that occurred after the backup before enabling paid operations.

## Provider and allowance runbook

For missing configuration or model access, inspect the capabilities reason and configure the server key/model on the API. A key change never changes the provider recorded on a previous report. For authentication failures, disable compromised accounts with `account-disable` and revoke their sessions.

For rate limiting, execution capacity, refusals, and incomplete responses, retain the durable request result and its attempt count. Recover by request identity after a browser interruption. Do not send a new request just because the browser lost its connection. A timeout or interrupted run may have incurred a charge; uncertain reservations remain committed until reviewed against provider usage.

For exhausted allowance, inspect `usage`, reconcile recorded charges and currency conversion, and move unused category allowance using the owner allowance command if appropriate. Do not raise the ₹500 total ceiling to unblock an ordinary workflow. Lexical search, saved reports, and bounded deterministic analysis remain available without provider spending.

For an API outage, the frontend labels bundled demonstration reports as saved. Restore database connectivity and readiness before accepting traffic. After a restart, inspect durable runs and reservations; the application must not silently rerun an uncertain paid request. Verify backups periodically on a fresh disposable database.
