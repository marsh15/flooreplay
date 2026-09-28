/**
 * Shared E2E helpers. The frontend is started by the Playwright webServer;
 * the backend must already be running on :8000 with the seed loaded.
 */
export async function ensureBackend(): Promise<void> {
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      const response = await fetch('http://localhost:8000/api/v1/health/ready')
      if (response.ok) return
    } catch {
      // not up yet; retry
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(
    'Backend on http://localhost:8000 is not ready. Start it with `make backend-dev` and load fixtures with `make seed` before running E2E.',
  )
}
