import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import savedReport from '../src/data/hero-report.json' with { type: 'json' }
import savedRevision from '../src/data/hero-revision.json' with { type: 'json' }
import type { IncidentWorkflowData, WorkflowTask } from '../src/lib/workflow'

const owner = { id: 'owner-1', username: 'owner', display_name: 'Production owner', role: 'owner' }
const other = { id: 'reviewer-2', username: 'reviewer', display_name: 'Maintenance reviewer', role: 'reviewer' }
const taskFixture = (): WorkflowTask => ({
  id: 'task-1', incident_id: 'INC-001', analysis_id: 'analysis-2', revision: 2, proposal_id: 'verify-material',
  question: 'Confirm fabric readiness on S4', requested_fields: ['affected_operations', 'material_status', 'restart_conditions'],
  assignee_id: owner.id, assignee_name: owner.display_name, due_at: '2026-09-30T08:30:00+05:30',
  status: 'OPEN', created_by: owner.id, created_at: '2026-09-30T08:00:00+05:30', updated_at: '2026-09-30T08:00:00+05:30', overdue: true,
  activities: [], response: null, outcome: null,
})

async function signIn(page: Page) {
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill('local-test')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible()
}

async function setup(page: Page, options: { role?: 'owner' | 'reviewer'; existingTask?: boolean; completedTask?: boolean; currentRevision?: number; failFirstCreate?: boolean } = {}) {
  let revision = options.currentRevision ?? 2
  let task: WorkflowTask | null = options.existingTask ? taskFixture() : null
  if (task && options.completedTask) {
    task.status = 'COMPLETED'; task.overdue = false
    task.outcome = { action_taken: 'Material readiness checked.', actual_completed_at: '2026-09-30T08:15:00+05:30', observed_good_units: 20, observed_at: '2026-09-30T08:30:00+05:30', assessment: 'Bucket rate met plan.', remaining_uncertainty: 'Machine contribution unconfirmed.' }
  }
  let resolution: IncidentWorkflowData['resolution'] = 'OPEN'
  const payloads: { path: string; body: unknown }[] = []
  let createAttempts = 0
  let privateReads = 0
  const getWorkflow = (): IncidentWorkflowData => ({ incident_id: 'INC-001', current_revision: revision, resolution,
    resolution_rationale: resolution === 'RESOLVED' ? 'Supervisor checked measured output and uncertainty.' : null,
    resolution_activities: [], tasks: task ? [task] : [], handover: { summary: 'S4 output needs a material-readiness check.', cutoff: savedReport.cutoff, uncertainties: ['No claim of confirmed cause.'], outstanding_checks: task && task.status !== 'COMPLETED' && task.status !== 'CANCELLED' ? [task] : [] },
  })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    if (path === '/auth/login') return route.fulfill({ json: { token: 'local-test-token', user: options.role === 'reviewer' ? other : owner } })
    if (path === '/auth/logout') return route.fulfill({ json: { ok: true } })
    if (path === '/capabilities') return route.fulfill({ json: { imports_enabled: false, reviews_enabled: true, ai: { generation_available: false } } })
    if (path === '/incidents') return route.fulfill({ json: { items: [{ ...savedRevision, line: 'S4', revision, window_start: savedRevision.window.start, window_end: savedRevision.window.end, shortfall: 74, status: 'COMPLETE' }] } })
    if (/^\/incidents\/INC-001\/revisions\/\d+$/.test(path)) return route.fulfill({ json: { ...savedRevision, revision: Number(path.split('/').at(-1)), available_revisions: [1, 2, 3] } })
    if (/^\/incidents\/INC-001\/analyses$/.test(path)) return route.fulfill({ json: { ...savedReport, id: `analysis-${revision}`, revision, execution_kind: 'live_deterministic', proposals: savedReport.proposals.slice(0, 1) } })
    if (/^\/analyses\/analysis-\d+$/.test(path)) return route.fulfill({ json: { ...savedReport, id: path.split('/').at(-1), revision: Number(path.split('-').at(-1)), execution_kind: 'live_deterministic', proposals: savedReport.proposals.slice(0, 1) } })
    if (path === '/workflow/assignees') { privateReads++; return route.fulfill({ json: { items: [owner, other] } }) }
    if (path === '/incidents/INC-001/workflow') { privateReads++; return route.fulfill({ json: getWorkflow() }) }
    if (route.request().method() === 'POST' && (path.endsWith('/checks') || path.startsWith('/checks/') || path.endsWith('/resolution'))) {
      const body: Record<string, unknown> = route.request().postDataJSON()
      payloads.push({ path, body })
      if (path.endsWith('/checks')) {
        createAttempts++
        if (options.failFirstCreate && createAttempts === 1) return route.abort('failed')
        task = { ...taskFixture(), assignee_id: String(body.assignee_id), due_at: String(body.due_at) }
      } else if (path.endsWith('/update') && task) {
        if (body.status === 'IN_PROGRESS') task.status = 'IN_PROGRESS'
        if (body.status === 'CANCELLED') task.status = 'CANCELLED'
        if (body.assignee_id === other.id) { task.assignee_id = other.id; task.assignee_name = other.display_name }
        task.updated_at = '2026-09-30T08:10:00+05:30'
        task.activities.push({ id: String(task.activities.length), actor: owner.id, kind: 'COMMENT', text: String(body.comment), created_at: task.updated_at })
      } else if (path.endsWith('/respond') && task) {
        revision++
        task.status = 'ANSWERED'; task.overdue = false
        task.response = { evidence_id: 'response-evidence', revision, summary: String(body.summary), source_ref: String(body.source_ref), occurred_at: String(body.occurred_at), details: { affected_operations: 'S4 seam', material_status: 'Ready', restart_conditions: 'Warehouse cleared' } }
      } else if (path.endsWith('/complete') && task) {
        task.status = 'COMPLETED'
        task.outcome = { action_taken: String(body.action_taken), actual_completed_at: String(body.actual_completed_at), observed_good_units: Number(body.observed_good_units), observed_at: String(body.observed_at), assessment: String(body.assessment), remaining_uncertainty: String(body.remaining_uncertainty) }
      } else if (path.endsWith('/resolution')) resolution = body.state === 'RESOLVED' ? 'RESOLVED' : 'OPEN'
      return route.fulfill({ json: path.endsWith('/resolution') ? getWorkflow() : task })
    }
    return route.fulfill({ status: 503, json: { message: 'Unsupported local fixture endpoint' } })
  })
  return { payloads, privateReads: () => privateReads, advanceRevision: () => { revision++ } }
}

