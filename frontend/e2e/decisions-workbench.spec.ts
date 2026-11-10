import AxeBuilder from '@axe-core/playwright'
import { mkdirSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import orders from './fixtures/decisions/orders.json' with { type: 'json' }
import readyDecision from './fixtures/decisions/ready-decision.json' with { type: 'json' }
import conflictingDecision from './fixtures/decisions/conflicting-decision.json' with { type: 'json' }
import overtimeDecision from './fixtures/decisions/overtime-decision.json' with { type: 'json' }
import reviewDecision from './fixtures/decisions/review-decision.json' with { type: 'json' }

async function mockDecisionApi(page: Page) {
  let records: unknown[] = []
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/decisions', '')
    if (path === '/orders') return route.fulfill({ json: orders })
    if (path === '/orders/POLO-221') return route.fulfill({ json: { ...readyDecision, records } })
    if (path === '/orders/POLO-222') return route.fulfill({ json: conflictingDecision })
    if (path === '/orders/POLO-223') return route.fulfill({ json: overtimeDecision })
    if (path === '/orders/POLO-224') return route.fulfill({ json: reviewDecision })
    if (path === '/orders/POLO-221/records') {
      const body = route.request().postDataJSON()
      records = [
        {
          id: 'record-1',
          recorded_at: '2026-10-22T06:00:00Z',
          reviewer: 'Maya',
          engine_outcome: 'ACCEPT',
          final_outcome: body.final_outcome,
          reason: body.reason,
          override: body.final_outcome !== 'ACCEPT',
        },
      ]
      return route.fulfill({ json: records[0] })
    }
    return route.fulfill({ status: 503, json: { message: 'Unavailable in workbench test' } })
  })
}

