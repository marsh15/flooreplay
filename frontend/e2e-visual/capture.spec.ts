import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const outDir = process.env.VISUAL_DIR ?? 'test-results/visual'
const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]
const routes = [
  { name: 'library', path: '/' },
  { name: 'incident', path: '/incidents/INC-001' },
  { name: 'demo', path: '/demo' },
  { name: 'imports', path: '/incidents/imports' },
  { name: 'evaluation', path: '/evaluation' },
  { name: 'workspaces', path: '/workspaces' },
  { name: 'operations', path: '/operations' },
  { name: 'archive', path: '/coverage' },
  { name: 'not-found', path: '/no-such-page' },
]

mkdirSync(outDir, { recursive: true })
const axeSummary: Record<string, { id: string; impact: string | null; nodes: number }[]> = {}

for (const viewport of viewports) {
  for (const route of routes) {
    test(`${route.name} @ ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.route('**/api/v1/**', (r) => r.abort())
      await page.goto(route.path)
      await page.waitForLoadState('networkidle')
      await page.addStyleTag({
        content: '*,*::before,*::after{animation:none!important;transition:none!important}',
      })
      await page.screenshot({
        path: path.join(outDir, `${route.name}-${viewport.name}.png`),
        fullPage: true,
      })
      const results = await new AxeBuilder({ page }).analyze()
      axeSummary[`${route.name}@${viewport.name}`] = results.violations.map((v) => ({
        id: v.id,
        impact: v.impact ?? null,
        nodes: v.nodes.length,
      }))
      expect(results).toBeDefined()
    })
  }
}

test.afterAll(() => {
  writeFileSync(path.join(outDir, 'axe-summary.json'), JSON.stringify(axeSummary, null, 2))
})
