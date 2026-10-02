# FloorReplay frontend

The React and TypeScript frontend provides the incident library, evidence workbench, CSV import flow and evaluation views. Vite builds the app; React Router handles navigation and TanStack Query manages API data. The original operator-coverage workbench remains available under `/coverage`.

## Run locally

Use Node.js 22.12.0 or newer and pnpm 10.30.0. From this directory:

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Start the API separately with `make backend-dev` from the repository root. Follow the [root README](../README.md) to configure PostgreSQL, run migrations and load seed data. Vite normally serves the frontend at `http://localhost:5173` and proxies `/api` to `http://localhost:8000`. Set `BACKEND_PROXY` when the local API uses another address.

Leave `VITE_API_BASE` unset to use the local proxy. For a hosted build, use the public API URL described in [.env.example](.env.example), ending in `/api/v1`. Vercel builds require HTTPS and reject credentials, query strings, fragments and a different path. Never put an OpenAI key, database URL or account password in a `VITE_*` variable. See the [Vercel deployment guide](../DEPLOY_VERCEL.md) for hosting configuration.

## Pages and sessions

| Route | Page |
|---|---|
| `/` | Incident library |
| `/demo` | Synthetic incident demonstration |
| `/incidents/:id` | Incident workbench |
| `/incidents/imports` | Incident CSV imports |
| `/evaluation` | Incident evaluation |
| `/operations` | Operational receipts |
| `/workspaces` | Workspace management |
| `/coverage` | Archived operator-coverage library |
| `/coverage/workbench` | Coverage replay workbench |
| `/coverage/notes` | Coverage notes |
| `/coverage/imports` | Coverage imports |
| `/coverage/comparison` | Coverage comparison |

Owners and invited reviewers sign in through the app shell. The session token stays in browser memory, so reloading the page requires another sign-in. Sign-in, sign-out and session expiry clear the query cache. A `401` response for the current authenticated session expires it and prompts the user to sign in again.

Pages load on demand. Page error boundaries provide recovery when rendering fails, and unmatched routes show a not-found page.

## Build and verify

Run these commands from this directory:

```sh
pnpm lint
pnpm build
pnpm preview
```

`pnpm build` runs the TypeScript build before creating the static site. `pnpm preview` serves that build locally. To refresh generated API types after backend contract changes, run `make generate-api` from the repository root; it exports `backend/openapi.json` and regenerates `src/lib/generated-api.ts`.

Playwright tests need a running API with seed data. From the repository root, run `make e2e-install` to install Chromium, then `make e2e`. The test configuration starts or reuses a Vite server. `E2E_BASE_URL` selects a different frontend address.

The [product guide](../PRODUCT.md) explains the incident workflow. [DEVELOPMENT.md](../DEVELOPMENT.md) records the design and verification history of the original coverage workbench.
