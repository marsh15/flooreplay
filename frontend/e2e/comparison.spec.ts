import { expect, test } from '@playwright/test'

import { ensureBackend, signInOwner } from './helpers'

test.beforeAll(ensureBackend)

test('the 32-case suite runs under two configurations and reports totals', async ({ page }) => {
  await page.goto('/coverage/comparison')
  await signInOwner(page)

  await expect(page.getByText(/pinned suite \(32 cases\)/)).toBeVisible()

  await page.getByRole('button', { name: 'Run comparison' }).click()
  await expect(page.getByText(/Suite SUITE-OPS-V1@/)).toBeVisible({ timeout: 45_000 })
  // baseline vs improved: every case passes under its own documented demands,
  // with no fixes and no regressions
  await expect(page.getByRole('group', { name: 'Unchanged pass', exact: true }).getByText('32', { exact: true })).toBeVisible()
  for (const label of ['Fixed', 'Regression', 'Unchanged fail']) {
    await expect(page.getByRole('group', { name: label, exact: true }).getByText('0', { exact: true })).toBeVisible()
  }
})

test('saved comparison history is listed', async ({ page }) => {
  await page.goto('/coverage/comparison')
  await signInOwner(page)
  await expect(page.getByText(/baseline/i).first()).toBeVisible()
})
