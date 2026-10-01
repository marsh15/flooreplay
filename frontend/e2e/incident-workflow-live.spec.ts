import { expect, test, type APIRequestContext } from '@playwright/test'
import { ensureBackend, signInOwner } from './helpers'

const apiBase = `${(process.env.E2E_API_BASE ?? 'http://localhost:8000').replace(/\/api\/v1\/?$/, '')}/api/v1`

test.beforeAll(ensureBackend)

async function createIsolatedInvestigation(request: APIRequestContext) {
  const username = process.env.E2E_USERNAME
  const password = process.env.E2E_PASSWORD
  if (!username || !password) throw new Error('Configure an owner in the isolated browser-test database.')
  const login = await request.post(`${apiBase}/auth/login`, { data: { username, password } })
  expect(login.ok()).toBeTruthy()
  const { token, user } = await login.json()
  const headers = { Authorization: `Bearer ${token}` }
  const incidentId = `WF-BROWSER-${crypto.randomUUID()}`
  const scope = { factory: 'Synthetic workflow test', line_id: 'WF1', order_id: 'WF-ORDER', style_id: 'WF-STYLE', stage: 'sewing', unit: 'good_units' }
  const intervals = [
    { start: '2026-09-20T09:00:00+05:30', end: '2026-09-20T09:15:00+05:30' },
    { start: '2026-09-20T09:15:00+05:30', end: '2026-09-20T09:30:00+05:30' },
  ]
  const rows = intervals.flatMap((interval, index) => [
    { ...scope, ...interval, id: `plan-${index}`, record_type: 'baseline_plan', quantity: 20, available_at: '2026-09-20T08:00:00+05:30' },
    { ...scope, ...interval, id: `output-${index}`, record_type: 'final_good_delta', quantity: 10, available_at: interval.end },
  ])
  const production = { incident_id: incidentId, base_revision: 0, cutoff: intervals[1].end, raw_text: JSON.stringify(rows), profile: 'production-v1', source_system: 'synthetic-output-ledger', timezone: 'Asia/Kolkata', filename: 'production.json', unit: 'good_units', scope }
  const preview = await request.post(`${apiBase}/incidents/imports/preview`, { headers, data: production })
  expect(preview.ok()).toBeTruthy()
  const parsedPreview = await preview.json()
  expect(parsedPreview.status).toBe('READY')
  const created = await request.post(`${apiBase}/incidents`, { headers, data: { ...production, title: 'Synthetic assigned maintenance check', window: { start: intervals[0].start, end: intervals[1].end }, preview_digest: parsedPreview.preview_digest, idempotency_key: crypto.randomUUID() } })
  expect(created.ok()).toBeTruthy()
  const operations = { ...production, base_revision: 1, cutoff: '2026-09-20T09:45:00+05:30', profile: 'operations-v1', filename: 'operations.json', raw_text: JSON.stringify([{ ...scope, id: 'machine-stop', record_type: 'machine_interruption', summary: 'Machine WF12 stopped; line impact needs confirmation.', start: '2026-09-20T09:10:00+05:30', end: '2026-09-20T09:20:00+05:30', available_at: '2026-09-20T09:35:00+05:30' }]) }
  const operationsPreview = await request.post(`${apiBase}/incidents/imports/preview`, { headers, data: operations })
  expect(operationsPreview.ok()).toBeTruthy()
  const published = await request.post(`${apiBase}/incidents/imports/publish`, { headers, data: { ...operations, preview_digest: (await operationsPreview.json()).preview_digest, idempotency_key: crypto.randomUUID() } })
  expect(published.ok()).toBeTruthy()
  return { incidentId, headers, user }
}

