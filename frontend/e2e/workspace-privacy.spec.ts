import { expect, test } from '@playwright/test'
import savedReport from '../src/data/hero-report.json' with { type: 'json' }
import savedRevision from '../src/data/hero-revision.json' with { type: 'json' }

// Browser transport fixture exercises account switching; backend tests enforce the same boundary against real storage.
test('a private deep link clears cached records on sign-out and stays unavailable to another account', async ({ page }) => {
  const requests: { path: string; authorization: string }[] = []
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const authorization = route.request().headers().authorization ?? ''
    requests.push({ path, authorization })
    if (path === '/auth/login') {
      const username = route.request().postDataJSON().username
      return route.fulfill({ json: { token: username, user: { id: username, username, display_name: username, role: 'owner' } } })
    }
    if (path === '/auth/logout') return route.fulfill({ json: { ok: true } })
    if (path === '/capabilities') return route.fulfill({ json: {} })
    if (authorization !== 'Bearer alice') return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: 'Record unavailable.' } })
    if (path === '/incidents/private-case') return route.fulfill({ json: { id: 'private-case', title: 'Confidential factory incident', workspace_id: 'private-alice', revision: 2, cutoff: savedReport.cutoff } })
    if (path === '/incidents/private-case/revisions/2') return route.fulfill({ json: { ...savedRevision, id: 'private-case', title: 'Confidential factory incident', workspace_id: 'private-alice' } })
    if (path === '/incidents/private-case/analyses' || path === '/analyses/private-analysis') return route.fulfill({ json: { ...savedReport, id: 'private-analysis', incident_id: 'private-case', workspace_id: 'private-alice' } })
    return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: 'Record unavailable.' } })
  })
  async function login(username: string) {
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password').fill('local-fixture-only')
    await page.getByRole('button', { name: 'Continue', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible()
  }
  await page.goto('/incidents/private-case?revision=2')
  await expect(page.getByRole('alert').filter({ hasText: 'Could not load incident' })).toBeVisible()
  await login('alice')
  await expect(page.getByRole('heading', { name: 'Confidential factory incident' })).toBeVisible()
  await expect(page.getByText('Private workspace records', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Confidential factory incident' })).toHaveCount(0)
  await expect(page.getByRole('alert').filter({ hasText: 'Could not load incident' })).toBeVisible()
  await login('bob')
  await expect(page.getByRole('heading', { name: 'Confidential factory incident' })).toHaveCount(0)
  await expect(page.getByRole('alert').filter({ hasText: 'Could not load incident' })).toBeVisible()
  await expect.poll(() => requests.some((entry) => entry.path === '/incidents/private-case/revisions/2' && entry.authorization === 'Bearer bob')).toBe(true)
})
