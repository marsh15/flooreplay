import { expect, test } from '@playwright/test'

test('saved calculation inputs open their source records offline', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => route.abort())
  await page.goto('/')
  await page.getByRole('link', { name: 'Delayed start on sewing line S4' }).click()
  await expect(page.getByRole('heading', { name: 'Calculation inputs' })).toBeVisible()
  await expect(page.getByText('variance = observed - planned; shortfall = max(0, planned - observed)')).toBeVisible()
  const table = page.getByRole('table', { name: 'Comparable completed 15-minute production buckets used in the reported calculation' })
  await expect(table.getByRole('row')).toHaveCount(11)
  await table.getByRole('button', { name: 'plan-0' }).click()
  await expect(page.getByRole('heading', { name: 'Source evidence' })).toBeVisible()
  await expect(page.getByText('synthetic-fixture:INC-001@2/plan-0')).toBeVisible()
  await page.keyboard.press('Escape')
  await table.getByRole('button', { name: 'out-0' }).click()
  await expect(page.getByText('synthetic-fixture:INC-001@2/out-0')).toBeVisible()
})

test('saved evaluation compares retrievers on one label revision', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => route.abort())
  await page.goto('/evaluation')
  await expect(page.getByRole('heading', { name: 'Common-label retrieval comparison' })).toBeVisible()
  await expect(page.getByText(/same retrieval-observable-v1 relevance labels/)).toBeVisible()
  const table = page.getByRole('table', { name: 'Title-only baseline and cutoff-visible evidence-card retrieval measured against common labels' })
  await expect(table.getByRole('row', { name: /Baseline · title only/ })).toContainText('3 / 6')
  await expect(table.getByRole('row', { name: /Candidate · cutoff-visible evidence card/ })).toContainText('6 / 6')
  await expect(page.getByText('material', { exact: true }).first()).toBeVisible()
})
