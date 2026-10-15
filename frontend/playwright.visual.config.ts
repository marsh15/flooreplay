import { defineConfig } from '@playwright/test'

// Backend-free visual + accessibility capture. API calls are aborted so the
// app renders its saved demo data. Run with `pnpm visual`; set VISUAL_DIR to
// choose where screenshots and the axe summary are written.
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const port = new URL(baseURL).port || '5173'
export default defineConfig({
  testDir: './e2e-visual',
  timeout: 60_000,
  workers: 1,
  reporter: 'list',
  use: { baseURL },
  webServer: {
    command: `pnpm dev --port ${port}`,
    url: baseURL,
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
