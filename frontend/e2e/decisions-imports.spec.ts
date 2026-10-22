import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import fixture from './fixtures/decisions/imports.json' with { type: 'json' }

const erpCsv = 'lot_id,fabric_quality,colour,"Stock, metres",unused\nL-221,SJ180,NAVY,4000,x\n'

async function fillErpForm(
  page: import('@playwright/test').Page,
  csv = erpCsv,
  quantityHeader = 'Stock, metres',
) {
  await page.getByLabel('Source profile').selectOption('erp-fabric-stock')
  await page.getByLabel('CSV file').setInputFiles({
    name: 'fabric-stock.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csv),
  })
  await page.getByLabel('As of (IST)').fill('2026-10-22T10:00')
  await page.getByLabel('Lot ID column', { exact: true }).selectOption('lot_id')
  await page.getByLabel('Fabric quality column', { exact: true }).selectOption('fabric_quality')
  await page.getByLabel('Colour column', { exact: true }).selectOption('colour')
  await page.getByLabel('Quantity column', { exact: true }).selectOption(quantityHeader)
  await page.getByLabel('Quantity unit').selectOption('m')
  await page.getByLabel('Covered fabric qualities').fill('SJ180')
}

function multipartField(body: string, name: string) {
  const marker = `name="${name}"\r\n`
  const markerAt = body.indexOf(marker)
  if (markerAt < 0) return undefined
  const start = body.indexOf('\r\n\r\n', markerAt)
  if (start < 0) return undefined
  const end = body.indexOf('\r\n--', start + 4)
  return end < 0 ? undefined : body.slice(start + 4, end)
}

test('imports send explicit multipart fields and mapping edits invalidate the preview', async ({
  page,
}) => {
  const previewRequests: { contentType: string; body: string }[] = []
  const publishRequests: Record<string, unknown>[] = []
  let failFirstPublish = true
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/imports/preview') && request.method() === 'POST') {
      const body = request.postDataBuffer()?.toString('utf8') ?? ''
      previewRequests.push({
        contentType: request.headers()['content-type'] ?? '',
        body,
      })
      return route.fulfill({ json: fixture.ready_preview })
    }
    if (path.endsWith('/imports/publish') && request.method() === 'POST') {
      publishRequests.push(request.postDataJSON())
      if (failFirstPublish) {
        failFirstPublish = false
        return route.fulfill({ status: 503, json: { detail: 'Temporary publish failure' } })
      }
      return route.fulfill({ json: fixture.published })
    }
    return route.fulfill({ status: 404, json: { detail: 'Unexpected imports request' } })
  })

  await page.goto('/imports')
  await expect(page.getByRole('heading', { name: 'Decision imports' })).toBeVisible()
  await fillErpForm(page)
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText('READY', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Publish import' })).toBeEnabled()
  expect(previewRequests).toHaveLength(1)
  expect(previewRequests[0].contentType).toMatch(/^multipart\/form-data;\s*boundary=/i)
  expect(previewRequests[0].body).toContain('name="file"')
  expect(previewRequests[0].body).toContain('fabric-stock.csv')
  expect(previewRequests[0].body).toContain('name="profile"')
  expect(previewRequests[0].body).toContain('erp-fabric-stock')
  expect(previewRequests[0].body).toContain('name="as_of"')
  expect(previewRequests[0].body).toContain('2026-10-22T04:30:00')
  expect(previewRequests[0].body).toContain('name="column_mapping"')
  expect(JSON.parse(multipartField(previewRequests[0].body, 'column_mapping') ?? '{}')).toEqual({
    lot_id: 'lot_id',
    fabric_quality: 'fabric_quality',
    colour: 'colour',
    qty: 'Stock, metres',
  })
  expect(JSON.parse(multipartField(previewRequests[0].body, 'units') ?? '{}')).toEqual({
    qty: 'm',
    allocation_qty: 'm',
  })

  await page.getByLabel(/GSM column/).selectOption('unused')
  await expect(page.getByRole('button', { name: 'Publish import' })).toBeDisabled()
  await page.getByLabel(/GSM column/).selectOption('')
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByRole('button', { name: 'Publish import' })).toBeEnabled()
  await page.getByRole('button', { name: 'Publish import' }).click()
  await expect(page.getByText('Temporary publish failure')).toBeVisible()
  await page.getByRole('button', { name: 'Publish import' }).click()
  await expect(page.getByText('1 facts published')).toBeVisible()
  expect(publishRequests).toHaveLength(2)
  expect(publishRequests[0].preview_digest).toBe('preview-ready-001')
  expect(publishRequests[1].idempotency_key).toBe(publishRequests[0].idempotency_key)

  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations).toEqual([])
})

test('a BLOCKED preview cannot be published', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/imports/preview')) return route.fulfill({ json: fixture.blocked_preview })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected imports request' } })
  })

  await page.goto('/imports')
  await fillErpForm(page, 'lot_id,fabric_quality,colour,qty\nL-221,SJ180,NAVY,1,200\n', 'qty')
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText('BLOCKED', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Publish import' })).toBeDisabled()
  await expect(
    page.getByText('Thousands separators are ambiguous; enter digits without grouping.'),
  ).toBeVisible()
})