test('private assignments stay hidden before sign-in and after sign-out', async ({ page }) => {
  const fixture = await setup(page, { existingTask: true })
  await page.goto('/incidents/INC-001?revision=2')
  const workflow = page.locator('#assigned-checks')
  await expect(workflow.getByText(/Sign in as an owner or invited reviewer/)).toBeVisible()
  expect(fixture.privateReads()).toBe(0)
  await signIn(page)
  await expect(workflow.getByRole('article')).toContainText('Confirm fabric readiness on S4')
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(workflow.getByRole('article')).toHaveCount(0)
  await expect(page.getByText('Production owner · due')).toHaveCount(0)
})

test('failed assignment retries the same frozen payload and idempotency key', async ({ page }) => {
  const fixture = await setup(page, { failFirstCreate: true })
  await page.goto('/incidents/INC-001?revision=2')
  await signIn(page)
  const workflow = page.locator('#assigned-checks')
  await workflow.getByLabel('Named assignee').selectOption(owner.id)
  await workflow.getByLabel('Due at (India time)', { exact: true }).fill('2026-10-01T09:00:01')
  await workflow.getByRole('button', { name: 'Assign evidence check', exact: true }).click()
  await expect(workflow.getByRole('button', { name: 'Retry same request' })).toBeVisible()
  await expect(workflow.getByLabel('Named assignee')).toBeDisabled()
  await workflow.getByRole('button', { name: 'Retry same request' }).click()
  await expect(workflow.getByRole('article')).toContainText('Confirm fabric readiness on S4')
  const assignments = fixture.payloads.filter((entry) => entry.path.endsWith('/checks'))
  expect(assignments).toHaveLength(2)
  expect(assignments[0]?.body).toEqual(assignments[1]?.body)
  expect(assignments[0]?.body).toMatchObject({ assignee_id: owner.id, due_at: '2026-10-01T09:00:01+05:30' })
})

