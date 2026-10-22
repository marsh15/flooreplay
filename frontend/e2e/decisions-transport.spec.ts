import { expect, test } from '@playwright/test'

test('shared transport lets the browser encode multipart uploads and keeps JSON requests', async ({
  page,
}) => {
  const captured: { contentType: string; body: string }[] = []
  await page.route('**/api/v1/**', (route) => {
    if (new URL(route.request().url()).pathname.endsWith('/decisions/imports/preview')) {
      captured.push({
        contentType: route.request().headers()['content-type'] ?? '',
        body: route.request().postDataBuffer()?.toString() ?? '',
      })
      return route.fulfill({ json: { status: 'READY' } })
    }
    return route.fulfill({ status: 503, json: { message: 'Unavailable in transport test' } })
  })
  await page.goto('/demo')
  await page.evaluate(async () => {
    const modulePath = '/src/lib/http.ts'
    const { apiRequest } = await import(modulePath)
    const body = new FormData()
    body.append('file', new File(['lot_id\nL-221\n'], 'stock.csv', { type: 'text/csv' }))
    body.append('profile', 'erp-fabric-stock')
    await apiRequest('/decisions/imports/preview', { method: 'POST', body })
    await apiRequest('/decisions/imports/preview', {
      method: 'POST',
      body: JSON.stringify({ preview_digest: 'synthetic-preview' }),
    })
  })
  expect(captured).toHaveLength(2)
  expect(captured[0].contentType).toMatch(/^multipart\/form-data; boundary=/)
  expect(captured[0].body).toContain('filename="stock.csv"')
  expect(captured[0].body).toContain('erp-fabric-stock')
  expect(captured[1].contentType).toBe('application/json')
  expect(JSON.parse(captured[1].body)).toEqual({ preview_digest: 'synthetic-preview' })
})

for (const status of [200, 204]) {
  test(`bodyless decision actions accept an empty ${status} response`, async ({ page }) => {
    await page.route('**/api/v1/**', (route) => {
      if (new URL(route.request().url()).pathname.endsWith('/decisions/policies/synthetic/adopt'))
        return route.fulfill({ status, body: '' })
      return route.fulfill({ status: 503, json: { message: 'Unavailable in transport test' } })
    })
    await page.goto('/demo')
    const result = await page.evaluate(async () => {
      const modulePath = '/src/lib/http.ts'
      const { apiNoContent } = await import(modulePath)
      await apiNoContent('/decisions/policies/synthetic/adopt', {
        method: 'POST',
        body: JSON.stringify({ run_id: 'synthetic', acknowledgements: {} }),
      })
      return 'completed'
    })
    expect(result).toBe('completed')
  })
}
