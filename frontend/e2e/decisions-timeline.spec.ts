import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import decision from './fixtures/decisions/ready-decision.json' with { type: 'json' }
import timeline from './fixtures/decisions/timeline.json' with { type: 'json' }

test('knowledge scrubber uses IST, updates the exact cutoff and supports keyboard endpoints', async ({
  page,
}) => {
  const policies: string[] = []
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api/v1/decisions', '')
    if (path === '/orders/POLO-221/timeline') return route.fulfill({ json: timeline })
    if (path === '/orders/POLO-221') {
      const policy = url.searchParams.get('policy')
      if (policy) policies.push(policy)
      return route.fulfill({
        json: { ...decision, cutoff: url.searchParams.get('cutoff') ?? decision.cutoff },
      })
    }
    return route.fulfill({ status: 503, json: { message: 'Unavailable in timeline test' } })
  })

  await page.goto(
    '/orders/POLO-221/timeline?cutoff=2026-10-22T04%3A06%3A00Z&policy=policy-candidate',
  )
  await expect(page.getByRole('heading', { name: /Timeline.*POLO-221/ })).toBeVisible()
  const scrubber = page.getByRole('slider', { name: 'Knowledge-time cutoff' })
  await expect(scrubber).toHaveValue('2')
  await expect.poll(() => policies).toContain('policy-candidate')
  await expect(page.getByText(/22 Oct, 09:36 IST/).first()).toBeVisible()
  await scrubber.focus()
  await page.keyboard.press('End')
  await expect(scrubber).toHaveValue('3')
  await expect(page).toHaveURL(/cutoff=2026-10-22T04%3A07%3A00Z.*policy=policy-candidate/)
  await page.keyboard.press('Home')
  await expect(scrubber).toHaveValue('0')
  await page.keyboard.press('ArrowRight')
  await expect(scrubber).toHaveValue('1')
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations).toEqual([])
})
