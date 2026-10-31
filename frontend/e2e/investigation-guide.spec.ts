import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import heroReport from '../src/data/hero-report.json' with { type: 'json' }
import heroRevision from '../src/data/hero-revision.json' with { type: 'json' }

// Mocked only: the saved INC-001 fixtures stand in for the API, so no backend is needed.
async function mockLiveAnalysis(page: Page) {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/capabilities'))
      return route.fulfill({
        json: {
          mode: 'live',
          imports_enabled: false,
          reviews_enabled: true,
          export_enabled: true,
          ai: { generation_available: false, index_ready: false, reason: 'disabled' },
        },
      })
    if (path.endsWith('/analyses')) {
      const revision = route.request().postDataJSON().revision
      return route.fulfill({
        json: {
          ...heroReport,
          id: `guide-${revision}`,
          revision,
          execution_kind: 'live_deterministic',
        },
      })
    }
    if (path.includes('/revisions/') && !path.endsWith('/source-health'))
      return route.fulfill({
        json: { ...heroRevision, revision: path.endsWith('/1') ? 1 : 2 },
      })
    return route.fulfill({ status: 503, json: { message: 'Unavailable in guide test' } })
  })
}

test.describe('saved offline report', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/**', (route) => route.abort())
  })

  test('guide shows each step with its saved status and a link to its section', async ({
    page,
  }) => {
    await page.goto('/incidents/INC-001')
    const guide = page.getByRole('complementary', { name: 'Investigation guide' })
    await expect(guide.getByRole('heading', { name: 'Follow the investigation' })).toBeVisible()
    await expect(guide.getByRole('listitem')).toHaveCount(5)
    await expect(guide.getByText(/Saved report for revision 2/)).toBeVisible()
    await expect(guide.getByText('Shortfall 74 good units · coverage complete')).toBeVisible()
    await expect(guide.getByText('Needs the live API', { exact: true })).toBeVisible()
    await expect(
      guide.getByText('PDF available · JSON needs sign-in', { exact: true }),
    ).toBeVisible()
    await expect(page.locator('#compare-revisions')).toBeHidden()

    const links: [string, string][] = [
      ['1. Measure the difference', '#observed-situation'],
      ['2. Check sources and missing evidence', '#source-health'],
      ['Evidence timeline', '#evidence-timeline'],
      ['3. Check findings', '#explanations-and-open-questions'],
      ['Review proposals', '#recovery-options'],
      ['Assigned checks', '#assigned-checks'],
      ['5. Export the report', '#shift-update'],
    ]
    for (const [name, href] of links)
      await expect(guide.getByRole('link', { name, exact: true })).toHaveAttribute('href', href)
  })

  test('keyboard activation moves to the named section', async ({ page }) => {
    await page.goto('/incidents/INC-001')
    const guide = page.getByRole('complementary', { name: 'Investigation guide' })
    const sourceLink = guide.getByRole('link', {
      name: '2. Check sources and missing evidence',
      exact: true,
    })
    await sourceLink.focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/#source-health$/)
    await expect(page.locator('#source-health')).toBeInViewport()
  })

  test('guide has no detectable accessibility violations', async ({ page }) => {
    await page.goto('/incidents/INC-001')
    await expect(page.getByRole('complementary', { name: 'Investigation guide' })).toBeVisible()
    const results = await new AxeBuilder({ page })
      .include('[aria-label="Investigation guide"]')
      .analyze()
    expect(results.violations.map((violation) => violation.id)).toEqual([])
  })
})

test.describe('saved offline report on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/**', (route) => route.abort())
  })

  test('step links are touch-sized and the page does not scroll sideways', async ({ page }) => {
    await page.goto('/incidents/INC-001')
    const guide = page.getByRole('complementary', { name: 'Investigation guide' })
    await expect(guide).toBeVisible()
    for (const link of await guide.getByRole('link').all()) {
      const box = await link.boundingBox()
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  })
})

test('live report with an earlier revision enables comparison and export', async ({ page }) => {
  await mockLiveAnalysis(page)
  await page.goto('/incidents/INC-001')
  const guide = page.getByRole('complementary', { name: 'Investigation guide' })
  await expect(guide.getByText(/Pinned report guide-2 for revision 2, the latest/)).toBeVisible()
  await expect(guide.getByText('Compare with revision 1', { exact: true })).toBeVisible()
  await expect(guide.getByText('Portable export ready', { exact: true })).toBeVisible()
  await expect(page.locator('#compare-revisions')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Export portable report' })).toBeEnabled()

  await guide.getByRole('link', { name: '4. Compare revisions', exact: true }).click()
  await expect(page).toHaveURL(/#compare-revisions$/)
  await expect(page.getByRole('button', { name: 'Compare revisions', exact: true })).toBeVisible()
})

test('earlier evidence revision is labelled as historical, not the latest state', async ({
  page,
}) => {
  await mockLiveAnalysis(page)
  await page.goto('/incidents/INC-001?revision=1')
  const guide = page.getByRole('complementary', { name: 'Investigation guide' })
  await expect(
    guide.getByText(
      'You are reading revision 1; the latest is revision 2. Assigned checks and the shift handover show the latest incident state.',
    ),
  ).toBeVisible()
  await expect(guide.getByText('No earlier revision', { exact: true })).toBeVisible()
  await expect(page.locator('#compare-revisions')).toBeHidden()
})
