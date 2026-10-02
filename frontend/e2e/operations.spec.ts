import { expect, test } from '@playwright/test'
import type { OperationsReport } from '../src/lib/operations'

test('owner diagnoses uncertain work through receipts and runbook, then signout clears evidence', async ({ page }) => {
  const evidence: OperationsReport = { events: [{ request_id: 'request-failure-001', route: '/imports/{source_id}', method: 'POST', status_code: 503, failure_category: 'IMPORT_SOURCE_INVALID', elapsed_seconds: 0.2, created_at: '2026-10-01T08:00:00Z' }], operations: [{ id: 'operation-uncertain-001', request_id: 'request-provider-001', task: 'question', status: 'UNCERTAIN', incident_id: 'private-owner-case', analysis_id: 'pinned-analysis', elapsed_seconds: null, provider_receipts: [{ request_id: 'provider-request-001' }], inspect_url: '/api/v1/ai-runs/operation-uncertain-001' }], allowance_entries: [{ id: 'reservation-001', purpose: 'reviewer', operation: 'generation', status: 'UNCERTAIN', reserved_inr: 5, charged_inr: 0 }], alerts: [{ code: 'UNCERTAIN_PROVIDER_CHARGE', severity: 'page', operation_id: 'operation-uncertain-001', remediation: 'Inspect provider receipts and billing before reconciling the retained reservation. Do not submit a new paid request.' }], execution_model: 'bounded_request_path', recovery_policy: 'Expired calls remain uncertain and no provider call is retried automatically.', limitations: ['External alert delivery is not configured.'] }
  let requests = 0
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    if (path === '/auth/login') return route.fulfill({ json: { token: 'offline-owner', user: { id: 'owner-ops', username: 'owner', display_name: 'Owner', role: 'owner' } } })
    if (path === '/auth/logout') return route.fulfill({ json: { ok: true } })
    if (path === '/capabilities') return route.fulfill({ json: { imports_enabled: false, reviews_enabled: true } })
    if (path === '/operations') { requests++; return route.fulfill({ json: evidence }) }
    return route.fulfill({ status: 404, json: { message: 'Unused fixture endpoint' } })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/operations')
  await expect(page.getByText('Sign in as an owner to inspect your operations.')).toBeVisible()
  expect(requests).toBe(0)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill('offline-test')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText('page · UNCERTAIN_PROVIDER_CHARGE')).toBeVisible()
  await expect(page.getByText(/reserved ₹5.00/)).toBeVisible()
  await page.getByRole('link', { name: 'Open response runbook' }).click()
  await expect(page.getByRole('heading', { name: 'Response runbook' })).toBeVisible()
  await page.getByText('Provider receipt identifiers').click()
  await expect(page.getByText(/provider-request-001/)).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByText('private-owner-case', { exact: false })).toHaveCount(0)
  await expect(page.getByText('Sign in as an owner to inspect your operations.')).toBeVisible()
})
