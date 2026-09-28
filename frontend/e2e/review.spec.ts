import { expect, test } from '@playwright/test'

import { ensureBackend } from './helpers'

test.beforeAll(ensureBackend)

test('later-context review: refreshed evidence makes the 07:58 recommendation stale', async ({
  page,
}) => {
  await page.goto('/workbench?scenario=SCEN-REVIEW-LATER&revision=1')

  await page.getByRole('button', { name: 'Run replay' }).click()
  await expect(page.getByText('Ready for review')).toBeVisible()

  await page
    .getByRole('combobox', { name: 'Later scenario revision' })
    .selectOption('SCEN-REVIEW-LATER@2')
  await page.getByRole('button', { name: 'Run review check' }).click()
  await expect(page.getByText('stale recommendation')).toBeVisible()
  await expect(page.getByText(/DECISION_TIME_CHANGED/)).toBeVisible()
})

test('later-context review: an identical context is still supported', async ({ page }) => {
  await page.goto('/workbench?scenario=SCEN-REVIEW-LATER&revision=1')

  await page.getByRole('button', { name: 'Run replay' }).click()
  await expect(page.getByText('Ready for review')).toBeVisible()

  await page.getByRole('combobox', { name: 'Later scenario revision' }).selectOption('SCEN-HERO@2')
  await page.getByRole('button', { name: 'Run review check' }).click()
  await expect(page.getByText('still supported')).toBeVisible()
})
