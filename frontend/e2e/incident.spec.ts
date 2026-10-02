import { expect, test } from '@playwright/test'

import { ensureBackend, signInOwner } from './helpers'

test.beforeAll(ensureBackend)

test('incident investigation keeps evidence and later revision separate', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Incident library' })).toBeVisible()
  await page.getByRole('link', { name: 'Delayed start on sewing line S4' }).click()
  await expect(page.getByRole('heading', { name: 'Observed situation' })).toBeVisible()
  await expect(page.getByText('74', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Historical local-model result' })).toBeVisible()
  await expect(page.getByText(/Project-author review supported 1 of 4 factual claims/)).toBeVisible()
  await page.getByRole('combobox', { name: 'Evidence revision' }).selectOption('1')
  await expect(page.getByText('73', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/This proposal belongs to revision 1/).first()).toBeVisible()
  await page.getByRole('button', { name: 'EV-MAT-1' }).first().click()
  await expect(page.getByRole('heading', { name: 'Source evidence' })).toBeVisible()
  await expect(page.getByText('material-transfer-218', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: 'Historical precedents' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open precedent' }).first()).toBeVisible()
  await expect(page.getByText(/Proposal prerequisites require separate current-source verification/).first()).toBeVisible()
  await page.getByRole('combobox', { name: 'Evidence revision' }).selectOption('2')
  await expect(page.getByRole('button', { name: 'EV-MAINT-1', exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Export portable report' })).toBeDisabled()
})

test('evaluation shows measured denominators and failed local-model cases', async ({ page }) => {
  await page.goto('/evaluation')
  await expect(page.getByRole('heading', { name: 'Incident evaluation lab' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Numeric Correctness' })).toBeVisible()
  await expect(page.getByText('10 / 10').first()).toBeVisible()
  await expect(page.getByText('8 / 16').first()).toBeVisible()
  await expect(page.getByText('4 / 10').first()).toBeVisible()
  await expect(page.getByText('6 reported failures')).toBeVisible()
  await expect(page.getByText(/Ten cases and three retrieval queries/)).toBeVisible()
})

test('incident import preview blocks an invalid source row', async ({ page }) => {
  await page.goto('/incidents/imports')
  await signInOwner(page)
  await expect(page.getByRole('heading', { name: 'Import incident evidence' })).toBeVisible()
  await page.getByLabel('Import into').selectOption('new')
  await page.getByLabel('New incident ID').fill(`INVALID-${Date.now()}`)
  await page.getByLabel('Incident title').fill('Invalid private import preview')
  await page.getByLabel('Factory', { exact: true }).fill('Synthetic test factory')
  await page.getByLabel('Sewing line', { exact: true }).fill('S4')
  await page.getByLabel('Order ID', { exact: true }).fill('ORD-TEST')
  await page.getByLabel('Style ID', { exact: true }).fill('STYLE-TEST')
  await page.getByLabel('Window start', { exact: true }).fill('2026-09-28T09:00:00+05:30')
  await page.getByLabel('Window end', { exact: true }).fill('2026-09-28T12:00:00+05:30')
  await page.getByLabel('Knowledge cutoff', { exact: true }).fill('2026-09-28T12:00:00+05:30')
  await page.getByLabel('Local file').setInputFiles({
    name: 'invalid.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify([{ id: 'test-plan', record_type: 'baseline_plan', available_at: '2026-09-28T11:40:00+05:30', line_id: 'S4' }])),
  })
  await page.getByRole('button', { name: 'Preview source' }).click()
  await expect(page.getByRole('heading', { name: 'Preview: BLOCKED' })).toBeVisible()
  await expect(page.getByText('Production records require factory, order_id, style_id, and stage', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create incident', exact: true })).toBeDisabled()
})

test('bundled investigation remains readable while the API is unavailable', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => route.abort())
  await page.goto('/')
  await expect(page.getByText(/Showing bundled saved demo cases/)).toBeVisible()
  await page.getByRole('link', { name: 'Delayed start on sewing line S4' }).click()
  await expect(page.getByText('Saved deterministic result')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Historical local-model result' })).toBeVisible()
  await expect(page.getByText('74', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit for review' })).toHaveCount(0)
  await page.getByRole('button', { name: 'EV-MAT-1' }).first().click()
  await expect(page.getByText('material-transfer-218', { exact: true })).toBeVisible()
  await page.goto('/evaluation')
  await expect(page.getByText('API unavailable. Showing the bundled saved evaluation report.')).toBeVisible()
  await expect(page.getByText('8 / 16').first()).toBeVisible()
})
