import { defineConfig } from '@playwright/test'

// E2E tests drive the real app: Vite dev server on :5173 (started here if
// not already running) and the FastAPI backend on :8000 (must already be
// running with the seed loaded — `make backend-dev` + `make seed`).
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
