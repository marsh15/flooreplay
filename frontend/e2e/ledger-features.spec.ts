import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { ensureBackend, signInOwner } from './helpers'

const stamp = (hour: number, minute: number) =>
  `2026-09-28T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00+05:30`
const header =
  'id,record_type,available_at,start,end,quantity,unit,count_mode,factory,line_id,order_id,style_id,stage'

test.beforeAll(ensureBackend)

async function previewCsv(page: Page, raw: string, filename: string) {
  await page
    .getByLabel('Local file')
    .setInputFiles({ name: filename, mimeType: 'text/csv', buffer: Buffer.from(raw) })
  await page.getByRole('button', { name: 'Inspect CSV columns', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Match CSV columns' })).toBeVisible()
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
}

test('source health separates reported intervals from missing records on the seeded example', async ({
  page,
}) => {
  await page.goto('/incidents/INC-001?revision=2')
  const section = page.locator('#source-health')
  await expect(section.getByRole('heading', { name: 'Source health' })).toBeVisible()
  await expect(section.getByText('10 due intervals reported; 7 below plan.')).toBeVisible()
  const table = section.getByRole('table', { name: /Output feed status/ })
  await expect(table.getByRole('row')).toHaveCount(11)
  await expect(table.locator('tbody').getByText('Reported', { exact: true })).toHaveCount(10)
  await expect(section.getByText(/rejected rows are not counted/)).toBeVisible()
})

// One sign-in for both live flows: the suite shares a 10-per-15-minute sign-in limit.
test('cumulative readings and a reviewed alias import with every source value accounted for', async ({
  page,
}) => {
  test.setTimeout(120_000)
  const suffix = Date.now()
  const scope = `Synthetic counter factory,S-CNT-${suffix},ORD-CNT-${suffix},STYLE-CNT,sewing`
  await page.goto('/incidents/imports')
  await signInOwner(page)
  await page.getByLabel('Import into').selectOption('new')
  await page.getByLabel('New incident ID').fill(`CNT-${suffix}`)
  await page.getByLabel('Incident title').fill('Counter export investigation')
  await page.getByLabel('Factory', { exact: true }).fill('Synthetic counter factory')
  await page.getByLabel('Sewing line', { exact: true }).fill(`S-CNT-${suffix}`)
  await page.getByLabel('Order ID', { exact: true }).fill(`ORD-CNT-${suffix}`)
  await page.getByLabel('Style ID', { exact: true }).fill('STYLE-CNT')
  await page.getByLabel('Window start', { exact: true }).fill(stamp(9, 0))
  await page.getByLabel('Window end', { exact: true }).fill(stamp(9, 45))
  await page.getByLabel('Knowledge cutoff', { exact: true }).fill(stamp(9, 0))
  const plan = [
    header,
    `plan-a-${suffix},baseline_plan,${stamp(8, 30)},${stamp(9, 0)},${stamp(9, 15)},20,good_units,delta,${scope}`,
    `plan-b-${suffix},baseline_plan,${stamp(8, 30)},${stamp(9, 15)},${stamp(9, 30)},20,good_units,delta,${scope}`,
    `plan-c-${suffix},baseline_plan,${stamp(8, 30)},${stamp(9, 30)},${stamp(9, 45)},20,good_units,delta,${scope}`,
  ].join('\n')
  await previewCsv(page, plan, 'plan.csv')
  await expect(page.getByRole('heading', { name: 'Preview: READY' })).toBeVisible()
  await page
    .getByRole('region', { name: 'Import preview' })
    .getByRole('button', { name: 'Create incident', exact: true })
    .click()
  await expect(page.getByText('Revision 1 published.', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'Open the new investigation' }).click()
  const incidentId = decodeURIComponent(new URL(page.url()).pathname.split('/').at(-1) ?? '')

  await page.getByRole('link', { name: 'Incident library', exact: true }).click()
  await page.getByRole('link', { name: 'Import incident evidence', exact: true }).click()
  await page.getByLabel('Incident', { exact: true }).selectOption(incidentId)
  await page.getByLabel('Source profile').selectOption('production-v1')
  await page.getByLabel('Knowledge cutoff', { exact: true }).fill(stamp(9, 35))
  const readings = [
    header,
    `r0-${suffix},final_good_delta,${stamp(9, 1)},${stamp(8, 45)},${stamp(9, 0)},340,good_units,cumulative,${scope}`,
    `r1-${suffix},final_good_delta,${stamp(9, 16)},${stamp(9, 0)},${stamp(9, 15)},352,good_units,cumulative,${scope}`,
    `r2-${suffix},final_good_delta,${stamp(9, 31)},${stamp(9, 15)},${stamp(9, 30)},370,good_units,cumulative,${scope}`,
  ].join('\n')
  await previewCsv(page, readings, 'counter.csv')
  await expect(page.getByRole('heading', { name: 'Preview: READY' })).toBeVisible()
  const conversion = page.getByRole('region', { name: 'Counter readings converted to deltas' })
  await expect(conversion.getByRole('row')).toHaveCount(4)
  await expect(conversion.getByText('Anchor', { exact: true })).toBeVisible()
  await expect(conversion.getByText(`12 since r0-${suffix}`)).toBeVisible()
  await expect(conversion.getByText(`18 since r1-${suffix}`)).toBeVisible()
  await page
    .getByRole('region', { name: 'Import preview' })
    .getByRole('button', { name: 'Publish new revision', exact: true })
    .click()
  await expect(page.getByText('Revision 2 published.', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'Open the new investigation' }).click()
  await expect(page.getByRole('combobox', { name: 'Evidence revision' })).toHaveValue('2')
  const health = page.locator('#source-health')
  await expect(health.getByText('2 due intervals reported; 2 below plan.')).toBeVisible()

  // The MES names the line differently; a reviewed alias reconciles it and keeps the original.
  await page.getByRole('link', { name: 'Incident library', exact: true }).click()
  await page.getByRole('link', { name: 'Import incident evidence', exact: true }).click()
  await page.getByLabel('Incident', { exact: true }).selectOption(incidentId)
  await page.getByLabel('Source profile').selectOption('production-v1')
  await page.getByLabel('Knowledge cutoff', { exact: true }).fill(stamp(9, 50))
  const mes = `${header}\nmes-${suffix},final_good_delta,${stamp(9, 46)},${stamp(9, 30)},${stamp(9, 45)},20,good_units,delta,${scope.replace(`S-CNT-${suffix}`, 'Line C')}`
  await page
    .getByLabel('Local file')
    .setInputFiles({ name: 'mes.csv', mimeType: 'text/csv', buffer: Buffer.from(mes) })
  await page.getByRole('button', { name: 'Inspect CSV columns', exact: true }).click()
  await page.getByText(/^Identifier aliases/).click()
  await page.getByRole('button', { name: 'Add identifier alias', exact: true }).click()
  await page.getByLabel('Source value', { exact: true }).fill('Line C')
  await expect(page.getByText(`→ S-CNT-${suffix}`)).toBeVisible()
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Preview: READY' })).toBeVisible()
  await expect(page.getByText('{"line_id":"Line C"}')).toBeVisible()
  await page
    .getByRole('region', { name: 'Import preview' })
    .getByRole('button', { name: 'Publish new revision', exact: true })
    .click()
  await expect(page.getByText('Revision 3 published.', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'Open the new investigation' }).click()
  await expect(
    page.locator('#source-health').getByText('3 due intervals reported; 2 below plan.'),
  ).toBeVisible()
})

for (const path of ['/incidents', '/incidents/INC-001?revision=2', '/incidents/imports']) {
  test(`phone width keeps ${path} inside the viewport`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(path)
    await expect(page.getByRole('main')).toBeVisible()
    await page.waitForLoadState('networkidle')
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })
}
