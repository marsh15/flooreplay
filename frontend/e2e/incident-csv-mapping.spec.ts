import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

async function signIn(page: Page) {
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill('test-local-only')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible()
}
const source = '\uFEFFRow,Text,Replaces\r\nnote-1,"line one\nline two",\r\n'
async function setup(page: Page) {
  const requests: { path: string; body: Record<string, unknown> }[] = []
  let inspections = 0
  let failPublish = true
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    if (path === '/auth/login') return route.fulfill({ json: { token: 'local-only', user: { id: 'owner', display_name: 'Owner', username: 'owner', role: 'owner' } } })
    if (path === '/auth/logout') return route.fulfill({ json: { ok: true } })
    if (path === '/workspaces') return route.fulfill({ json: { items: [{ id: 'private-csv', name: 'CSV workspace', visibility: 'private', role: 'owner' }] } })
    if (path === '/capabilities') return route.fulfill({ json: { imports_enabled: true } })
    if (path === '/incidents') return route.fulfill({ json: { items: [{ id: 'CSV-TEST', workspace_id: 'private-csv', title: 'CSV mapping example', revision: 1, cutoff: '2026-09-28T09:15:00+05:30' }] } })
    if (path === '/incidents/CSV-TEST/revisions/1') return route.fulfill({ json: { id: 'CSV-TEST', scope: { factory: 'Factory', line_id: 'S2', order_id: 'ORD', style_id: 'STYLE', stage: 'sewing', unit: 'good_units' } } })
    if (path.startsWith('/incidents/imports/')) {
      const body: Record<string, unknown> = route.request().postDataJSON()
      requests.push({ path, body })
      if (path.endsWith('/inspect')) {
        inspections++
        return route.fulfill({ json: { headers: ['Row', 'Text', 'Replaces'], sample_rows: [{ Row: 'note-1', Text: 'line one\nline two', Replaces: '' }], row_count: 1, fields: [{ name: 'id', required: true, description: 'Original source record identifier.' }, { name: 'summary', required: true, description: 'Source text as recorded.' }, { name: 'supersedes_id', required: false, description: 'A replaced source record.' }] } })
      }
      if (path.endsWith('/preview')) return route.fulfill({ json: { status: 'READY', profile: 'operations-v1', source_system: 'shift-log', timezone: 'Asia/Kolkata', filename: body.filename, raw_digest: 'raw-source-digest', preview_digest: 'mapped-preview-digest', row_count: 1, issues: [], plan_buckets: [], output_buckets: [], events: [{ id: 'note-1', summary: 'line one\nline two' }] } })
      if (path.endsWith('/publish')) {
        if (failPublish) { failPublish = false; return route.abort('failed') }
        return route.fulfill({ json: { id: 'CSV-TEST', revision: 2 } })
      }
    }
    return route.fulfill({ status: 503, json: { message: 'Unsupported fixture endpoint' } })
  })
  return { requests, inspections: () => inspections }
}

async function inspectAndMap(page: Page) {
  await page.getByLabel('Incident', { exact: true }).selectOption('CSV-TEST')
  await page.getByLabel('Local file').setInputFiles({ name: 'unfamiliar.csv', mimeType: 'text/csv', buffer: Buffer.from(source) })
  await expect(page.getByRole('button', { name: 'Preview source', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Inspect CSV columns', exact: true }).click()
  await expect(page.getByRole('table', { name: /Original CSV sample/ })).toContainText('line one\nline two')
  await expect(page.getByRole('combobox', { name: 'Map id (required)', exact: true })).toHaveValue('unmapped')
  await page.getByRole('combobox', { name: 'Map id (required)', exact: true }).selectOption({ label: 'Row' })
  await page.getByRole('combobox', { name: 'Map summary (required)', exact: true }).selectOption({ label: 'Text' })
}

test('explicit mapping preserves BOM and quoted multiline source; retry publishes identical mapping and key', async ({ page }) => {
  const fixture = await setup(page)
  await page.goto('/incidents/imports')
  expect(fixture.inspections()).toBe(0)
  await signIn(page)
  await inspectAndMap(page)
  await expect(page.getByText(/Ignored source columns: Replaces/)).toBeVisible()
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
  const preview = page.getByRole('region', { name: 'Import preview' })
  await expect(preview.getByRole('heading', { name: 'Preview: READY' })).toBeVisible()
  await expect(preview.getByRole('heading', { name: /Normalized operational evidence/ })).toBeVisible()
  await preview.getByRole('button', { name: 'Publish new revision', exact: true }).click()
  await expect(preview.getByRole('button', { name: 'Retry same publication', exact: true })).toBeVisible()
  await preview.getByRole('button', { name: 'Retry same publication', exact: true }).click()
  await expect(preview.getByText(/Revision 2 published/)).toBeVisible()
  const inspected = fixture.requests.find((entry) => entry.path.endsWith('/inspect'))
  expect(inspected?.body.raw_text).toBe(source)
  const previewed = fixture.requests.find((entry) => entry.path.endsWith('/preview'))
  expect(previewed?.body).toMatchObject({ raw_text: source, column_mapping: { id: 'Row', summary: 'Text' }, field_defaults: {} })
  const published = fixture.requests.filter((entry) => entry.path.endsWith('/publish'))
  expect(published).toHaveLength(2)
  expect(published[0]?.body).toEqual(published[1]?.body)
})

test('mapping or context edits invalidate previews; profile/file changes clear inspection; sign-out removes private source state', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await setup(page)
  await page.goto('/incidents/imports')
  await signIn(page)
  await inspectAndMap(page)
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Import preview' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Map summary (required)', exact: true }).selectOption('constant')
  await expect(page.getByRole('region', { name: 'Import preview' })).toHaveCount(0)
  await page.getByLabel('Constant for summary').fill('Explicit supervisor observation')
  await page.getByRole('button', { name: 'Preview source', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Import preview' })).toBeVisible()
  await page.getByLabel('Source system').fill('updated-shift-log')
  await expect(page.getByRole('region', { name: 'Import preview' })).toHaveCount(0)
  await page.getByLabel('Source profile').selectOption('notes-v1')
  await expect(page.getByRole('heading', { name: 'Match CSV columns' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Preview source', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Inspect CSV columns', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Match CSV columns' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Match CSV columns' })).toHaveCount(0)
  await expect(page.getByText(/Sign in with an owner account/)).toBeVisible()
  await signIn(page)
  await expect(page.getByLabel('Local file')).toHaveValue('')
  await expect(page.getByRole('region', { name: 'Import preview' })).toHaveCount(0)
})
