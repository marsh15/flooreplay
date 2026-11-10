import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { ensureBackend, signInOwner } from './helpers'

/**
 * The one live order-decisions spec: no mocks, the real API and the seeded synthetic demo.
 * Needs `make seed` (the public demo). The private half needs an owner who has run
 * `python -m flooreplay decisions-demo --owner <E2E_USERNAME>` and it adopts a policy, which
 * can happen once per workspace, so it runs only when E2E_PRIVATE_SANDBOX=1 (CI sets it on a
 * fresh database). Locally, load the sandbox for a new owner before each such run. One sign-in
 * only: the login limit is 10 per 15 minutes.
 */
test.beforeAll(ensureBackend)

test('an anonymous visitor walks the public demo', async ({ page }) => {
  // --- the public demo, signed out -----------------------------------------------------------
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Order decisions' })).toBeVisible()
  await expect(page.getByText('Showing the public synthetic demo.')).toBeVisible()
  for (const order of ['POLO-221', 'POLO-222', 'POLO-223', 'POLO-224', 'POLO-225'])
    await expect(page.getByRole('link', { name: order, exact: true })).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])

  await page.getByRole('link', { name: 'POLO-221', exact: true }).click()
  await expect(page.getByRole('heading', { name: /POLO-221/ })).toBeVisible()
  await expect(page.getByText('READY', { exact: true }).first()).toBeVisible()
  await expect(page.locator('#recommendation').getByText('ACCEPT', { exact: true })).toBeVisible()
  await expect(page.getByText(/This replay is unsettled/)).toHaveCount(0)
  await expect(page.getByText(/signed-in account and a private workspace/)).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])

  // Scrub back in time: before the dyeing note it is READY, with the note it is CONFLICTING.
  await page.getByRole('link', { name: 'Knowledge timeline' }).click()
  const scrubber = page.getByRole('slider', { name: 'Knowledge-time cutoff' })
  await scrubber.focus()
  await scrubber.press('Home')
  await expect(page.getByText('Gate: READY')).toBeVisible()
  await scrubber.press('ArrowRight')
  await expect(page.getByText('Gate: CONFLICTING')).toBeVisible()
  await scrubber.press('End')
  await expect(page.getByText('Gate: READY')).toBeVisible()
  await expect(page.getByText(/dyeing|fabric qc/i).first()).toBeVisible()

  // The lab shows the stored regression run: one FIXED and one REGRESSION.
  await page.getByRole('link', { name: 'Replay lab' }).click()
  await expect(page.getByText('Latest stored regression run loaded.')).toBeVisible()
  await expect(page.getByText('FIXED', { exact: true })).toBeVisible()
  await expect(page.getByText('REGRESSION', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Adopt policy' })).toBeDisabled()
})

test('a signed-in owner records a decision and adopts a policy in a private workspace', async ({
  page,
}) => {
  test.skip(
    !process.env.E2E_PRIVATE_SANDBOX,
    'Set E2E_PRIVATE_SANDBOX=1 with a freshly loaded sandbox',
  )
  await page.goto('/')
  await signInOwner(page)
  // The first option is the public demo; the owner's personal workspace follows it.
  await page.getByLabel('Workspace').selectOption({ index: 1 })
  await page.getByRole('link', { name: 'Order decisions' }).first().click()
  await page.getByRole('link', { name: 'POLO-221', exact: true }).click()
  await page.getByLabel('Reason for this decision').fill('QA resolved the stock conflict.')
  await page.getByRole('button', { name: 'Record final decision' }).click()
  await expect(page.getByRole('heading', { name: 'Recorded decisions' })).toBeVisible()
  await expect(page.getByText('QA resolved the stock conflict.', { exact: true })).toBeVisible()

  await page.getByRole('link', { name: 'Replay lab' }).click()
  await expect(page.getByText('Latest stored regression run loaded.')).toBeVisible()
  await page
    .getByLabel(/Acknowledgement for Capacity is short but overtime covers it/)
    .fill('A one hour overtime cap is acceptable for this factory.')
  await page.getByRole('button', { name: 'Adopt policy' }).click()
  await expect(page.getByText('Policy adopted')).toBeVisible()
})
