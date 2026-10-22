import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import fixture from './fixtures/decisions/lab.json' with { type: 'json' }

test('adoption stays disabled until a complete stored run and each regression acknowledgement exist', async ({
  page,
}) => {
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/policies')) return route.fulfill({ json: fixture.policies })
    if (path.endsWith('/policies/diff')) return route.fulfill({ json: fixture.diff })
    if (path.endsWith('/regression-runs') && request.method() === 'POST')
      return route.fulfill({ json: fixture.run })
    if (path.endsWith('/regression-runs/run-candidate-001'))
      return route.fulfill({ json: fixture.run })
    if (path.endsWith('/adopt') && request.method() === 'POST')
      return route.fulfill({ status: 200, json: { adopted: true } })
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
  { name: 'baseline digest', run: { ...fixture.run, baseline_digest: 'another-baseline' } },
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
        json: { adopted: 'policy-base', policies: [fixture.policies.policies[0]] },
      })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected lab request' } })
  })

  await page.goto('/lab')
  await expect(page.getByText('No candidate policy is available.')).toBeVisible()
  await expect(page.getByText('Loading policy changes…')).toHaveCount(0)
})
