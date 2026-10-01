import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { ensureBackend, signInOwner } from './helpers'

const apiBase = (process.env.E2E_API_BASE ?? 'http://localhost:8000').replace(/\/api\/v1\/?$/, '')
const stamp = (minute: number) => `2026-09-28T09:${String(minute).padStart(2, '0')}:00+05:30`
const headers = 'External_ID,Type,Available,Interval_Start,Interval_End,Good_Count,Units,Corrects'
const exportCsv = (id: string, type: string, available: string, quantity: number, corrects = '') => `\uFEFF${headers}\r\n${id},${type},${available},${stamp(0)},${stamp(15)},${quantity},good_units,${corrects}\r\n`

async function inspectAndMap(page: Page, raw: string, filename: string, correction = false) {
  await page.getByLabel('Local file').setInputFiles({ name: filename, mimeType: 'text/csv', buffer: Buffer.from(raw) })
  await page.getByRole('button', { name: 'Inspect CSV columns', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Match CSV columns' })).toBeVisible()
  await page.getByText(/^Optional fields and record relationships/).click()
  const columns = { id: 'External_ID', record_type: 'Type', available_at: 'Available', start: 'Interval_Start', end: 'Interval_End', quantity: 'Good_Count', unit: 'Units' }
  for (const [name, header] of Object.entries(columns)) await page.getByRole('combobox', { name: new RegExp(`^Map ${name}(?: |$)`) }).selectOption({ label: header })
  await page.getByRole('button', { name: 'Use destination scope for unmapped fields' }).click()
  await page.getByRole('combobox', { name: /^Map count_mode/ }).selectOption('constant')
  await page.getByLabel('Constant for count_mode', { exact: true }).fill('delta')
  if (correction) await page.getByRole('combobox', { name: /^Map supersedes_id/ }).selectOption({ label: 'Corrects' })
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Preview: READY' })).toBeVisible()
}

test.beforeAll(ensureBackend)

test('unfamiliar CSV creates baseline, mapped output and explicit correction while preserving the earlier report', async ({ page }) => {
  test.setTimeout(120_000)
  const suffix = Date.now()
  const incidentId = `CSV-MAP-${suffix}`
  const planId = `csv-plan-${suffix}`
  const outputId = `csv-output-${suffix}`
  const correctionId = `csv-correction-${suffix}`
  await page.goto('/incidents/imports')
  await signInOwner(page)
  await page.getByLabel('Import into').selectOption('new')
  await page.getByLabel('New incident ID').fill(incidentId)
  await page.getByLabel('Incident title').fill('Mapped spreadsheet investigation')
  await page.getByLabel('Factory', { exact: true }).fill('Synthetic mapping factory')
  await page.getByLabel('Sewing line', { exact: true }).fill(`S-${suffix}`)
  await page.getByLabel('Order ID', { exact: true }).fill(`ORD-${suffix}`)
  await page.getByLabel('Style ID', { exact: true }).fill('STYLE-MAP')
  await page.getByLabel('Window start', { exact: true }).fill(stamp(0))
  await page.getByLabel('Window end', { exact: true }).fill(stamp(15))
  await page.getByLabel('Knowledge cutoff', { exact: true }).fill(stamp(15))
  await inspectAndMap(page, exportCsv(planId, 'baseline_plan', '2026-09-28T08:45:00+05:30', 20), 'warehouse-plan.csv')
  await page.getByRole('region', { name: 'Import preview' }).getByRole('button', { name: 'Create incident', exact: true }).click()
  await expect(page.getByText('Revision 1 published.', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'Open the new investigation' }).click()
  await expect(page.getByRole('heading', { name: 'Mapped spreadsheet investigation', exact: true })).toBeVisible()

  await page.getByRole('link', { name: 'Incident library', exact: true }).click()
  await page.getByRole('link', { name: 'Import incident evidence', exact: true }).click()
  await page.getByLabel('Incident', { exact: true }).selectOption(incidentId)
  await page.getByLabel('Source profile').selectOption('production-v1')
  await page.getByLabel('Knowledge cutoff', { exact: true }).fill(stamp(16))
  await inspectAndMap(page, exportCsv(outputId, 'final_good_delta', stamp(15), 10), 'output-ledger.csv')
  await page.getByLabel('Constant for count_mode', { exact: true }).fill('cumulative')
  await expect(page.getByRole('region', { name: 'Import preview' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Preview: BLOCKED' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Publish new revision', exact: true })).toBeDisabled()
  await page.getByLabel('Constant for count_mode', { exact: true }).fill('delta')
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Preview: READY' })).toBeVisible()
  await page.getByRole('region', { name: 'Import preview' }).getByRole('button', { name: 'Publish new revision', exact: true }).click()
  await expect(page.getByText('Revision 2 published.', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'Open the new investigation' }).click()
  await expect(page.getByRole('heading', { name: 'Mapped spreadsheet investigation', exact: true })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Evidence revision' })).toHaveValue('2')
  await expect(page.getByText('10', { exact: true }).first()).toBeVisible()
  await expect(page).toHaveURL(/analysis=/)
  const priorId = new URL(page.url()).searchParams.get('analysis')
  if (!priorId) throw new Error('Investigation did not pin an analysis identity.')
  const beforeResponse = await page.request.get(`${apiBase}/api/v1/analyses/${encodeURIComponent(priorId)}`)
  expect(beforeResponse.ok()).toBe(true)
  const before: Record<string, unknown> = await beforeResponse.json()
  expect(before.stale).toBe(false)
  const beforeContents = Object.fromEntries(Object.entries(before).filter(([name]) => name !== 'stale'))

  await page.getByRole('link', { name: 'Incident library', exact: true }).click()
  await page.getByRole('link', { name: 'Import incident evidence', exact: true }).click()
  await page.getByLabel('Incident', { exact: true }).selectOption(incidentId)
  await page.getByLabel('Source profile').selectOption('production-v1')
  await page.getByLabel('Knowledge cutoff', { exact: true }).fill(stamp(25))
  await inspectAndMap(page, exportCsv(correctionId, 'final_good_delta', stamp(20), 18, outputId), 'output-correction.csv', true)
  await page.getByRole('region', { name: 'Import preview' }).getByRole('button', { name: 'Publish new revision', exact: true }).click()
  await expect(page.getByText('Revision 3 published.', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'Open the new investigation' }).click()
  await expect(page.getByRole('combobox', { name: 'Evidence revision' })).toHaveValue('3')
  await expect(page.getByText('2', { exact: true }).first()).toBeVisible()
  const afterResponse = await page.request.get(`${apiBase}/api/v1/analyses/${encodeURIComponent(priorId)}`)
  expect(afterResponse.ok()).toBe(true)
  const after: Record<string, unknown> = await afterResponse.json()
  expect(after.stale).toBe(true)
  expect(Object.fromEntries(Object.entries(after).filter(([name]) => name !== 'stale'))).toEqual(beforeContents)
  await page.getByRole('combobox', { name: 'Evidence revision' }).selectOption('2')
  await expect(page.getByText('10', { exact: true }).first()).toBeVisible()
})
