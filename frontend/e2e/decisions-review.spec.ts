import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import fixture from './fixtures/decisions/review.json' with { type: 'json' }

test('review queue highlights Tamil spans and submits a correction with both value and evidence', async ({
  page,
}) => {
  let resolvedBody: Record<string, unknown> | undefined
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/review-items')) return route.fulfill({ json: fixture })
    if (path.endsWith('/resolve') && request.method() === 'POST') {
      resolvedBody = request.postDataJSON()
      return route.fulfill({ json: { resolved: true } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected review request' } })
  })

  await page.goto('/review')
  await expect(page.getByRole('heading', { name: 'Review queue' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open order POLO-224' })).toHaveCount(2)
  await expect(page.getByRole('link', { name: 'Open order POLO-224' }).first()).toHaveAttribute(
    'href',
    '/orders/POLO-224',
  )
  await expect(page.getByText('L-221 துணியில் துளை இல்லை 🧵; 1200 மீ shade fail.')).toBeVisible()
  await expect(page.getByText('hole illa', { exact: true })).toHaveAttribute(
    'data-highlight',
    'true',
  )
  await expect(page.getByText('shade fail', { exact: true })).toHaveAttribute(
    'data-highlight',
    'true',
  )
  await page.getByLabel('Value for issue in review-tamil-001').fill('defect')
  await page.getByLabel('Evidence for issue in review-tamil-001').fill('1200 மீ')
  await page.getByLabel('Reason for review-tamil-001').fill('QC confirmed the defect quantity.')
  await page.getByRole('button', { name: 'Correct review-tamil-001' }).click()
  await expect
    .poll(() => resolvedBody)
    .toEqual({
      action: 'correct',
      corrected: { issue: { value: 'defect', evidence: '1200 மீ' } },
      reason: 'QC confirmed the defect quantity.',
    })

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations).toEqual([])
})

test('confirm and reject each submit an explicit action and a nonblank reason', async ({
  page,
}) => {
  const resolved: Record<string, unknown>[] = []
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/review-items')) return route.fulfill({ json: fixture })
    if (path.endsWith('/resolve') && request.method() === 'POST') {
      resolved.push(request.postDataJSON())
      return route.fulfill({ json: { resolved: true } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected review request' } })
  })

  await page.goto('/review')
  const confirmReason = page.getByLabel('Reason for review-tanglish-002')
  const confirmButton = page.getByRole('button', { name: 'Confirm review-tanglish-002' })
  await expect(confirmButton).toBeDisabled()
  await confirmReason.fill('QC reviewed the source note.')
  await expect(confirmButton).toBeEnabled()
  await confirmButton.click()
  await expect
    .poll(() => resolved[0])
    .toEqual({ action: 'confirm', reason: 'QC reviewed the source note.' })

  await page
    .getByLabel('Reason for review-english-003')
    .fill('A supervisor verified the clean lot.')
  await page.getByRole('button', { name: 'Reject review-english-003' }).click()
  await expect
    .poll(() => resolved[1])
    .toEqual({
      action: 'reject',
      reason: 'A supervisor verified the clean lot.',
    })
})

test('a correction can clear a false-positive field with null value and evidence', async ({
  page,
}) => {
  let corrected: Record<string, unknown> | undefined
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/review-items')) return route.fulfill({ json: fixture })
    if (path.endsWith('/resolve') && request.method() === 'POST') {
      corrected = request.postDataJSON()
      return route.fulfill({ json: { resolved: true } })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected review request' } })
  })

  await page.goto('/review')
  await page.getByLabel('Value for issue in review-english-003').fill('')
  await page.getByLabel('Evidence for issue in review-english-003').fill('')
  await page
    .getByLabel('Reason for review-english-003')
    .fill('The note states the lot had no holes.')
  await page.getByRole('button', { name: 'Correct review-english-003' }).click()
  await expect
    .poll(() => corrected)
    .toEqual({
      action: 'correct',
      corrected: { issue: { value: null, evidence: null } },
      reason: 'The note states the lot had no holes.',
    })
})

test('private review rows disappear on sign out even when the queue remains mounted', async ({
  page,
}) => {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    const owner = route.request().headers().authorization === 'Bearer synthetic-owner'
    if (path.endsWith('/auth/login'))
      return route.fulfill({
        json: {
          token: 'synthetic-owner',
          user: { id: 'owner', username: 'owner', display_name: 'Owner', role: 'owner' },
        },
      })
    if (path.endsWith('/auth/logout')) return route.fulfill({ json: { logged_out: true } })
    if (path.endsWith('/review-items'))
      return route.fulfill({ json: owner ? fixture : { items: [] } })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected private queue request' } })
  })

  await page.goto('/review')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill('synthetic-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText('L-221 துணியில் துளை இல்லை 🧵; 1200 மீ shade fail.')).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByText('L-221 துணியில் துளை இல்லை 🧵; 1200 மீ shade fail.')).toHaveCount(0)
  await expect(page.getByText('No items need review')).toBeVisible()
})