test('home lists order outcomes and the decision workbench exposes evidence', async ({ page }) => {
  await mockDecisionApi(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Order decisions' })).toBeVisible()
  await expect(page.getByRole('link', { name: /POLO-221/ })).toBeVisible()
  await expect(page.getByText('Accept', { exact: true }).first()).toBeVisible()
  const homeAxe = await new AxeBuilder({ page }).analyze()
  expect(homeAxe.violations).toEqual([])
  await page.setViewportSize({ width: 1440, height: 900 })
  mkdirSync('test-results/core', { recursive: true })
  await page.screenshot({ path: 'test-results/core/order-decisions-home-1440.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/core/order-decisions-home-390.png', fullPage: true })

  await page.getByRole('link', { name: /POLO-221/ }).click()
  await expect(page.getByRole('heading', { name: /POLO-221/ })).toBeVisible()
  await expect(page.getByText('READY', { exact: true })).toBeVisible()
  await expect(page.getByText('4,305 m', { exact: true })).toBeVisible()
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.screenshot({
    path: 'test-results/core/order-decision-workbench-1440.png',
    fullPage: true,
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({
    path: 'test-results/core/order-decision-workbench-390.png',
    fullPage: true,
  })
  await expect(
    page.getByRole('button', { name: 'fact-lot-221', exact: true }).first(),
  ).toBeVisible()
  await page.getByRole('button', { name: 'fact-lot-221', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Fact details' })).toBeVisible()
  const drawer = page.getByRole('dialog')
  await expect(drawer.getByText('fact-lot-220', { exact: true }).first()).toBeVisible()
  const workbenchAxe = await new AxeBuilder({ page }).analyze()
  expect(workbenchAxe.violations).toEqual([])
})

test('recording an override sends the exact replay cutoff and a trimmed reason', async ({
  page,
}) => {
  let recordBody: Record<string, unknown> | undefined
  let records: unknown[] = []
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/decisions', '')
    if (path === '/orders/POLO-221') return route.fulfill({ json: { ...readyDecision, records } })
    if (path === '/orders/POLO-221/records') {
      recordBody = route.request().postDataJSON()
      records = [
        {
          id: 'record-1',
          recorded_at: '2026-10-22T06:00:00Z',
          reviewer: 'Maya',
          engine_outcome: 'ACCEPT',
          final_outcome: 'DECLINE',
          reason: 'Fabric delayed',
          override: true,
        },
      ]
      return route.fulfill({ json: records[0] })
    }
    return route.fulfill({ status: 503, json: { message: 'Unavailable in record test' } })
  })
  await page.goto('/orders/POLO-221?cutoff=2026-10-22T05%3A30%3A00Z')
  await page.getByLabel('Final decision').selectOption('DECLINE')
  await expect(page.getByText('Human override', { exact: true })).toBeVisible()
  await page.getByLabel('Reason for this decision').fill('  Fabric delayed  ')
  await page.getByRole('button', { name: 'Record final decision' }).click()
  await expect
    .poll(() => recordBody)
    .toEqual({
      cutoff: '2026-10-22T05:30:00Z',
      policy_digest: 'policy-v1-abc',
      final_outcome: 'DECLINE',
      reason: 'Fabric delayed',
    })
  await expect(page.getByRole('heading', { name: 'Recorded decisions' })).toBeVisible()
  await expect(page.getByText('Fabric delayed', { exact: true })).toBeVisible()
})

test('conflicting evidence stays a written review finding and overtime conditions are explicit', async ({
  page,
}) => {
  await mockDecisionApi(page)
  await page.goto('/orders/POLO-222')
  await expect(page.getByText('CONFLICTING', { exact: true }).first()).toBeVisible()
  await expect(page.getByText(/ERP reports 4,000 m.*QC reports 1,200 m failed/)).toBeVisible()
  await expect(
    page.locator('#recommendation').getByText('NEEDS REVIEW', { exact: true }),
  ).toBeVisible()
  await page
    .getByRole('list', { name: 'Gate findings' })
    .getByRole('button', { name: 'fact-lot-222', exact: true })
    .click()
  const conflictDrawer = page.getByRole('dialog')
  await expect(
    conflictDrawer.getByText('fact-lot-222-correction', { exact: true }).first(),
  ).toBeVisible()
  await expect(
    conflictDrawer.getByText('fact-lot-222-recount', { exact: true }).first(),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Close fact details' }).click()

  await page.goto('/orders/POLO-223')
  await expect(page.getByText(/2 hours per line per day/)).toBeVisible()
  await expect(page.getByText(/across 3 lines for 10 days/)).toBeVisible()
})

test('an order affected by an unreviewed note links to the review queue', async ({ page }) => {
  await mockDecisionApi(page)
  await page.goto('/orders/POLO-224')
  await expect(page.getByText('NEEDS REVIEW', { exact: true }).first()).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'fact-note-224', exact: true }).first(),
  ).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open the review queue' })).toHaveAttribute(
    'href',
    '/review',
  )
})

test('v1 incident library has a dedicated investigations route and nav label', async ({ page }) => {
  await mockDecisionApi(page)
  await page.route('**/api/v1/incidents', (route) => route.fulfill({ json: { items: [] } }))
  await page.goto('/investigations')
  await expect(page.getByRole('heading', { name: 'Incident library' })).toBeVisible()
  await expect(
    page.locator('#main-content').getByRole('link', { name: 'Shortfall investigations (v1)' }),
  ).toHaveAttribute('href', '/investigations')
})

test('home explains when the decisions endpoint is unavailable', async ({ page }) => {
  await page.route('**/api/v1/decisions/orders', (route) =>
    route.fulfill({ status: 404, json: { detail: 'Not Found' } }),
  )
  await page.goto('/')
  await expect(
    page.getByText(/Order decisions are not available from this server yet/),
  ).toBeVisible()
  await expect(
    page.locator('#main-content').getByRole('link', { name: 'Shortfall investigations (v1)' }),
  ).toHaveAttribute('href', '/investigations')
  await expect(page.getByText('No orders yet')).toHaveCount(0)
})
