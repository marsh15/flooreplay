import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import fixture from './fixtures/decisions/lab.json' with { type: 'json' }

test('adoption stays disabled until a complete stored run and each regression acknowledgement exist', async ({
  page,
}) => {
  const adoptRequests: unknown[] = []
  const diffRequests: Record<string, unknown>[] = []
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/policies')) return route.fulfill({ json: fixture.policies })
    if (path.endsWith('/policies/diff')) {
      diffRequests.push(request.postDataJSON())
      return route.fulfill({ json: fixture.diff })
    }
    if (path.endsWith('/regression-runs') && request.method() === 'POST')
      return route.fulfill({ json: fixture.run })
    if (path.endsWith('/regression-runs')) return route.fulfill({ json: { items: [] } })
    if (path.endsWith('/regression-runs/run-candidate-001'))
      return route.fulfill({ json: fixture.run })
    if (path.endsWith('/regression-runs/run-candidate-001/adopt') && request.method() === 'POST') {
      adoptRequests.push(request.postDataJSON())
      return route.fulfill({ status: 200, json: { id: 'adoption-1', adopted_by: 'owner' } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected lab request' } })
  })

  await page.goto('/lab')
  await expect(page.getByRole('heading', { name: 'Replay lab' })).toBeVisible()
  await page.getByLabel('Candidate policy').selectOption('policy-candidate')
  await expect(page.getByText('fabric.safety_floor_pct')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Adopt policy' })).toBeDisabled()

  await page.getByRole('button', { name: 'Run regression' }).click()
  await expect(page.getByText('Earlier fabric shortage')).toBeVisible()
  await expect(page.getByText('Safety margin order', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Adopt policy' })).toBeDisabled()

  await page
    .getByLabel('Acknowledgement for Safety margin order')
    .fill('Reviewed the safety threshold regression with the merchandiser.')
  await expect(page.getByRole('button', { name: 'Adopt policy' })).toBeEnabled()
  await page.getByRole('button', { name: 'Adopt policy' }).click()
  await expect(page.getByText('Policy adopted')).toBeVisible()
  // The run id rides in the path, only the written acknowledgements are sent, and the diff is
  // computed from the two stored policy documents rather than from bare digests.
  expect(adoptRequests).toEqual([
    {
      acknowledgements: {
        'case-regression': 'Reviewed the safety threshold regression with the merchandiser.',
      },
    },
  ])
  expect(diffRequests[0]).toEqual({
    baseline: { label: 'Current policy', engine_version: 'decision-v1' },
    candidate: { label: 'Candidate policy', engine_version: 'decision-v1' },
  })

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations).toEqual([])
})

test('an incomplete regression run cannot enable adoption', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/policies')) return route.fulfill({ json: fixture.policies })
    if (path.endsWith('/policies/diff')) return route.fulfill({ json: fixture.diff })
    if (path.endsWith('/regression-runs') && route.request().method() === 'POST')
      return route.fulfill({ json: { ...fixture.run, complete: false } })
    if (path.endsWith('/regression-runs')) return route.fulfill({ json: { items: [] } })
    if (path.endsWith('/regression-runs/run-candidate-001'))
      return route.fulfill({ json: { ...fixture.run, complete: false } })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected lab request' } })
  })

  await page.goto('/lab')
  await page.getByLabel('Candidate policy').selectOption('policy-candidate')
  await page.getByRole('button', { name: 'Run regression' }).click()
  await expect(page.getByText('Run is incomplete · suite')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Adopt policy' })).toBeDisabled()
})

test('a stored run can be refreshed after completion', async ({ page }) => {
  let reads = 0
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/policies')) return route.fulfill({ json: fixture.policies })
    if (path.endsWith('/policies/diff')) return route.fulfill({ json: fixture.diff })
    if (path.endsWith('/regression-runs') && request.method() === 'POST')
      return route.fulfill({ json: { ...fixture.run, complete: false } })
    if (path.endsWith('/regression-runs')) return route.fulfill({ json: { items: [] } })
    if (path.endsWith('/regression-runs/run-candidate-001')) {
      reads += 1
      return route.fulfill({
        json: reads === 1 ? { ...fixture.run, complete: false } : fixture.run,
      })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected lab request' } })
  })

  await page.goto('/lab')
  await page.getByLabel('Candidate policy').selectOption('policy-candidate')
  await page.getByRole('button', { name: 'Run regression' }).click()
  await expect(page.getByText('Run is incomplete · suite')).toBeVisible()
  await page.getByRole('button', { name: 'Refresh stored run' }).click()
  await expect(page.getByText('Stored regression run refreshed.')).toBeVisible()
  await page.getByLabel('Acknowledgement for Safety margin order').fill('Reviewed this regression.')
  await expect(page.getByRole('button', { name: 'Adopt policy' })).toBeEnabled()
})

