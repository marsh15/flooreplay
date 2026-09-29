import { expect, test } from '@playwright/test'

import { ensureBackend } from './helpers'

test.beforeAll(ensureBackend)

test('a floor note becomes a draft, then a confirmed fork — never an automatic event', async ({
  page,
}) => {
  await page.goto('/coverage/notes')

  await page
    .locator('textarea')
    .fill('O117 will not be in today. Sleeve attach on Line 4 needs cover.')
  await page.getByRole('button', { name: 'Extract draft' }).click()

  // the offline rule baseline parses honestly; the mention resolves
  await expect(page.getByText(/draft by rule-baseline/)).toBeVisible()
  await expect(page.getByText('OPERATOR_UNAVAILABLE')).toBeVisible()
  await expect(page.getByText('O117').first()).toBeVisible()

  await page.getByRole('button', { name: 'Confirm event and fork revision' }).click()
  await expect(page.getByText(/Confirmed\. New revision/)).toBeVisible()
})

test('manual entry works without any parser output', async ({ page }) => {
  await page.goto('/coverage/notes')
  await page.getByRole('button', { name: 'Skip parsing: manual entry' }).click()
  await expect(page.getByText('Confirm structured event')).toBeVisible()
})