const profileCases = [
  {
    profile: 'erp-fabric-stock',
    required: ['lot_id', 'qty', 'fabric_quality', 'colour'],
    values: ['L-221', '4000', 'SJ180', 'NAVY'],
    unit: 'm',
    units: { qty: 'm', allocation_qty: 'm' },
  },
  {
    profile: 'sheet-trims-status',
    required: ['style_id', 'trim_id', 'on_hand', 'supplier'],
    values: ['POLO-221', 'BTN-01', '900', 'Synthetic trims supplier'],
    unit: 'pcs',
    units: { on_hand: 'pcs', inbound_qty: 'pcs' },
  },
  {
    profile: 'shift-capacity',
    required: ['line_id', 'date', 'available_minutes'],
    values: ['L1', '2026-10-22', '480'],
    unit: 'minutes',
    units: { available_minutes: 'minutes', committed_minutes: 'minutes' },
  },
  {
    profile: 'supplier-updates',
    required: ['ref', 'qty', 'fabric_quality', 'colour', 'eta', 'supplier'],
    values: ['IN-221', '1000', 'SJ180', 'NAVY', '2026-10-24', 'Synthetic supplier'],
    unit: 'm',
    units: { qty: 'm', qc_qty: 'm' },
  },
  {
    profile: 'order-requests',
    required: [
      'order_id',
      'buyer',
      'style_id',
      'colours',
      'ship_date',
      'order_value_inr',
      'partial_shipment_allowed',
      'fabric_quality',
      'consumption_per_pc',
      'sam_minutes',
    ],
    values: [
      'ORD-221',
      'Synthetic buyer',
      'POLO-221',
      '[{"colour":"NAVY","qty_pcs":100}]',
      '2026-11-01',
      '100000',
      'true',
      'SJ180',
      '0.002',
      '4',
    ],
    unit: 'm',
    units: { consumption_per_pc: 'm' },
  },
  {
    profile: 'notes',
    required: ['text'],
    values: ['L-221 no holes found.'],
    units: {},
  },
] as const

for (const item of profileCases) {
  test(`${item.profile} maps all required Package A fields and sends units by canonical field`, async ({
    page,
  }) => {
    let body = ''
    await page.route('**/api/v1/**', (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (path.endsWith('/imports/preview')) {
        body = request.postDataBuffer()?.toString('utf8') ?? ''
        return route.fulfill({
          json: { ...fixture.ready_preview, profile: item.profile.replaceAll('-', '_') },
        })
      }
      return route.fulfill({ status: 404, json: { detail: 'Unexpected imports request' } })
    })

    const labels: Record<string, string> = {
      lot_id: 'Lot ID',
      qty: 'Quantity',
      fabric_quality: 'Fabric quality',
      colour: 'Colour',
      style_id: 'Style ID',
      trim_id: 'Trim ID',
      on_hand: 'On hand',
      supplier: 'Supplier',
      line_id: 'Line ID',
      date: 'Work date',
      available_minutes: 'Available minutes',
      ref: 'Reference',
      eta: 'ETA',
      order_id: 'Order ID',
      buyer: 'Buyer',
      colours: 'Colours JSON',
      ship_date: 'Ship date',
      order_value_inr: 'Order value INR',
      partial_shipment_allowed: 'Partial shipment allowed',
      consumption_per_pc: 'Consumption per piece',
      sam_minutes: 'SAM minutes',
      text: 'Note text',
    }
    const headers = [...item.required]
    const csvValues = item.values.map((value) => `"${value.replaceAll('"', '""')}"`).join(',')
    await page.goto('/imports')
    await page.getByLabel('Source profile').selectOption(item.profile)
    await page.getByLabel('CSV file').setInputFiles({
      name: `${item.profile}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(`${headers.join(',')}\n${csvValues}\n`),
    })
    await page.getByLabel('As of (IST)').fill('2026-10-22T10:00')
    if ('unit' in item && item.unit) await page.getByLabel('Quantity unit').selectOption(item.unit)
    if (item.profile === 'erp-fabric-stock')
      await page.getByLabel('Covered fabric qualities').fill('SJ180')
    for (const field of item.required)
      await page.getByLabel(`${labels[field]} column`, { exact: true }).selectOption(field)
    await page.getByRole('button', { name: 'Preview import' }).click()
    await expect(page.getByText('READY', { exact: true })).toBeVisible()
    const mapped = JSON.parse(multipartField(body, 'column_mapping') ?? '{}')
    expect(Object.keys(mapped).sort()).toEqual([...item.required].sort())
    expect(mapped).toEqual(Object.fromEntries(item.required.map((field) => [field, field])))
    if (Object.keys(item.units).length)
      expect(JSON.parse(multipartField(body, 'units') ?? '{}')).toEqual(item.units)
    else expect(multipartField(body, 'units')).toBeUndefined()
  })
}

test('a public workspace explains why imports require private access', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/imports/preview'))
      return route.fulfill({
        status: 403,
        json: { detail: 'PRIVATE_IMPORT_REQUIRED', code: 'PRIVATE_IMPORT_REQUIRED' },
      })
    return route.fulfill({ status: 404, json: { detail: 'Unexpected imports request' } })
  })

  await page.goto('/imports')
  await fillErpForm(page, 'lot_id,fabric_quality,colour,qty\nL-221,SJ180,NAVY,4000\n', 'qty')
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText(/private workspace/i)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Publish import' })).toBeDisabled()
})
