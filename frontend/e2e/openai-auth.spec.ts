import { expect, test } from '@playwright/test'
import fs from 'node:fs'

const report = JSON.parse(fs.readFileSync('src/data/hero-report.json', 'utf8'))
const revision = JSON.parse(fs.readFileSync('src/data/hero-revision.json', 'utf8'))
const library = JSON.parse(fs.readFileSync('src/data/incident-library.json', 'utf8'))

test('reviewer auth stays in memory and a disconnected AI operation is recovered without another paid call', async ({ page }) => {
  let paidRequests = 0
  let authenticated = false
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const bearer = route.request().headers().authorization
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body })
    if (path.endsWith('/auth/login')) { authenticated = true; return reply({ token: 'test-memory-token', user: { id: 'reviewer-1', username: 'reviewer', display_name: 'Shift reviewer', role: 'reviewer' }, expires_at: '2030-01-01T00:00:00Z' }) }
    if (path.endsWith('/capabilities')) return reply({ mode: 'local', imports_enabled: false, reviews_enabled: authenticated && !!bearer, export_enabled: authenticated && !!bearer, ai: { generation_available: authenticated && !!bearer, reason: authenticated ? null : 'NOT_SIGNED_IN', index_ready: false }, execution_limits: {}, configurations: [] })
    if (path.endsWith('/incidents')) return reply(library)
    if (path.includes('/revisions/')) return reply(revision)
    if (path.endsWith('/analyses')) return reply({ ...report, execution_kind: 'live' })
    if (path.includes('/analyses/') && !path.endsWith('/ai-runs')) return reply({ ...report, execution_kind: 'live' })
    if (path.endsWith('/ai-runs')) { expect(bearer).toBe('Bearer test-memory-token'); paidRequests++; return route.abort() }
    if (path.includes('/ai-runs/by-request/')) return reply({ id: 'ai-1', status: 'COMPLETED', analysis_id: report.id, task: 'question', configuration: { generation_model: 'gpt-4.1-mini-2025-04-14' }, result: { output: { claims: [{ text: 'The output record establishes a shortfall.', evidence_ids: ['EV-MAT-1'], metric_ids: ['shortfall'], historical_refs: [], source_fields: [], rendered_metrics: [{ id: 'shortfall', value: 74, unit: 'good_units' }] }], abstention_reasons: ['The cause remains unresolved.'] }, validation: { errors: [] } } })
    return reply({}, 404)
  })
  await page.goto('/incidents/INC-001?revision=2')
  await expect(page.getByRole('button', { name: 'Generate draft' })).toBeDisabled()
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('reviewer')
  await page.getByLabel('Password').fill('test-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText('Shift reviewer · reviewer')).toBeVisible()
  await page.getByRole('button', { name: 'Generate draft' }).click()
  await expect(page.getByRole('button', { name: 'Recover existing request' })).toBeVisible()
  await page.getByRole('button', { name: 'Recover existing request' }).click()
  await expect(page.getByText('The output record establishes a shortfall.')).toBeVisible()
  await expect(page.getByText(/shortfall: 74 good_units/)).toBeVisible()
  await expect(page.getByText('The cause remains unresolved.')).toBeVisible()
  expect(paidRequests).toBe(1)
  expect(await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) }))).toEqual({ local: [], session: [] })
  await page.reload()
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generate draft' })).toBeDisabled()
})

for (const terminal of [
  { status: 'REFUSED', error: 'Provider declined to return a structured draft', displayed: 'Provider declined to return a structured draft' },
  { status: 'UNCERTAIN', error: 'Provider connection interrupted; retained reservation, no automatic retry', displayed: 'Provider connection interrupted; retained reservation, no automatic retry' },
  { status: 'UNAVAILABLE', error: 'MODEL_ACCESS_UNAVAILABLE', displayed: 'The configured model is unavailable to this API project.' },
]) {
  test(`terminal ${terminal.status} stays visible during recovery and never appears reviewable`, async ({ page }) => {
    let paidRequests = 0
    let providerReady = true
    const run = { id: 'terminal-run', analysis_id: report.id, task: 'question', status: terminal.status, result: { errors: [terminal.error] } }
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      const reply = (body: unknown) => route.fulfill({ json: body })
      if (path.endsWith('/auth/login')) return reply({ token: 'terminal-memory-token', user: { id: 'reviewer-1', username: 'reviewer', display_name: 'Reviewer', role: 'reviewer' } })
      if (path.endsWith('/capabilities')) return reply({ imports_enabled: false, reviews_enabled: true, ai: { generation_available: providerReady && !!route.request().headers().authorization, reason: providerReady ? null : 'MISSING_API_CONFIGURATION', index_ready: false }, execution_limits: {}, configurations: [] })
      if (path.endsWith('/incidents')) return reply(library)
      if (path.includes('/revisions/')) return reply(revision)
      if (path.endsWith('/ai-runs')) { paidRequests++; providerReady = false; return reply(run) }
      if (path.includes('/ai-runs/by-request/')) return reply(run)
      if (path.includes('/analyses')) return reply({ ...report, execution_kind: 'live' })
      if (path.endsWith('/corpora')) return reply({ items: [] })
      return route.fulfill({ status: 404, json: {} })
    })
    await page.goto('/incidents/INC-001?revision=2')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByLabel('Username').fill('reviewer')
    await page.getByLabel('Password').fill('test-password')
    await page.getByRole('button', { name: 'Continue', exact: true }).click()
    await page.getByRole('button', { name: 'Generate draft' }).click()
    await expect(page.getByRole('alert').filter({ hasText: terminal.displayed })).toBeVisible()
    await expect(page.getByText(/Awaiting human review/)).toHaveCount(0)
    await page.getByRole('button', { name: 'Recover existing request' }).click()
    await expect(page.getByRole('alert').filter({ hasText: terminal.displayed })).toBeVisible()
    const identity = await page.getByLabel('Request identity').inputValue()
    await page.reload()
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByLabel('Username').fill('reviewer')
    await page.getByLabel('Password').fill('test-password')
    await page.getByRole('button', { name: 'Continue', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Generate draft' })).toBeDisabled()
    await page.getByLabel('Request identity').fill(identity)
    await page.getByRole('button', { name: 'Recover existing request' }).click()
    await expect(page.getByRole('alert').filter({ hasText: terminal.displayed })).toBeVisible()
    expect(paidRequests).toBe(1)
  })
}

test('current provider measurements remain separate from historical Qwen results', async ({ page }) => {
  const evaluation = JSON.parse(fs.readFileSync('src/data/evaluation-report.json', 'utf8'))
  await page.route('**/api/v1/**', (route) => {
    if (route.request().url().endsWith('/evaluation-reports/incident-core-v1')) return route.fulfill({ json: { ...evaluation, current_provider: { provider: 'openai', status: 'MEASURED_STRUCTURAL_ONLY', attempted: 3, completed: 2, failed: 1, running: 0, unverified_completed: 0, reviewed: 0, reviewed_claims: 0, supported_claims: 0 } } })
    return route.fulfill({ status: 503, json: { message: 'Unavailable test fixture endpoint' } })
  })
  await page.goto('/evaluation')
  const current = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Current OpenAI evaluation' }) })
  await expect(current.getByText('OpenAI: measured structural only.')).toBeVisible()
  await expect(current.getByText(/Human-reviewed claim support: Not reviewed/)).toBeVisible()
  await expect(current).toContainText('attempted')
  await expect(page.getByText(/Provider results below are historical Qwen measurements/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Historical Qwen and deterministic results' })).toBeVisible()
})
