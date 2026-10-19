import { expect, test, type Page } from '@playwright/test'
import type { NoteParseResult } from '../src/lib/api'

async function fixture(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    if (path === '/auth/login') {
      const { username } = route.request().postDataJSON()
      return route.fulfill({
        json: {
          token: username,
          user: { id: username, username, display_name: username, role: 'owner' },
        },
      })
    }
    if (path === '/capabilities')
      return route.fulfill({
        json: {
          mode: 'local',
          imports_enabled: true,
          configurations: [],
          ai: { generation_available: false },
        },
      })
    if (path === '/auth/logout') return route.fulfill({ json: { signed_out: true } })
    if (path === '/usage')
      return route.fulfill({
        json: {
          available_inr: 500,
          committed_inr: 0,
          total_ceiling_inr: 500,
          active_operations: 0,
          purpose_available_inr: {},
          entries: [],
        },
      })
    return route.fulfill({ json: { items: [] } })
  })
}

async function login(page: Page, username: string) {
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill('dummy-regression-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible()
}

test('logout clears operational notes before another owner signs in', async ({ page }) => {
  await fixture(page)
  await page.goto('/coverage/notes')
  await login(page, 'alice')
  const privateNote = 'Private operational note from Alice'
  await page.locator('textarea').fill(privateNote)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.locator('textarea')).not.toHaveValue(privateNote)
  await login(page, 'bob')
  await expect(page.locator('textarea')).not.toHaveValue(privateNote)
})

test('unrecognized and invalid revision links have recovery paths', async ({ page }) => {
  await fixture(page)
  await page.goto('/missing-page')
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open the incident library' })).toHaveAttribute(
    'href',
    '/',
  )
  for (const revision of ['0', '1.5', 'NaN']) {
    await page.goto(`/incidents/INC-001?revision=${revision}`)
    await expect(page.getByRole('heading', { name: 'Invalid evidence revision' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Open latest investigation' })).toBeVisible()
  }
})

test('editing a note during extraction leaves the returned draft stale', async ({ page }) => {
  await fixture(page)
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const draft: NoteParseResult = {
    parser_call_id: 'dummy-parser',
    parser_kind: 'rule-baseline',
    live: false,
    draft: {
      event_category: 'OPERATOR_UNAVAILABLE',
      subject_mentions: ['O117'],
      operation_mentions: [],
      polarity: 'positive',
      uncertainty_phrase: null,
      raw_temporal_expressions: [],
      ambiguity_notes: [],
    },
    resolution: {
      operators: [{ raw: 'O117', resolved_id: 'O117', status: 'RESOLVED', candidates: ['O117'] }],
      operations: [],
    },
  }
  await page.route('**/api/v1/notes/parse', async (route) => {
    await gate
    await route.fulfill({ json: draft })
  })
  await page.goto('/coverage/notes')
  await login(page, 'alice')
  const original = 'O117 is unavailable for the morning shift.'
  await page.locator('textarea').fill(original)
  const requested = page.waitForRequest('**/api/v1/notes/parse')
  await page.getByRole('button', { name: 'Extract draft', exact: true }).click()
  await requested
  await page.locator('textarea').fill('O219 is unavailable instead.')
  release()
  await expect(page.getByText(/the draft below is stale/)).toBeVisible()
  await expect(page.getByLabel('Summary', { exact: true })).toHaveValue(original)
})