test('isolated workflow publishes evidence while keeping the previous report unchanged', async ({ page, request }) => {
  const prepared = await createIsolatedInvestigation(request)
  await page.goto(`/incidents/${prepared.incidentId}?revision=2`)
  await signInOwner(page)
  await expect(page.getByRole('heading', { name: 'Observed situation' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Assigned checks and outcomes', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/analysis=/)
  const originalAnalysis = new URL(page.url()).searchParams.get('analysis')
  if (!originalAnalysis) throw new Error('The investigation must have a pinned report identity.')
  const originalReport = await request.get(`${apiBase}/analyses/${originalAnalysis}`)
  const original = await originalReport.json()
  const indiaInput = (instant: number) => new Date(instant + 330 * 60_000).toISOString().slice(0, 19).replace(/:00$/, '')
  await page.getByRole('combobox', { name: 'Named assignee', exact: true }).selectOption(prepared.user.id)
  await page.getByLabel('Due at (India time)', { exact: true }).fill(indiaInput(Date.now() + 3_600_000))
  await page.getByRole('button', { name: 'Assign evidence check', exact: true }).click()
  const task = page.getByRole('article', { name: /Evidence check:/ }).first()
  await expect(task).toBeVisible()
  await expect(page.getByRole('button', { name: 'Record incident resolved', exact: true })).toBeDisabled()
  await task.getByText('Comments and assignment history', { exact: true }).click()
  await task.getByLabel('Comment or reassignment reason').fill('Maintenance accepted the assigned source check.')
  await task.getByRole('button', { name: 'Start check', exact: true }).click()
  await expect(task.getByText('in progress', { exact: true })).toBeVisible()
  await task.getByText('Record source response', { exact: true }).click()
  await task.getByLabel('Response summary', { exact: true }).fill('Maintenance source confirms the line stopped during the recorded interval.')
  await task.getByLabel('Source record reference', { exact: true }).fill('maintenance-status-test')
  await task.getByLabel('Observation occurred at (India time)', { exact: true }).fill('2026-09-20T09:10')
  await task.getByLabel('affected operations', { exact: true }).fill('All sewing operations on WF1')
  await task.getByLabel('repair status', { exact: true }).fill('Repair completed; recorded stop confirmed')
  await task.getByLabel('restart conditions', { exact: true }).fill('Operator confirmed stable machine operation')
  await task.getByLabel('Source explicitly confirms a line-wide production block').check()
  await task.getByLabel('Confirmed block start (India time)', { exact: true }).fill('2026-09-20T09:10')
  await task.getByLabel('Confirmed block end (India time)', { exact: true }).fill('2026-09-20T09:20')
  await task.getByRole('button', { name: 'Publish source response as new revision', exact: true }).click()
  await expect(page).toHaveURL(/revision=3/)
  await expect(task.getByText('answered', { exact: true })).toBeVisible()
  const workflowResponse = await request.get(`${apiBase}/incidents/${prepared.incidentId}/workflow`, { headers: prepared.headers })
  const workflow = await workflowResponse.json()
  expect(workflow.current_revision).toBe(3)
  expect(workflow.tasks[0].response.revision).toBe(3)
  const evidenceId = workflow.tasks[0].response.evidence_id
  await page.getByRole('button', { name: evidenceId, exact: true }).first().click()
  const drawer = page.getByRole('dialog', { name: 'Source evidence' })
  await expect(drawer.getByText(/maintenance-status-test/)).toBeVisible()
  await expect(drawer.getByText(/workflow-v1/)).toBeVisible()
  await page.keyboard.press('Escape')
  await task.getByText('Record action and measured outcome', { exact: true }).click()
  await task.getByLabel('Action actually taken', { exact: true }).fill('Checked the recorded stop and restart with maintenance.')
  const firstCompletionSecond = Math.ceil(Date.parse(workflow.tasks[0].created_at) / 1000) * 1000
  await expect.poll(() => Date.now(), { timeout: 2000 }).toBeGreaterThanOrEqual(firstCompletionSecond)
  await task.getByLabel('Actual completion at (India time)', { exact: true }).fill(indiaInput(Date.now()))
  await task.getByLabel('Observed good units (optional)', { exact: true }).fill('22')
  await task.getByLabel('Output observed at (India time)', { exact: true }).fill(indiaInput(Date.now()))
  await task.getByLabel('Outcome assessment', { exact: true }).fill('Restart observed; this does not establish a causal improvement.')
  await task.getByLabel('Remaining uncertainty', { exact: true }).fill('The contribution to total shift output remains unknown.')
  await task.getByRole('button', { name: 'Complete check and record outcome', exact: true }).click()
  await expect(task.getByText('completed', { exact: true })).toBeVisible()
  await expect(page.getByText('Incident open', { exact: true })).toBeVisible()
  await expect(task.getByText(/22 observed good units/)).toBeVisible()
  await page.getByLabel('Resolution or reopening rationale', { exact: true }).fill('Evidence check completed; no operational follow-up remains in this synthetic case.')
  await page.getByRole('button', { name: 'Record incident resolved', exact: true }).click()
  await expect(page.getByText('Incident resolved', { exact: true })).toBeVisible()
  const handover = page.getByRole('region', { name: 'Shift handover', exact: true })
  await expect(handover.getByText('No outstanding checks recorded.', { exact: true })).toBeVisible()
  await page.emulateMedia({ media: 'print' })
  const supervisor = page.getByRole('article', { name: 'Printable supervisor report' })
  await expect(supervisor.getByRole('heading', { name: 'Current action and resolution record' })).toBeVisible()
  await expect(supervisor.getByText(/Recorded output: 22 good units/)).toBeVisible()
  const unchanged = await request.get(`${apiBase}/analyses/${originalAnalysis}`)
  const after = await unchanged.json()
  expect(after.revision).toBe(2)
  expect(after.metrics).toEqual(original.metrics)
  expect(after.timeline).toEqual(original.timeline)
  expect(after.timeline.some((record: { id: string }) => record.id === evidenceId)).toBe(false)
})
