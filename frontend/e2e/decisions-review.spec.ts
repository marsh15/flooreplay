import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import fixture from './fixtures/decisions/review.json' with { type: 'json' }

type Posted = { path: string; body: Record<string, unknown> }

/** Serves the review queue the way the backend does: one item per flagged field. */
async function mockReviewApi(page: Page, posted: Posted[] = []) {
  await page.route('**/api/v1/**', (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (path.endsWith('/review-items')) {
      expect(url.searchParams.get('workspace_id')).toBeTruthy()
      return route.fulfill({ json: fixture })
    }
    if (
      /\/review-items\/[^/]+\/(confirm|correct|reject)$/.test(path) &&
      request.method() === 'POST'
    ) {
      posted.push({ path: path.split('/review-items/')[1], body: request.postDataJSON() })
      return route.fulfill({ json: fixture.items[0] })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected review request' } })
  })
}

test('review items group per source, quote Tamil evidence and hide resolved items', async ({
  page,
}) => {
  await mockReviewApi(page)
  await page.goto('/review')
  await expect(page.getByRole('heading', { name: 'Review queue' })).toBeVisible()
  // Three pending sources; the confirmed item is not shown.
  await expect(page.getByRole('article')).toHaveCount(3)
  await expect(page.getByRole('link', { name: 'Open order POLO-224' })).toHaveAttribute(
    'href',
    '/orders/POLO-224',
  )
  await expect(page.getByText('துளை இல்லை', { exact: true })).toBeVisible()
  await expect(page.getByText('(characters 12–22)')).toBeVisible()
  await expect(page.getByText('hole illa', { exact: true })).toBeVisible()
  await expect(page.getByText('no holes')).toHaveCount(0)
  await expect(page.getByText('Assigned to: reviewer-1')).toBeVisible()

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations).toEqual([])
})

test('a correction is sent once per changed field with the reviewer note', async ({ page }) => {
  const posted: Posted[] = []
  await mockReviewApi(page, posted)
  await page.goto('/review')
  await page.getByLabel('Value for issue in ext-tamil').fill('shade_fail')
  await page.getByLabel('Reason for ext-tamil').fill('QC confirmed the shade failure.')
  await page.getByRole('button', { name: 'Correct ext-tamil' }).click()
  await expect
    .poll(() => posted)
    .toEqual([
      {
        path: 'item-issue/correct',
        body: { note: 'QC confirmed the shade failure.', value: 'shade_fail' },
      },
    ])
})

test('confirm and reject apply to every flagged field and need a nonblank reason', async ({
  page,
}) => {
  const posted: Posted[] = []
  await mockReviewApi(page, posted)
  await page.goto('/review')
  const confirmButton = page.getByRole('button', { name: 'Confirm ext-tamil' })
  await expect(confirmButton).toBeDisabled()
  await page.getByLabel('Reason for ext-tamil').fill('QC reviewed the source note.')
  await expect(confirmButton).toBeEnabled()
  await confirmButton.click()
  await expect
    .poll(() => posted)
    .toEqual([
      { path: 'item-lot/confirm', body: { note: 'QC reviewed the source note.', value: 'L-221' } },
      {
        path: 'item-issue/confirm',
        body: { note: 'QC reviewed the source note.', value: 'defect' },
      },
    ])

  await page.getByLabel('Reason for ext-tanglish').fill('A supervisor verified the clean lot.')
  await page.getByRole('button', { name: 'Reject ext-tanglish' }).click()
  await expect
    .poll(() => posted.at(-1))
    .toEqual({
      path: 'item-tanglish/reject',
      body: { note: 'A supervisor verified the clean lot.' },
    })
})

test('a correction can clear a false-positive field', async ({ page }) => {
  const posted: Posted[] = []
  await mockReviewApi(page, posted)
  await page.goto('/review')
  await page.getByLabel('Value for issue in ext-tanglish').fill('')
  await page.getByLabel('Evidence for issue in ext-tanglish').fill('')
  await page.getByLabel('Reason for ext-tanglish').fill('The note says there was no hole.')
  await page.getByRole('button', { name: 'Correct ext-tanglish' }).click()
  await expect
    .poll(() => posted)
    .toEqual([
      {
        path: 'item-tanglish/correct',
        body: { note: 'The note says there was no hole.', value: null },
      },
    ])
})

test('signed-out visitors are told to sign in instead of seeing an empty queue', async ({
  page,
}) => {
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ status: 401, json: { code: 'SIGN_IN_REQUIRED', message: 'Sign in' } }),
  )
  await page.goto('/review')
  await expect(page.getByText(/Sign in to see the review queue/)).toBeVisible()
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
    if (path.endsWith('/workspaces')) return route.fulfill({ json: { items: [] } })
    if (path.endsWith('/review-items'))
      return route.fulfill({ json: owner ? fixture : { items: [] } })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected private queue request' } })
  })

  await page.goto('/review')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Username').fill('owner')
  await page.getByLabel('Password').fill('synthetic-password')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByText('துளை இல்லை', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByText('துளை இல்லை', { exact: true })).toHaveCount(0)
  await expect(page.getByText('No items need review')).toBeVisible()
})
