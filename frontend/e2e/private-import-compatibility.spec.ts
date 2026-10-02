import { expect, test } from '@playwright/test'

test('private import stops when an older backend has no workspace service', async ({ page }) => {
  const writes: string[] = []
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/login')) return route.fulfill({ json: { token: 'synthetic-login', user: { id: 'owner', username: 'owner', display_name: 'Owner', role: 'owner' } } })
    if (path.endsWith('/capabilities')) return route.fulfill({ json: { mode: 'local', imports_enabled: true, reviews_enabled: true } })
    if (path.endsWith('/incidents')) return route.fulfill({ json: { items: [] } })
    if (route.request().method() !== 'GET') writes.push(path)
    return route.fulfill({ status: 404, json: { message: 'Legacy endpoint unavailable' } })
  })
  await page.goto('/incidents/imports')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill('synthetic-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText(/Private workspace service is unavailable/)).toBeVisible()
  await expect(page.getByLabel('Local file')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Preview source', exact: true })).toHaveCount(0)
  expect(writes).toEqual([])
})
