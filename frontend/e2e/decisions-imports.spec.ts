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

function decodeCsv(body: Record<string, unknown>) {
  return Buffer.from(String(body.content_base64), 'base64').toString('utf8')
}

test('imports send the file and explicit settings as JSON and mapping edits invalidate the preview', async ({
  page,
}) => {
  const previewRequests: Record<string, unknown>[] = []
  const publishRequests: Record<string, unknown>[] = []
  let failFirstPublish = true
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/imports/preview') && request.method() === 'POST') {
      previewRequests.push(request.postDataJSON())
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
  const [sent] = previewRequests
  expect(sent).toMatchObject({
    filename: 'fabric-stock.csv',
    profile: 'erp-fabric-stock',
    timezone: 'Asia/Kolkata',
    coverage_qualities: ['SJ180'],
  })
  expect(String(sent.as_of)).toContain('2026-10-22T04:30:00')
  expect(decodeCsv(sent)).toBe(erpCsv)
  expect(sent.column_mapping).toEqual({
    lot_id: 'lot_id',
    fabric_quality: 'fabric_quality',
    colour: 'colour',
    qty: 'Stock, metres',
  })
  expect(sent.units).toEqual({ qty: 'm', allocation_qty: 'm' })

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
  // Publishing sends the previewed bytes and settings again, so the server can re-check them.
  expect(decodeCsv(publishRequests[0])).toBe(erpCsv)
  expect(publishRequests[0].column_mapping).toEqual(sent.column_mapping)
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
    let body: Record<string, unknown> = {}
    await page.route('**/api/v1/**', (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (path.endsWith('/imports/preview')) {
        body = request.postDataJSON()
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
    const mapped = body.column_mapping as Record<string, string>
    expect(Object.keys(mapped).sort()).toEqual([...item.required].sort())
    expect(mapped).toEqual(Object.fromEntries(item.required.map((field) => [field, field])))
    expect(body.units).toEqual(item.units)
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
  await expect(page.getByText(/Imports require a private workspace/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Publish import' })).toBeDisabled()
})

test('editing metadata keeps pending headers while selecting a new file discards old headers', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const originalText = File.prototype.text
    const pending = new Map<string, () => Promise<void>>()
    Object.assign(window, {
      releaseFileText: (name: string) => pending.get(name)?.(),
    })
    File.prototype.text = function (this: File) {
      if (!this.name.startsWith('slow-')) return originalText.call(this)
      return new Promise<string>((resolve, reject) => {
        pending.set(this.name, () => originalText.call(this).then(resolve, reject))
      })
    }
  })
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ status: 503, json: { message: 'Unavailable in header-read test' } }),
  )
  await page.goto('/imports')
  const file = page.getByLabel('CSV file')
  const columns = page.getByLabel('Lot ID column', { exact: true }).locator('option')
  await file.setInputFiles({
    name: 'slow-stock.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(erpCsv),
  })
  await expect(columns).toHaveCount(1)
  await page.getByLabel('As of (IST)').fill('2026-10-23T10:00')
  await page.getByLabel('Quantity unit').selectOption('m')
  await page.getByLabel('Covered fabric qualities').fill('SJ180')
  await page.evaluate(async () => {
    const controls = window as typeof window & {
      releaseFileText: (name: string) => Promise<void> | undefined
    }
    await controls.releaseFileText('slow-stock.csv')
  })
  await expect(columns).toHaveText([
    'Not mapped',
    'lot_id',
    'fabric_quality',
    'colour',
    'Stock, metres',
    'unused',
  ])

  await file.setInputFiles({
    name: 'slow-old.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('old_lot,old_qty\nL-221,1\n'),
  })
  await file.setInputFiles({
    name: 'fresh-stock.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('new_lot,new_qty\nL-222,2\n'),
  })
  await expect(columns).toHaveText(['Not mapped', 'new_lot', 'new_qty'])
  await page.evaluate(async () => {
    const controls = window as typeof window & {
      releaseFileText: (name: string) => Promise<void> | undefined
    }
    await controls.releaseFileText('slow-old.csv')
  })
  await expect(columns).toHaveText(['Not mapped', 'new_lot', 'new_qty'])
})

test('an unreadable CSV explains the failure and a replacement file can still load', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const originalText = File.prototype.text
    File.prototype.text = function (this: File) {
      if (this.name === 'unreadable.csv') return Promise.reject(new Error('Synthetic read failure'))
      return originalText.call(this)
    }
  })
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ status: 503, json: { message: 'Unavailable in header-read test' } }),
  )
  await page.goto('/imports')
  const file = page.getByLabel('CSV file')
  await file.setInputFiles({
    name: 'unreadable.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(erpCsv),
  })
  await expect(page.getByText('The CSV file could not be read. Select it again.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Preview import' })).toBeDisabled()
  await file.setInputFiles({
    name: 'replacement.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(erpCsv),
  })
  await expect(page.getByLabel('Lot ID column', { exact: true }).locator('option')).toHaveCount(6)
  await expect(page.getByText('The CSV file could not be read. Select it again.')).toHaveCount(0)
})
