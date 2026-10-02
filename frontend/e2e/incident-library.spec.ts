import { expect, test } from '@playwright/test'

const summary = (id: string, library_group: 'curated_demo' | 'engineering_fixture' | 'operational') => ({
  id, library_group, revision: 2, title: `Case ${id}`, line: id === 'INC-001' ? 'S4' : 'S2',
  window_start: '2026-09-28T09:00:00+05:30', window_end: '2026-09-28T12:00:00+05:30', cutoff: '2026-09-28T11:30:00+05:30',
  shortfall: 74, status: 'COMPLETE', evidence_completeness: '4/6 available sources; timeline partial', last_reviewed_revision: 1,
})

for (const width of [1440, 390]) {
  test(`library separates fixture browsing from imported work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.route('**/api/v1/**', (route) => {
      if (new URL(route.request().url()).pathname.endsWith('/incidents')) {
        return route.fulfill({ json: { items: [summary('INC-001', 'curated_demo'), summary('REL-IMPORTED', 'operational'), ...Array.from({ length: 15 }, (_, index) => summary(`FIXTURE-${index + 1}`, 'engineering_fixture'))] } })
      }
      return route.fulfill({ status: 503, json: { message: 'Unavailable' } })
    })
    await page.goto('/')
    await expect(page.getByRole('link', { name: 'Start the example investigation' })).toHaveAttribute('href', '/incidents/INC-001?revision=2')
    await expect(page.getByRole('link', { name: 'Case REL-IMPORTED' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Case FIXTURE-1', exact: true })).toHaveCount(0)
    const records = width === 390 ? page.getByRole('article') : page.getByRole('table')
    await expect(records.getByText('Calculation complete', { exact: true }).first()).toBeVisible()
    await expect(records.getByText('4/6 available sources; timeline partial', { exact: true }).first()).toBeVisible()
    await expect(records.getByText(/^Review applies to revision 1/).first()).toBeVisible()
    await page.getByRole('button', { name: 'Engineering fixtures (15)' }).click()
    await expect(page.getByRole('link', { name: 'Case REL-IMPORTED' })).toHaveCount(0)
    await expect(page.getByRole('navigation', { name: 'Incident pages' })).toContainText('Showing 1–12 of 15 cases')
    await page.getByRole('button', { name: 'Next page' }).click()
    await expect(page.getByRole('link', { name: 'Case FIXTURE-13' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Incident pages' })).toContainText('page 2 of 2')
    await page.getByRole('button', { name: 'Demo and imported cases (2)' }).click()
    await page.getByRole('combobox', { name: 'Line', exact: true }).selectOption('S4')
    await expect(page.getByRole('link', { name: 'Case INC-001' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Case REL-IMPORTED' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Next page' })).toBeDisabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}

test('offline first visit opens the saved example and explains unavailable search', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => route.abort())
  await page.goto('/')
  await expect(page.getByText(/Showing bundled saved demo cases/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Engineering fixtures (0)' })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search incident evidence' }).fill('fabric')
  await expect(page.getByText(/Live search is unavailable while the API is offline/)).toBeVisible()
  await page.getByRole('button', { name: 'Clear search' }).click()
  await page.getByRole('link', { name: 'Start the example investigation' }).click()
  await expect(page.getByRole('heading', { name: 'Observed situation' })).toBeVisible()
  await expect(page.getByText('74', { exact: true }).first()).toBeVisible()
})

test('library filters evidence and authenticated open actions without exposing assignees after signout', async ({ page }) => {
  let unavailable = false
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/login')) return route.fulfill({ json: { token: 'isolated-mock', user: { id: 'reviewer', username: 'reviewer', display_name: 'Reviewer', role: 'reviewer' } } })
    if (path.endsWith('/auth/logout')) return route.fulfill({ json: {} })
    if (path.endsWith('/incidents')) {
      if (unavailable) return route.abort()
      const signedIn = !!route.request().headers().authorization
      return route.fulfill({ json: { items: [
        { ...summary('INC-001', 'curated_demo'), evidence_state: 'PARTIAL', workflow: signedIn ? { investigation_state: 'OPEN', action_state: 'OPEN_ACTIONS', open_action_count: 1, assignees: [{ id: 'person', name: 'Private assignee' }] } : null },
        { ...summary('IMPORTED', 'operational'), evidence_state: 'ALL_REPORTED_SOURCES_AVAILABLE', workflow: signedIn ? { investigation_state: 'RESOLVED', action_state: 'NO_OPEN_ACTIONS', open_action_count: 0, assignees: [] } : null },
      ] } })
    }
    return route.fulfill({ status: 503, json: { message: 'Unavailable' } })
  })
  await page.goto('/')
  await expect(page.getByRole('combobox', { name: 'Assignee (open actions)' })).toBeDisabled()
  await expect(page.getByRole('link', { name: 'Try the safe action demo' })).toHaveAttribute('href', '/demo')
  await page.getByRole('combobox', { name: 'Evidence state', exact: true }).selectOption('PARTIAL')
  await expect(page.getByRole('link', { name: 'Case IMPORTED' })).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Evidence state', exact: true }).selectOption('')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('reviewer')
  await page.getByLabel('Password').fill('local-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('combobox', { name: 'Assignee (open actions)' }).selectOption('person')
  await expect(page.getByRole('link', { name: 'Case IMPORTED' })).toHaveCount(0)
  await expect(page.getByRole('table').getByText('Actions: 1 open actions')).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Assignee (open actions)' })).toBeDisabled()
  await expect(page.getByRole('option', { name: 'Private assignee' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Case IMPORTED' })).toBeVisible()
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('reviewer')
  await page.getByLabel('Password').fill('local-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('combobox', { name: 'Assignee (open actions)' }).selectOption('person')
  unavailable = true
  await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))
  await expect(page.getByText(/Showing bundled saved demo cases/)).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Assignee (open actions)' })).toHaveValue('')
  await expect(page.getByRole('combobox', { name: 'Assignee (open actions)' })).toBeDisabled()
  await expect(page.getByRole('link', { name: 'Delayed start on sewing line S4', exact: true })).toBeVisible()
})

test('default library search excludes engineering fixtures', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/incidents')) return route.fulfill({ json: { items: [summary('INC-001', 'curated_demo'), summary('FIXTURE-1', 'engineering_fixture')] } })
    if (path.endsWith('/incidents/search')) return route.fulfill({ json: { items: [
      { ...summary('INC-001', 'curated_demo'), match_reason: 'fabric record', differences: [] },
      { ...summary('FIXTURE-1', 'engineering_fixture'), match_reason: 'fabric generated fixture', differences: [] },
    ] } })
    return route.fulfill({ status: 503, json: { message: 'Unavailable' } })
  })
  await page.goto('/')
  await page.getByRole('searchbox', { name: 'Search incident evidence' }).fill('fabric')
  await expect(page.getByRole('link', { name: 'Case INC-001', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Case FIXTURE-1', exact: true })).toHaveCount(0)
  await expect(page.getByText('1 retrieved results matching the current library view and filters.', { exact: false })).toBeVisible()
})