for (const mismatch of [
  { name: 'engine version', run: { ...fixture.run, engine_version: 'decision-v0' } },
  {
    name: 'baseline digest',
    run: { ...fixture.run, baseline_policy_digest: 'another-baseline' },
  },
]) {
  test(`a complete run with the wrong ${mismatch.name} cannot enable adoption`, async ({
    page,
  }) => {
    await page.route('**/api/v1/**', (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (path.endsWith('/policies')) return route.fulfill({ json: fixture.policies })
      if (path.endsWith('/policies/diff')) return route.fulfill({ json: fixture.diff })
      if (path.endsWith('/regression-runs') && request.method() === 'POST')
        return route.fulfill({ json: mismatch.run })
      if (path.endsWith('/regression-runs')) return route.fulfill({ json: { items: [] } })
      if (path.endsWith('/regression-runs/run-candidate-001'))
        return route.fulfill({ json: mismatch.run })
      return route.fulfill({ status: 404, json: { detail: 'Unexpected lab request' } })
    })

    await page.goto('/lab')
    await page.getByLabel('Candidate policy').selectOption('policy-candidate')
    await page.getByRole('button', { name: 'Run regression' }).click()
    await expect(page.getByText('Safety margin order', { exact: true })).toBeVisible()
    await page
      .getByLabel('Acknowledgement for Safety margin order')
      .fill('Reviewed this regression.')
    await expect(page.getByRole('button', { name: 'Adopt policy' })).toBeDisabled()
  })
}

test('the lab explains when there is no candidate policy', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/policies'))
      return route.fulfill({
        json: { adopted: 'policy-base', items: [fixture.policies.items[0]] },
      })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected lab request' } })
  })

  await page.goto('/lab')
  await expect(page.getByText('No candidate policy is available.')).toBeVisible()
  await expect(page.getByText('Loading policy changes…')).toHaveCount(0)
})

test('a stored run for the selected candidate loads without running anything', async ({ page }) => {
  let started = 0
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/policies')) return route.fulfill({ json: fixture.policies })
    if (path.endsWith('/policies/diff')) return route.fulfill({ json: fixture.diff })
    if (path.endsWith('/regression-runs') && request.method() === 'POST') {
      started += 1
      return route.fulfill({ status: 401, json: { code: 'SIGN_IN_REQUIRED' } })
    }
    if (path.endsWith('/regression-runs')) {
      expect(new URL(request.url()).searchParams.get('candidate')).toBe('policy-candidate')
      expect(new URL(request.url()).searchParams.get('workspace_id')).toBe('public-demo')
      return route.fulfill({ json: { items: [fixture.run] } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected lab request' } })
  })

  await page.goto('/lab')
  await expect(page.getByText('Showing the public synthetic demo.')).toBeVisible()
  await expect(page.getByText('Earlier fabric shortage')).toBeVisible()
  await expect(page.getByText('Latest stored regression run loaded.')).toBeVisible()
  await page.getByRole('button', { name: 'Run regression' }).click()
  await expect(page.getByText(/needs a signed-in member of a private workspace/)).toBeVisible()
  expect(started).toBe(1)
})
