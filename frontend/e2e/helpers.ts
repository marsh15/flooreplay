/**
 * Shared E2E helpers. The frontend is started by the Playwright webServer;
 * the backend must already be running on :8000 with the seed loaded.
 */
export async function ensureBackend(): Promise<void> {
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      const response = await fetch(`${(process.env.E2E_API_BASE ?? 'http://localhost:8000').replace(/\/api\/v1\/?$/, '')}/api/v1/health/ready`)
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

export async function signInOwner(page: import('@playwright/test').Page): Promise<void> {
  const username = process.env.E2E_USERNAME
  const password = process.env.E2E_PASSWORD
  if (!username || !password) throw new Error('Set E2E_USERNAME and E2E_PASSWORD for an owner in the isolated browser-test database.')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
}
