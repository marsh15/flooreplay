import { expect, test } from '@playwright/test'

import { ensureBackend } from './helpers'

test.beforeAll(ensureBackend)

test('library lists the hero scenarios and the synthetic-data disclaimer', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: /FloorReplay/ }).first()).toBeVisible()
  await expect(page.getByText('SCEN-HERO@1').first()).toBeVisible()
  await expect(
    page.getByText(/unofficial engineering exploration using synthetic data/i),
  ).toBeVisible()
})

test('library surfaces persisted latest-attempt summaries', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText(/Kaveri Garments Unit 3/).first()).toBeVisible()
})
