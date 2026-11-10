import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { Limits, PageHeader, Section, StatusTag } from '@/components/board'
import { WorkspacePicker } from '@/components/decisions/WorkspacePicker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { previewImport, publishImport } from '@/lib/decisions'
import type { ImportPreview, ImportPreviewInput, ImportProfile } from '@/lib/decisions-types'
import { ApiError } from '@/lib/http'
import { formatInstant } from '@/lib/status'

type MappingField = { key: string; label: string }
type ProfileConfig = {
  value: ImportProfile
  label: string
  required: MappingField[]
  optional: MappingField[]
  unitKeys: string[]
}

const PROFILES: ProfileConfig[] = [
  {
    value: 'erp-fabric-stock',
    label: 'ERP fabric stock',
    required: [
      { key: 'lot_id', label: 'Lot ID' },
      { key: 'qty', label: 'Quantity' },
      { key: 'fabric_quality', label: 'Fabric quality' },
      { key: 'colour', label: 'Colour' },
    ],
    optional: [
      { key: 'gsm', label: 'GSM' },
      { key: 'width_m', label: 'Width in metres' },
      { key: 'allocation_order_id', label: 'Allocation order ID' },
      { key: 'allocation_qty', label: 'Allocation quantity' },
      { key: 'allocation_quality', label: 'Allocation quality' },
      { key: 'allocation_colour', label: 'Allocation colour' },
    ],
    unitKeys: ['qty', 'allocation_qty'],
  },
  {
    value: 'sheet-trims-status',
    label: 'Trims status sheet',
    required: [
      { key: 'style_id', label: 'Style ID' },
      { key: 'trim_id', label: 'Trim ID' },
      { key: 'on_hand', label: 'On hand' },
      { key: 'supplier', label: 'Supplier' },
    ],
    optional: [
      { key: 'inbound_qty', label: 'Inbound quantity' },
      { key: 'eta', label: 'ETA' },
    ],
    unitKeys: ['on_hand', 'inbound_qty'],
  },
  {
    value: 'shift-capacity',
    label: 'Shift capacity',
    required: [
      { key: 'line_id', label: 'Line ID' },
      { key: 'date', label: 'Work date' },
      { key: 'available_minutes', label: 'Available minutes' },
    ],
    optional: [
      { key: 'efficiency_pct', label: 'Efficiency percent' },
      { key: 'commitment_order_id', label: 'Commitment order ID' },
      { key: 'committed_minutes', label: 'Committed minutes' },
    ],
    unitKeys: ['available_minutes', 'committed_minutes'],
  },
  {
    value: 'supplier-updates',
    label: 'Supplier updates',
    required: [
      { key: 'ref', label: 'Reference' },
      { key: 'qty', label: 'Quantity' },
      { key: 'fabric_quality', label: 'Fabric quality' },
      { key: 'colour', label: 'Colour' },
      { key: 'eta', label: 'ETA' },
      { key: 'supplier', label: 'Supplier' },
    ],
    optional: [
      { key: 'qc_issue', label: 'QC issue' },
      { key: 'qc_qty', label: 'QC quantity' },
      { key: 'lot_id', label: 'QC lot ID' },
    ],
    unitKeys: ['qty', 'qc_qty'],
  },
  {
    value: 'order-requests',
    label: 'Order request and BOM',
    required: [
      { key: 'order_id', label: 'Order ID' },
      { key: 'buyer', label: 'Buyer' },
      { key: 'style_id', label: 'Style ID' },
      { key: 'colours', label: 'Colours JSON' },
      { key: 'ship_date', label: 'Ship date' },
      { key: 'order_value_inr', label: 'Order value INR' },
      { key: 'partial_shipment_allowed', label: 'Partial shipment allowed' },
      { key: 'fabric_quality', label: 'Fabric quality' },
      { key: 'consumption_per_pc', label: 'Consumption per piece' },
      { key: 'sam_minutes', label: 'SAM minutes' },
    ],
    optional: [
      { key: 'consumption_unit', label: 'Consumption unit' },
      { key: 'trims', label: 'Trims JSON' },
    ],
    unitKeys: ['consumption_per_pc'],
  },
  {
    value: 'notes',
    label: 'Notes',
    required: [{ key: 'text', label: 'Note text' }],
    optional: [
      { key: 'note_id', label: 'Note ID' },
      { key: 'lot_hint', label: 'Lot hint' },
    ],
    unitKeys: [],
  },
]

function firstCsvRecord(text: string) {
  const source = text.replace(/^\uFEFF/, '')
  const cells: string[] = []
  let cell = ''
  let quoted = false
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index]
    if (character === '"') {
      if (quoted && source[index + 1] === '"') {
        cell += '"'
        index += 1
      } else quoted = !quoted
    } else if (!quoted && character === ',') {
      cells.push(cell)
      cell = ''
    } else if (!quoted && (character === '\n' || character === '\r')) {
      cells.push(cell)
      return cells
    } else cell += character
  }
  cells.push(cell)
  return cells
}

