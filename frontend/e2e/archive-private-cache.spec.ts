import { expect, test } from '@playwright/test'

test('signing out removes private archive rows even when the archive page has no auth hook', async ({ page }) => {
  const privateCase = { scenario_id: 'PRIVATE-ARCHIVE', revision: 1, title: 'Confidential archive test scenario', tags: [], defect_statement: 'Synthetic private episode', decision_at: '2026-09-28T09:00:00+05:30' }
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const owner = route.request().headers().authorization === 'Bearer synthetic-owner'
    if (path.endsWith('/auth/login')) return route.fulfill({ json: { token: 'synthetic-owner', user: { id: 'owner', username: 'owner', display_name: 'Owner', role: 'owner' } } })
    if (path.endsWith('/auth/logout')) return route.fulfill({ json: { logged_out: true } })
    if (path.endsWith('/capabilities')) return route.fulfill({ json: { mode: 'local', imports_enabled: owner } })
    if (path.endsWith('/incidents')) return route.fulfill({ json: { items: [] } })
    if (path.endsWith('/scenarios')) return route.fulfill({ json: { items: owner ? [privateCase] : [], latest_attempts: [] } })
    return route.fulfill({ status: 503, json: { message: 'Unavailable' } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill('synthetic-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('link', { name: 'Coverage archive', exact: true }).click()
  await expect(page.getByRole('link', { name: privateCase.title })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('link', { name: privateCase.title })).toHaveCount(0)
  await expect(page.getByText('No scenarios are seeded yet')).toBeVisible()
})
