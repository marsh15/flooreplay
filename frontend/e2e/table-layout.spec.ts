import { expect, test } from '@playwright/test'

const description = 'Catches overlap-blind proposals and eligibility regressions in the improved policy. The same evidence must always propose the same eligible operator. Source: ' + 'source-record-'.repeat(16)

for (const width of [1440, 1024, 390]) {
  test(`coverage table keeps long text inside its columns at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.route('**/api/v1/**', (route) => {
      if (new URL(route.request().url()).pathname.endsWith('/scenarios')) {
        return route.fulfill({ json: {
          items: [{ scenario_id: 'SCEN-WRAPPING', revision: 1, title: 'Long scenario title with stale evidence and an overlapping operator assignment', tags: ['evidence-freshness'], defect_statement: description, decision_at: '2026-09-22T02:28:00+00:00' }],
          latest_attempts: [],
        } })
      }
      return route.fulfill({ status: 503, json: { message: 'Unavailable' } })
    })
    await page.goto('/coverage')
    const table = page.getByRole('table', { name: 'Coverage scenarios' })
    await expect(table.getByText(description, { exact: true })).toBeVisible()
    await page.evaluate(() => document.fonts.ready)
    const overflowingText = await table.locator('th, td').evaluateAll((cells) => cells.flatMap((cell) => {
      const bounds = cell.getBoundingClientRect()
      const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT)
      const failures: string[] = []
      while (walker.nextNode()) {
        const node = walker.currentNode
        if (!node.textContent?.trim()) continue
        const range = document.createRange()
        range.selectNodeContents(node)
        if (Array.from(range.getClientRects()).some((rect) => rect.right > bounds.right + 1 || rect.left < bounds.left - 1)) failures.push(node.textContent)
      }
      return failures
    }))
    expect(overflowingText).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await expect(table.getByText('Not run in this database yet')).toBeVisible()
  })
}