function inputAsUtc(value: string) {
  if (!value) return ''
  const date = new Date(`${value}:00+05:30`)
  return Number.isNaN(date.getTime()) ? '' : date.toISOString()
}

function statusTone(status: ImportPreview['status']) {
  return status === 'READY' ? 'success' : 'danger'
}

export function DecisionImports() {
  const [profile, setProfile] = useState<ImportProfile>('erp-fabric-stock')
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [asOf, setAsOf] = useState('')
  const [unit, setUnit] = useState('')
  const [coverageQualities, setCoverageQualities] = useState('')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState('')
  const [message, setMessage] = useState('')
  const generation = useRef(0)
  const fileReadGeneration = useRef(0)
  const previewGeneration = useRef(-1)
  const previewMutation = useMutation({ mutationFn: previewImport })
  const publishMutation = useMutation({ mutationFn: publishImport })
  const config = PROFILES.find((item) => item.value === profile)!
  const mappingComplete = config.required.every((field) => mapping[field.key])
  const needsQuantityUnit = config.unitKeys.length > 0

  function invalidatePreview() {
    generation.current += 1
    setPreview(null)
    setIdempotencyKey('')
    setMessage('')
  }

  async function onPreview() {
    if (!file || !inputAsUtc(asOf) || !mappingComplete || (needsQuantityUnit && !unit)) return
    const requestGeneration = generation.current
    setMessage('')
    const input: ImportPreviewInput = {
      file,
      profile,
      column_mapping: mapping,
      as_of: inputAsUtc(asOf),
      ...(needsQuantityUnit
        ? { units: Object.fromEntries(config.unitKeys.map((field) => [field, unit])) }
        : {}),
      ...(profile === 'erp-fabric-stock'
        ? {
            coverage_qualities: coverageQualities
              .split(',')
              .map((value) => value.trim())
              .filter(Boolean),
          }
        : {}),
    }
    try {
      const result = await previewMutation.mutateAsync(input)
      if (generation.current !== requestGeneration) return
      setPreview(result)
      previewGeneration.current = requestGeneration
      setIdempotencyKey(crypto.randomUUID())
    } catch (error) {
      if (generation.current !== requestGeneration) return
      setMessage(
        error instanceof ApiError && error.code === 'PRIVATE_IMPORT_REQUIRED'
          ? 'Imports require a private workspace. The public demo cannot save imported evidence.'
          : error instanceof ApiError
            ? error.message
            : 'Import preview failed. Check the file and try again.',
      )
    }
  }

  async function onPublish() {
    if (!preview || preview.status !== 'READY' || !idempotencyKey) return
    setMessage('')
    const publishingPreview = preview.preview_digest
    const publishingKey = idempotencyKey
    const publishingGeneration = previewGeneration.current
    try {
      const result = await publishMutation.mutateAsync({
        preview_digest: publishingPreview,
        idempotency_key: publishingKey,
      })
      if (
        generation.current !== publishingGeneration ||
        preview?.preview_digest !== publishingPreview
      )
        return
      setMessage(`${result.facts_created} facts published · artifact ${result.artifact_id}`)
    } catch (error) {
      if (
        generation.current !== publishingGeneration ||
        preview?.preview_digest !== publishingPreview
      )
        return
      setMessage(
        error instanceof ApiError
          ? error.message
          : 'Publish failed. You can retry this preview safely.',
      )
    }
  }

  function onFileChange(selected: File | null) {
    const fileGeneration = ++fileReadGeneration.current
    invalidatePreview()
    setFile(selected)
    setHeaders([])
    setMapping({})
    if (selected) {
      void selected
        .text()
        .then((text) => {
          if (fileReadGeneration.current === fileGeneration) {
            setHeaders(firstCsvRecord(text).filter((header) => header.length > 0))
          }
        })
        .catch(() => {
          if (fileReadGeneration.current === fileGeneration)
            setMessage('The CSV file could not be read. Select it again.')
        })
    }
  }

  const publishing = publishMutation.isPending

  return (
    <div className="space-y-8">
      <PageHeader title="Decision imports">
        <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
          Preview file evidence with an explicit source profile, column mapping, units and IST as-of
          time before publishing.
        </p>
      </PageHeader>
      <WorkspacePicker />
      <Section
        title="Import source"
        detail="CSV evidence is previewed before it can become an immutable fact."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-1 text-sm font-medium">
            Source profile
            <select
              disabled={publishing}
              className="h-10 w-full rounded-sm border border-input bg-card px-3 focus-visible:outline-2"
              value={profile}
              onChange={(event) => {
                invalidatePreview()
                setProfile(event.currentTarget.value as ImportProfile)
                setMapping({})
              }}
            >
              {PROFILES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm font-medium">
            CSV file
            <Input
              type="file"
              accept=".csv,text/csv"
              disabled={publishing}
              onChange={(event) => onFileChange(event.currentTarget.files?.[0] ?? null)}
            />
          </label>
          <label className="space-y-1 text-sm font-medium">
            As of (IST)
            <Input
              type="datetime-local"
              value={asOf}
              disabled={publishing}
              onChange={(event) => {
                invalidatePreview()
                setAsOf(event.currentTarget.value)
              }}
            />
          </label>
          {needsQuantityUnit ? (
            <label className="space-y-1 text-sm font-medium">
              Quantity unit
              <select
                disabled={publishing}
                className="h-10 w-full rounded-sm border border-input bg-card px-3 focus-visible:outline-2"
                value={unit}
                onChange={(event) => {
                  invalidatePreview()
                  setUnit(event.currentTarget.value)
                }}
              >
                <option value="">Choose a unit</option>
                <option value="kg">kg</option>
                <option value="m">m</option>
                <option value="pcs">pcs</option>
                <option value="minutes">minutes</option>
              </select>
            </label>
          ) : null}
          {profile === 'erp-fabric-stock' ? (
            <label className="space-y-1 text-sm font-medium md:col-span-2">
              Covered fabric qualities
              <Input
                value={coverageQualities}
                disabled={publishing}
                placeholder="SJ180, SJ200"
                onChange={(event) => {
                  invalidatePreview()
                  setCoverageQualities(event.currentTarget.value)
                }}
              />
            </label>
          ) : null}
        </div>
        <div className="mt-5 border-t border-border pt-4">
          <h2 className="text-base font-semibold">Column mapping</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Choose a source column for each required field. Columns are never guessed.
          </p>
          {[...config.required, ...config.optional].map((field) => (
            <label key={field.key} className="mt-3 block max-w-xl space-y-1 text-sm font-medium">
              {field.label} column{' '}
              {config.required.some((required) => required.key === field.key)
                ? '(required)'
                : '(optional)'}
              <select
                aria-label={`${field.label} column`}
                disabled={publishing}
                className="h-10 w-full rounded-sm border border-input bg-card px-3 focus-visible:outline-2"
                value={mapping[field.key] ?? ''}
                onChange={(event) => {
                  const value = event.currentTarget.value
                  invalidatePreview()
                  setMapping((current) => {
                    const next = { ...current }
                    if (value) next[field.key] = value
                    else delete next[field.key]
                    return next
                  })
                }}
              >
                <option value="">Not mapped</option>
                {headers.map((header) => (
                  <option
                    key={header}
                    value={header}
                    disabled={Object.entries(mapping).some(
                      ([key, value]) => key !== field.key && value === header,
                    )}
                  >
                    {header}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button
            onClick={() => void onPreview()}
            disabled={
              publishing ||
              !file ||
              !inputAsUtc(asOf) ||
              !mappingComplete ||
              (needsQuantityUnit && !unit) ||
              previewMutation.isPending
            }
          >
            {previewMutation.isPending ? 'Previewing…' : 'Preview import'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => void onPublish()}
            disabled={
              !preview || preview.status !== 'READY' || !idempotencyKey || publishMutation.isPending
            }
          >
            {publishMutation.isPending ? 'Publishing…' : 'Publish import'}
          </Button>
        </div>
      </Section>
      {message ? (
        <p role="status" className="rounded-sm border border-border bg-card p-3 text-sm">
          {message}
        </p>
      ) : null}
      {preview ? (
        <Section
          title="Preview result"
          detail={`File ${preview.filename} · as of ${formatInstant(preview.as_of)}`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <StatusTag tone={statusTone(preview.status)}>{preview.status}</StatusTag>
            <span className="font-mono text-xs">Digest {preview.preview_digest}</span>
          </div>
          {preview.problems.length ? (
            <Limits tone="danger">
              <ul className="list-disc space-y-1 pl-5">
                {preview.problems.map((problem, index) => (
                  <li key={`${problem.row}:${problem.field}:${index}`}>
                    Row {problem.row} · {problem.field}: {problem.message}
                  </li>
                ))}
              </ul>
            </Limits>
          ) : null}
          {preview.facts.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Entity</TableHead>
                  <TableHead>Fact kind</TableHead>
                  <TableHead>Valid from</TableHead>
                  <TableHead>Payload</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.facts.map((fact) => (
                  <TableRow key={fact.id}>
                    <TableCell className="font-mono text-xs">{fact.entity_key}</TableCell>
                    <TableCell>{fact.kind}</TableCell>
                    <TableCell>{formatInstant(fact.valid_from)}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {JSON.stringify(fact.payload)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
          {preview.notes.length ? (
            <ul className="space-y-2">
              {preview.notes.map((note) => (
                <li key={note.note_id} className="rounded-sm border border-border p-3 text-sm">
                  {note.text}
                </li>
              ))}
            </ul>
          ) : null}
        </Section>
      ) : null}
    </div>
  )
}