test('source response creates a revision; outcome completion leaves incident open until explicit resolution', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const fixture = await setup(page, { existingTask: true })
  await page.goto('/incidents/INC-001?revision=2')
  await signIn(page)
  const workflow = page.locator('#assigned-checks')
  const check = workflow.getByRole('article')
  await expect(check).toContainText('overdue')
  await check.getByText('Comments and assignment history', { exact: true }).click()
  await expect(check.getByRole('button', { name: 'Start check', exact: true })).toBeDisabled()
  await check.getByLabel('Comment or reassignment reason').fill('Production lead begins the source check.')
  await check.getByRole('button', { name: 'Start check', exact: true }).click()
  await expect(check).toContainText('in progress')
  await check.getByText('Record source response', { exact: true }).click()
  await check.getByLabel('Response summary').fill('Warehouse confirmed fabric readiness.')
  await check.getByLabel('Source record reference').fill('warehouse-record-218')
  await check.getByLabel('Observation occurred at (India time)').fill('2026-09-28T10:45')
  await check.getByLabel('affected operations').fill('S4 seam')
  await check.getByLabel('material status').fill('Ready')
  await check.getByLabel('restart conditions').fill('Warehouse cleared')
  await check.getByRole('button', { name: 'Publish source response as new revision' }).click()
  await expect(page).toHaveURL(/revision=3/)
  await expect(check).toContainText('Source response · evidence revision 3')
  await check.getByText('Record action and measured outcome', { exact: true }).click()
  await check.getByLabel('Action actually taken').fill('Material transfer checked and production resumed.')
  await check.getByLabel('Actual completion at (India time)').fill('2026-09-30T08:15')
  await check.getByLabel('Observed good units (optional)').fill('20')
  await check.getByLabel('Output observed at (India time)').fill('2026-09-30T08:30')
  await check.getByLabel('Outcome assessment').fill('Output returned to planned bucket rate.')
  await check.getByLabel('Remaining uncertainty', { exact: true }).fill('Machine contribution remains unconfirmed.')
  await check.getByRole('button', { name: 'Complete check and record outcome' }).click()
  await expect(check).toContainText('Recorded outcome')
  await expect(workflow.getByText('Incident open', { exact: true })).toBeVisible()
  await expect(check).toContainText('20 observed good units')
  await workflow.getByLabel('Resolution or reopening rationale').fill('Supervisor checked measured output and uncertainty.')
  await workflow.getByRole('button', { name: 'Record incident resolved', exact: true }).click()
  await expect(workflow.getByText('Incident resolved', { exact: true })).toBeVisible()
  expect(fixture.payloads.find((entry) => entry.path.endsWith('/respond'))?.body).toMatchObject({ base_revision: 2 })
  expect(fixture.payloads.find((entry) => entry.path.endsWith('/resolution'))?.body).toMatchObject({ base_revision: 3 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.emulateMedia({ media: 'print' })
  await expect(workflow.getByRole('heading', { name: 'Shift handover' })).toBeVisible()
  await expect(workflow.getByText('Recorded outcome', { exact: true })).toBeVisible()
  await expect(workflow.getByRole('button', { name: 'Reopen incident' })).toBeHidden()
})

test('unassigned reviewer can comment but cannot start, reassign, answer, or complete another reviewer check', async ({ page }) => {
  await setup(page, { role: 'reviewer', existingTask: true })
  await page.goto('/incidents/INC-001?revision=2')
  await signIn(page)
  const check = page.locator('#assigned-checks').getByRole('article')
  await check.getByText('Comments and assignment history', { exact: true }).click()
  await expect(check.getByRole('button', { name: 'Start check', exact: true })).toHaveCount(0)
  await expect(check.getByLabel('Reassign to')).toHaveCount(0)
  await expect(check.getByText('Record source response', { exact: true })).toHaveCount(0)
  await check.getByLabel('Comment or reassignment reason').fill('Maintenance log still needs confirmation.')
  await check.getByRole('button', { name: 'Save comment or assignment' }).click()
  await check.getByText(/Audit history/).click()
  await expect(check).toContainText('Maintenance log still needs confirmation.')
})

test('reviewer can make explicit resolution and terminal checks allow only comments', async ({ page }) => {
  await setup(page, { role: 'reviewer', existingTask: true, completedTask: true })
  await page.goto('/incidents/INC-001?revision=2')
  await signIn(page)
  const workflow = page.locator('#assigned-checks')
  const check = workflow.getByRole('article')
  await check.getByText('Comments and assignment history', { exact: true }).click()
  await expect(check.getByRole('button', { name: 'Start check', exact: true })).toHaveCount(0)
  await expect(check.getByRole('button', { name: 'Cancel check with reason', exact: true })).toHaveCount(0)
  await expect(check.getByLabel('Reassign to')).toHaveCount(0)
  await expect(check.getByText('Record source response', { exact: true })).toHaveCount(0)
  await expect(check.getByText('Record action and measured outcome', { exact: true })).toHaveCount(0)
  await check.getByLabel('Comment or reassignment reason').fill('Supervisor acknowledged the remaining uncertainty.')
  await check.getByRole('button', { name: 'Save comment or assignment' }).click()
  await check.getByText(/Audit history/).click()
  await expect(check).toContainText('Supervisor acknowledged the remaining uncertainty.')
  await workflow.getByLabel('Resolution or reopening rationale').fill('Reviewed completed outcome with the production lead.')
  await workflow.getByRole('button', { name: 'Record incident resolved', exact: true }).click()
  await expect(workflow.getByText('Incident resolved', { exact: true })).toBeVisible()
})

test('pinned historical report keeps latest workflow explicit and cannot assign stale checks', async ({ page }) => {
  await setup(page, { existingTask: true, currentRevision: 3 })
  await page.goto('/incidents/INC-001?revision=2&analysis=analysis-2')
  await signIn(page)
  const workflow = page.locator('#assigned-checks')
  await expect(workflow.getByText(/This workflow shows the latest incident state/)).toBeVisible()
  await expect(workflow.getByText(/This report is revision 2. Open revision 3/)).toBeVisible()
  await expect(workflow.getByRole('button', { name: 'Assign evidence check', exact: true })).toHaveCount(0)
  await workflow.getByRole('article').getByText('Record source response', { exact: true }).click()
  await expect(workflow.getByText(/Saving appends structured evidence to revision 4/)).toBeVisible()
  await workflow.getByRole('button', { name: 'Open latest evidence revision' }).click()
  await expect(page).toHaveURL(/revision=3/)
  await expect(workflow.getByText(/This report is revision 2/)).toHaveCount(0)
})

test('switching report revision refreshes the workflow after an external evidence update', async ({ page }) => {
  const fixture = await setup(page, { existingTask: true })
  await page.goto('/incidents/INC-001?revision=2')
  await signIn(page)
  const workflow = page.locator('#assigned-checks')
  await expect(workflow.getByText(/latest revision 2/)).toBeVisible()
  const before = fixture.privateReads()
  fixture.advanceRevision()
  await page.getByRole('combobox', { name: 'Evidence revision' }).selectOption('3')
  await expect(workflow.getByText(/latest revision 3/)).toBeVisible()
  expect(fixture.privateReads()).toBeGreaterThan(before)
  await workflow.getByRole('article').getByText('Record source response', { exact: true }).click()
  await expect(workflow.getByText(/Saving appends structured evidence to revision 4/)).toBeVisible()
  await expect(workflow.getByText(/This report is revision 3. Open revision 2/)).toHaveCount(0)
})
