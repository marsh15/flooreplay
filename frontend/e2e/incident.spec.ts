import { expect, test } from '@playwright/test'

import { ensureBackend } from './helpers'

test.beforeAll(ensureBackend)

test('incident investigation keeps evidence and later revision separate', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Incident library' })).toBeVisible()
  await page.getByRole('link', { name: 'Delayed start on sewing line S4' }).click()
  await expect(page.getByRole('heading', { name: 'Observed situation' })).toBeVisible()
  await expect(page.getByText('74', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Saved local-model result' })).toBeVisible()
  await expect(page.getByText(/Project-author review supported 1 of 4 factual claims/)).toBeVisible()
  await page.getByRole('combobox', { name: 'Evidence revision' }).selectOption('1')
  await expect(page.getByText('73', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/This proposal belongs to revision 1/).first()).toBeVisible()
  await page.getByRole('button', { name: 'EV-MAT-1' }).first().click()
  await expect(page.getByRole('heading', { name: 'Source evidence' })).toBeVisible()
  await expect(page.getByText('material-transfer-218', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: 'Historical precedents' })).toBeVisible()
  await expect(page.getByText('Late fabric transfer on line S2')).toBeVisible()
  await page.getByRole('combobox', { name: 'Evidence revision' }).selectOption('2')
  await expect(page.getByText('EV-MAINT-1').first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'Export portable report' })).toBeVisible()
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
  await expect(page.getByRole('heading', { name: 'Import incident evidence' })).toBeVisible()
  await page.getByLabel('Incident', { exact: true }).selectOption('INC-001')
  await page.getByLabel('Local file').setInputFiles({
    name: 'invalid.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify([{ id: 'test-event', record_type: 'line_block', available_at: '2026-09-28T11:40:00+05:30', line_id: 'S4' }])),
  })
  await page.getByRole('button', { name: 'Preview source' }).click()
  await expect(page.getByRole('heading', { name: 'Preview: BLOCKED' })).toBeVisible()
  await expect(page.getByText(/summary or text must contain/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Publish new revision' })).toBeDisabled()
})

test('bundled investigation remains readable while the API is unavailable', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => route.abort())
  await page.goto('/')
  await expect(page.getByText(/Showing one bundled saved deterministic investigation/)).toBeVisible()
  await page.getByRole('link', { name: 'Delayed start on sewing line S4' }).click()
  await expect(page.getByText('Saved deterministic result')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Saved local-model result' })).toBeVisible()
  await expect(page.getByText('74', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit for review' })).toHaveCount(0)
  await page.getByRole('button', { name: 'EV-MAT-1' }).first().click()
  await expect(page.getByText('material-transfer-218', { exact: true })).toBeVisible()
  await page.goto('/evaluation')
  await expect(page.getByText('API unavailable. Showing the bundled saved evaluation report.')).toBeVisible()
  await expect(page.getByText('8 / 16').first()).toBeVisible()
})
