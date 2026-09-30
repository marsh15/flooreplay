import { expect, test } from '@playwright/test'
import { ensureBackend } from './helpers'

test.beforeAll(ensureBackend)

test('live comparison explains corrected and newly available evidence without changing the earlier report', async ({ page }) => {
  await page.goto('/incidents/INC-001?revision=2')
  await expect(page.getByRole('heading', { name: 'Observed situation' })).toBeVisible()
  await page.getByRole('button', { name: 'Compare revisions', exact: true }).click()
  const comparison = page.getByRole('region', { name: 'Revision comparison' })
  await expect(comparison.getByRole('heading', { name: 'What changed in revision 2?' })).toBeVisible()
  await expect(comparison.getByText('added: EV-MAINT-1', { exact: true })).toBeVisible()
  await expect(comparison.getByText('added: EV-MACH-CORR', { exact: true })).toBeVisible()
  await expect(comparison.getByText(/corrects EV-MACH-1/)).toBeVisible()
  const shortfall = comparison.getByRole('row', { name: 'shortfall 73 74', exact: true })
  await expect(shortfall).toBeVisible()
  await expect(comparison.getByText(/Earlier approvals remain attached/)).toBeVisible()
  await page.getByRole('combobox', { name: 'Evidence revision', exact: true }).selectOption('1')
  await expect(page.getByRole('button', { name: 'Compare revisions', exact: true })).toHaveCount(0)
  await expect(page.getByText('73', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'EV-MAINT-1', exact: true })).toHaveCount(0)
})

test('print report keeps facts and source identifiers while hiding navigation and controls', async ({ page }) => {
  await page.goto('/incidents/INC-001?revision=2')
  await expect(page.getByRole('heading', { name: 'Observed situation' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Print investigation report', exact: true })).toBeVisible()
  await page.emulateMedia({ media: 'print' })
  await expect(page.getByRole('button', { name: 'Print investigation report', exact: true })).toBeHidden()
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeHidden()
  await expect(page.getByText(/FloorReplay · Evidence revision 2 · Report/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'OpenAI draft', exact: true })).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Observed situation' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'EV-MAT-1', exact: true }).first()).toBeVisible()
})
