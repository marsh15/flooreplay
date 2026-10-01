import { expect, test } from '@playwright/test'
import heroReport from '../src/data/hero-report.json' with { type: 'json' }
import heroRevision from '../src/data/hero-revision.json' with { type: 'json' }
import library from '../src/data/incident-library.json' with { type: 'json' }

for (const destination of ['library', 'earlier revision']) {
  test(`late analysis cannot undo navigation to ${destination}`, async ({ page }) => {
    let release = () => {}
    const gate = new Promise<void>((resolve) => { release = resolve })
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/incidents')) return route.fulfill({ json: library })
      if (path.includes('/revisions/')) return route.fulfill({ json: { ...heroRevision, revision: path.endsWith('/1') ? 1 : 2 } })
      if (path.endsWith('/incidents/INC-001/analyses')) {
        const revision = route.request().postDataJSON().revision
        if (revision === 2) await gate
        return route.fulfill({ json: { ...heroReport, id: `navigation-${revision}`, revision, execution_kind: 'live_deterministic' } })
      }
      if (path.includes('/analyses/navigation-')) {
        const revision = path.endsWith('-1') ? 1 : 2
        return route.fulfill({ json: { ...heroReport, id: `navigation-${revision}`, revision, execution_kind: 'live_deterministic' } })
      }
      return route.fulfill({ status: 503, json: { message: 'Unavailable in navigation test' } })
    })
    await page.goto('/incidents/INC-001?revision=2')
    await expect(page.getByLabel('Building analysis')).toBeVisible()
    if (destination === 'library') await page.getByRole('link', { name: 'Incident library', exact: true }).click()
    else await page.getByRole('combobox', { name: 'Evidence revision' }).selectOption('1')
    const completed = page.waitForResponse((response) => response.url().endsWith('/incidents/INC-001/analyses') && response.request().postDataJSON().revision === 2)
    release()
    await completed
    if (destination === 'library') {
      await expect(page).toHaveURL('/')
      await expect(page.getByRole('heading', { name: 'Incident library', exact: true })).toBeVisible()
    } else {
      await expect(page).toHaveURL(/revision=1&analysis=navigation-1/)
      await expect(page.getByRole('combobox', { name: 'Evidence revision' })).toHaveValue('1')
    }
  })
}
