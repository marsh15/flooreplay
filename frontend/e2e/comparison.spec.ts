import { expect, test } from '@playwright/test'

import { ensureBackend } from './helpers'

test.beforeAll(ensureBackend)

test('the 32-case suite runs under two configurations and reports totals', async ({ page }) => {
  await page.goto('/comparison')

  await expect(page.getByText(/pinned suite \(32 cases\)/)).toBeVisible()

  await page.getByRole('button', { name: 'Run comparison' }).click()
  await expect(page.getByText(/Suite SUITE-OPS-V1@/)).toBeVisible({ timeout: 45_000 })
  // baseline vs improved: every case passes under its own documented demands,
  // with no fixes and no regressions
  const tiles = page.locator('p.text-2xl')
  await expect(tiles.nth(0)).toHaveText('32') // unchanged pass
  await expect(tiles.nth(1)).toHaveText('0') // fixed
  await expect(tiles.nth(2)).toHaveText('0') // regression
  await expect(tiles.nth(3)).toHaveText('0') // unchanged fail
})

test('saved comparison history is listed', async ({ page }) => {
  await page.goto('/comparison')
  await expect(page.getByText(/baseline/i).first()).toBeVisible()
})
