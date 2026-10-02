import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ArrowLeft } from 'lucide-react'
import { workspaceApi } from '@/lib/workspaces'
import { api } from '@/lib/api'
import { useAuth } from '@/components/Auth'
import { incidentApi, type IncidentImportBody, type IncidentImportPreview, type IncidentCsvInspection, type NewIncidentBody } from '@/lib/incidents'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

const MAX_BYTES = 2 * 1024 * 1024

type ColumnChoice = { kind: 'unmapped' } | { kind: 'column'; header: string } | { kind: 'constant'; value: string }
type ColumnChoices = Record<string, ColumnChoice>
interface ImportPreviewState { body: IncidentImportBody; result: IncidentImportPreview; idempotencyKey: string; newIncident?: Omit<NewIncidentBody, 'preview_digest' | 'idempotency_key'> }

async function readImportFile(file: File | null): Promise<string> {
  if (!file) throw new Error('Choose a local CSV, JSON, or JSONL file.')
  if (file.size > MAX_BYTES) throw new Error('File exceeds the 2 MiB import limit.')
  try { return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer()) }
  catch { throw new Error('File must be valid UTF-8 text.') }
}

function CsvColumnMapping({ inspection, choices, onChange, scopeDefaults, onUseScope }: { inspection: IncidentCsvInspection; choices: ColumnChoices; onChange: (name: string, value: ColumnChoice) => void; scopeDefaults: Record<string, string>; onUseScope: () => void }) {
  const renderField = (field: IncidentCsvInspection['fields'][number]) => {
      const choice = choices[field.name] ?? { kind: 'unmapped' }
      const selected = choice.kind === 'column' ? `column-${inspection.headers.indexOf(choice.header)}` : choice.kind
      return <div key={field.name} className="grid gap-2 rounded border border-zinc-200 p-3 sm:grid-cols-2">
        <div><label htmlFor={`csv-map-${field.name}`} className="text-xs font-medium">Map {field.name}{field.required ? ' (required)' : ''}</label><p className="mt-1 text-xs leading-5 text-zinc-600">{field.description}</p></div>
        <div className="space-y-2"><select id={`csv-map-${field.name}`} value={selected} onChange={(event) => {
          const header = inspection.headers.find((_, index) => event.target.value === `column-${index}`)
          onChange(field.name, event.target.value === 'constant' ? { kind: 'constant', value: '' } : header === undefined ? { kind: 'unmapped' } : { kind: 'column', header })
        }} className="min-h-10 w-full rounded border border-zinc-300 bg-white px-2 text-sm"><option value="unmapped">Unmapped / ignore</option><option value="constant">Explicit constant</option>{inspection.headers.map((header, index) => <option key={header} value={`column-${index}`}>{header}</option>)}</select>
        {choice.kind === 'constant' && <label className="block text-xs">Constant for {field.name}<Input className="mt-1" required={field.required} value={choice.value} onChange={(event) => onChange(field.name, { kind: 'constant', value: event.target.value })} /></label>}
        {field.name === 'count_mode' && <p className="text-xs leading-5 text-amber-900">Production imports require an explicit count_mode of delta. Cumulative readings must not be labeled as deltas.</p>}
        </div>
      </div>
  }
  return <section aria-labelledby="csv-mapping-heading" className="space-y-4 border-t border-zinc-200 pt-5">
    <div><h2 id="csv-mapping-heading" className="text-base font-semibold">Match CSV columns</h2><p className="mt-1 text-sm leading-6 text-zinc-600">{inspection.row_count} original rows. Only identical canonical headers are preselected. Choose each source column or enter an explicit constant; unmapped columns are ignored. No dates, identifiers, units, or cumulative counts are inferred or converted.</p></div>
    <div className="max-w-full overflow-x-auto rounded border border-zinc-200"><table className="w-full min-w-max text-left text-xs"><caption className="px-3 py-2 text-left font-medium">Original CSV sample · first {inspection.sample_rows.length} rows</caption><thead className="bg-zinc-50"><tr>{inspection.headers.map((header) => <th key={header} scope="col" className="min-w-48 whitespace-nowrap px-3 py-2 font-medium">{header}</th>)}</tr></thead><tbody className="divide-y divide-zinc-100">{inspection.sample_rows.map((row, index) => <tr key={index}>{inspection.headers.map((header) => <td key={header} className="min-w-48 max-w-80 whitespace-pre-wrap break-words px-3 py-2">{row[header]}</td>)}</tr>)}</tbody></table></div>
    {Object.keys(scopeDefaults).length > 0 && <div className="space-y-2 rounded bg-zinc-50 p-3 text-xs leading-5"><p>Destination scope constants available: {Object.entries(scopeDefaults).map(([name, value]) => `${name}=${value}`).join(' · ')}</p><Button type="button" variant="outline" size="sm" onClick={onUseScope}>Use destination scope for unmapped fields</Button><p>This only fills unmapped scope fields. Source columns you selected remain authoritative and are validated against the destination.</p></div>}
    <p className="text-xs leading-5 text-zinc-600">Ignored source columns: {inspection.headers.filter((header) => !Object.values(choices).some((choice) => choice.kind === 'column' && choice.header === header)).join(', ') || 'None'}. Map a correction or relationship column explicitly when it carries evidence.</p>
    <div className="space-y-3">{inspection.fields.filter((field) => field.required).map(renderField)}</div>
    <details className="space-y-3"><summary className="cursor-pointer py-2 text-sm font-medium">Optional fields and record relationships ({inspection.fields.filter((field) => !field.required).length})</summary><div className="space-y-3">{inspection.fields.filter((field) => !field.required).map(renderField)}</div></details>
  </section>
}

function NormalizedSample({ preview }: { preview: IncidentImportPreview }) {
  const groups = [{ title: 'Normalized baseline plans', rows: preview.plan_buckets }, { title: 'Normalized output records', rows: preview.output_buckets }, { title: 'Normalized operational evidence', rows: preview.events }]
  return <div className="space-y-4">{groups.filter((group) => group.rows.length > 0).map((group) => <section key={group.title} className="space-y-2"><h3 className="text-sm font-medium">{group.title} · first {Math.min(group.rows.length, 5)} records</h3><div className="grid gap-2 lg:grid-cols-2">{group.rows.slice(0, 5).map((row, index) => <dl key={index} className="space-y-1 rounded border border-zinc-200 p-3 text-xs leading-5">{typeof row === 'object' && row !== null && Object.entries(row).map(([name, value]) => <div key={name} className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-3"><dt className="break-words font-medium text-zinc-600">{name.replaceAll('_', ' ')}</dt><dd className="break-words whitespace-pre-wrap">{value === null ? 'Not provided' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>)}</div></section>)}</div>
}


export function IncidentImportsPage() {
  const { user } = useAuth()
  return <IncidentImportsForm key={user?.id ?? 'anonymous'} owner={user?.role === 'owner'} />
}

function IncidentImportsForm({ owner }: { owner: boolean }) {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const workspaces = useQuery({ queryKey: ['workspaces', user?.id], queryFn: workspaceApi.list, enabled: owner, retry: false })
  const [workspaceId, setWorkspaceId] = useState('')
  const capabilities = useQuery({ queryKey: ['capabilities', user?.id ?? 'public'], queryFn: api.capabilities })
  const incidents = useQuery({ queryKey: ['incidents', user?.id ?? 'public'], queryFn: incidentApi.list, enabled: owner && capabilities.data?.imports_enabled })
  const [incidentId, setIncidentId] = useState('')
  const [mode, setMode] = useState<'existing' | 'new'>('existing')
  const [newId, setNewId] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [factory, setFactory] = useState('')
  const [line, setLine] = useState('')
  const [order, setOrder] = useState('')
  const [style, setStyle] = useState('')
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [baseRevision, setBaseRevision] = useState(1)
  const [cutoff, setCutoff] = useState('')
  const [profile, setProfile] = useState<IncidentImportBody['profile']>('operations-v1')
  const [sourceSystem, setSourceSystem] = useState('shift-log')
  const [timezone, setTimezone] = useState('Asia/Kolkata')
  const unit = 'good_units'
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [preview, setPreview] = useState<ImportPreviewState | null>(null)
  const [inspection, setInspection] = useState<IncidentCsvInspection | null>(null)
  const [choices, setChoices] = useState<ColumnChoices>({})
  const version = useRef(0)
  const fileVersion = useRef(0)
  const selected = incidents.data?.items.find((item) => item.id === incidentId)
  const effectiveProfile = mode === 'new' ? 'production-v1' : profile
  const csv = file?.name.toLowerCase().endsWith('.csv') === true
  const destination = useQuery({ queryKey: ['incident', incidentId, baseRevision], queryFn: () => incidentApi.revision(incidentId, baseRevision), enabled: owner && mode === 'existing' && !!selected })
  const scopeDefaults: Record<string, string> = mode === 'new' ? { factory, line_id: line, order_id: order, style_id: style, stage: 'sewing', unit: 'good_units' } : destination.data?.scope ?? {}
  const inspect = useMutation({
    mutationFn: async (input: { file: File; profile: IncidentImportBody['profile']; version: number }) => ({ result: await incidentApi.inspectCsv({ raw_text: await readImportFile(input.file), filename: input.file.name, profile: input.profile }), version: input.version }),
    onSuccess: ({ result, version: requestedVersion }) => {
      if (requestedVersion !== fileVersion.current) return
      setInspection(result)
      setChoices(Object.fromEntries(result.fields.map((field): [string, ColumnChoice] => [field.name, result.headers.includes(field.name) ? { kind: 'column', header: field.name } : { kind: 'unmapped' }])))
    }, retry: false,
  })
  const mapping = csv && inspection ? {
    column_mapping: Object.fromEntries(Object.entries(choices).flatMap(([name, choice]) => choice.kind === 'column' ? [[name, choice.header]] : [])),
    field_defaults: Object.fromEntries(Object.entries(choices).flatMap(([name, choice]) => choice.kind === 'constant' && choice.value.trim() ? [[name, choice.value.trim()]] : [])),
  } : {}
  const missingMappings = csv && (!inspection || inspection.fields.some((field) => { const choice = choices[field.name]; return field.required && (!choice || choice.kind === 'unmapped' || choice.kind === 'constant' && !choice.value.trim()) }))

  const previewMutation = useMutation({
    mutationFn: async (input: { file: File; body: Omit<IncidentImportBody, 'raw_text' | 'filename'>; newIncident?: Omit<NewIncidentBody, 'raw_text' | 'filename' | 'preview_digest' | 'idempotency_key'>; version: number }) => {
      const rawText = await readImportFile(input.file)
      const body: IncidentImportBody = { ...input.body, raw_text: rawText, filename: input.file.name }
      const newIncident = input.newIncident ? { ...input.newIncident, raw_text: rawText, filename: input.file.name } : undefined
      return { body, result: await incidentApi.previewImport(body), newIncident, version: input.version }
    },
    onSuccess: ({ body, result, newIncident, version: requestedVersion }) => { if (requestedVersion === version.current) setPreview({ body, result, newIncident, idempotencyKey: crypto.randomUUID() }) },
    retry: false,
  })
  const publish = useMutation({
    mutationFn: (pending: ImportPreviewState) => pending.newIncident
      ? incidentApi.createIncident({ ...pending.newIncident, preview_digest: pending.result.preview_digest, idempotency_key: pending.idempotencyKey })
      : incidentApi.publishImport(pending.body, pending.result.preview_digest, pending.idempotencyKey),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['incidents'] }), retry: false,
  })
  const changed = () => { version.current++; setPreview(null); previewMutation.reset(); publish.reset() }
  const fileOrProfileChanged = () => { fileVersion.current++; setInspection(null); setChoices({}); inspect.reset(); changed() }
  const previewSource = () => {
    if (!file) return
    const newIncident: Omit<NewIncidentBody, 'raw_text' | 'filename' | 'preview_digest' | 'idempotency_key'> | undefined = mode === 'new' ? {
      workspace_id: workspaceId || null, incident_id: newId.trim(), title: newTitle.trim(), scope: { factory: factory.trim(), line_id: line.trim(), order_id: order.trim(), style_id: style.trim(), stage: 'sewing', unit: 'good_units' },
      window: { start: windowStart.trim(), end: windowEnd.trim() }, cutoff: cutoff.trim(), source_system: sourceSystem.trim(), timezone: timezone.trim(), ...mapping,
    } : undefined
    const body: Omit<IncidentImportBody, 'raw_text' | 'filename'> = {
      workspace_id: mode === 'new' ? workspaceId || null : selected?.workspace_id ?? null, incident_id: mode === 'new' ? newId.trim() : incidentId, base_revision: mode === 'new' ? 0 : baseRevision, cutoff: cutoff.trim(),
      profile: effectiveProfile, source_system: sourceSystem.trim(), timezone: timezone.trim(), unit: effectiveProfile === 'production-v1' ? unit.trim() : null,
      ...(newIncident ? { scope: newIncident.scope } : {}), ...mapping,
    }
    setPreview(null)
    previewMutation.mutate({ file, body, newIncident, version: version.current })
  }
  const busy = inspect.isPending || previewMutation.isPending || publish.isPending
  const chooseIncident = (id: string) => {
    const item = incidents.data?.items.find((incident) => incident.id === id)
    setIncidentId(id)
    setBaseRevision(item?.revision ?? 1)
    setCutoff(item ? new Date(Date.parse(item.cutoff) + 30 * 60_000).toISOString() : '')
    changed()
  }

  return <div className="space-y-6">
    <div className="border-b border-zinc-200 pb-5"><Link to="/" className="inline-flex items-center gap-1.5 text-xs text-zinc-600 underline underline-offset-4"><ArrowLeft aria-hidden="true" className="size-3.5" />Incident library</Link><h1 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">Import incident evidence</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">Preview a local source file and its row diagnostics before adding it to an incident.</p></div>
    {capabilities.isPending ? <Skeleton className="h-32" /> : capabilities.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">Could not check permissions: {capabilities.error.message}</div> : !owner || !capabilities.data?.imports_enabled ? <div className="rounded border border-zinc-200 bg-white p-5 text-sm text-zinc-700">Sign in with an owner account to import source evidence.</div> : <>
      <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Publishing creates an immutable incident revision. Existing reports and reviews remain attached to their original revisions. A new baseline requires a new incident.</div>
      {incidents.isPending ? <Skeleton className="h-64" /> : incidents.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">Could not load incidents: {incidents.error.message}</div> : <form className="space-y-6 rounded-xl border border-zinc-200 bg-white p-5 sm:p-6" onSubmit={(event) => { event.preventDefault(); previewSource() }}><fieldset disabled={busy} className="space-y-6 min-w-0">
        <div className="border-b border-zinc-200 pb-5"><h2 className="mb-4 text-base font-semibold">Incident destination</h2><label htmlFor="import-mode" className="mb-1 block text-xs font-medium">Import into</label><select id="import-mode" value={mode} onChange={(event) => { setMode(event.target.value === 'new' ? 'new' : 'existing'); fileOrProfileChanged() }} className="h-10 w-full max-w-sm rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2"><option value="existing">Existing incident · new revision</option><option value="new">New incident · baseline plan</option></select></div>
        {mode === 'new' && <div className="space-y-2"><label className="block text-xs font-medium">Private destination workspace<select className="mt-1 min-h-10 w-full rounded border bg-white px-3 text-sm" value={workspaceId} onChange={(event) => { setWorkspaceId(event.target.value); changed() }}><option value="">My private workspace</option>{workspaces.data?.items.filter((item) => item.role === 'owner').map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><p className="text-xs text-zinc-600">New records are private. Public demonstration incidents cannot receive source imports.</p>{workspaces.isError && <p role="alert" className="text-xs text-amber-900">Workspace list unavailable. The default destination remains your private workspace.</p>}</div>}
        {mode === 'existing' ? <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="import-incident" className="mb-1 block text-xs font-medium">Incident</label><select id="import-incident" required value={incidentId} onChange={(event) => chooseIncident(event.target.value)} className="h-10 w-full rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2"><option value="">Select an incident…</option>{incidents.data.items.filter((item) => item.workspace_id && item.workspace_id !== 'public-demo').map((item) => <option key={item.id} value={item.id}>{item.id} · {item.title}</option>)}</select></div><div><label htmlFor="import-revision" className="mb-1 block text-xs font-medium">Base revision</label><select id="import-revision" required value={baseRevision} onChange={(event) => { setBaseRevision(Number(event.target.value)); changed() }} disabled={!selected} className="h-10 w-full rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2">{Array.from({ length: selected?.revision ?? 1 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>Revision {value}{value === selected?.revision ? ' · latest' : ' · historical'}</option>)}</select><p className="mt-1 text-xs text-zinc-600">Publication requires the latest revision.</p></div></div> : <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="new-id" className="mb-1 block text-xs font-medium">New incident ID</label><Input id="new-id" required maxLength={64} value={newId} onChange={(event) => { setNewId(event.target.value); changed() }} placeholder="INC-201" /></div><div><label htmlFor="new-title" className="mb-1 block text-xs font-medium">Incident title</label><Input id="new-title" required minLength={3} maxLength={200} value={newTitle} onChange={(event) => { setNewTitle(event.target.value); changed() }} placeholder="Delayed output on sewing line S2" /></div><div><label htmlFor="new-factory" className="mb-1 block text-xs font-medium">Factory</label><Input id="new-factory" required value={factory} onChange={(event) => { setFactory(event.target.value); changed() }} /></div><div><label htmlFor="new-line" className="mb-1 block text-xs font-medium">Sewing line</label><Input id="new-line" required value={line} onChange={(event) => { setLine(event.target.value); changed() }} /></div><div><label htmlFor="new-order" className="mb-1 block text-xs font-medium">Order ID</label><Input id="new-order" required value={order} onChange={(event) => { setOrder(event.target.value); changed() }} /></div><div><label htmlFor="new-style" className="mb-1 block text-xs font-medium">Style ID</label><Input id="new-style" required value={style} onChange={(event) => { setStyle(event.target.value); changed() }} /></div><div><label htmlFor="new-window-start" className="mb-1 block text-xs font-medium">Window start</label><Input id="new-window-start" required value={windowStart} onChange={(event) => { setWindowStart(event.target.value); changed() }} placeholder="2026-09-28T09:00:00+05:30" /></div><div><label htmlFor="new-window-end" className="mb-1 block text-xs font-medium">Window end</label><Input id="new-window-end" required value={windowEnd} onChange={(event) => { setWindowEnd(event.target.value); changed() }} placeholder="2026-09-28T12:00:00+05:30" /></div><p className="text-xs text-zinc-600 sm:col-span-2">Scope is sewing stage, good_units. The file must include matching 15-minute baseline plan records.</p></div>}
        <div className="grid gap-4 border-t border-zinc-200 pt-5 sm:grid-cols-2"><h2 className="text-base font-semibold sm:col-span-2">Source evidence</h2><div>{mode === 'existing' ? <><label htmlFor="import-profile" className="mb-1 block text-xs font-medium">Source profile</label><select id="import-profile" value={profile} onChange={(event) => { const value = event.target.value; if (value === 'production-v1' || value === 'operations-v1' || value === 'notes-v1') setProfile(value); fileOrProfileChanged() }} className="h-10 w-full rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2"><option value="operations-v1">Operations</option><option value="notes-v1">Notes</option><option value="production-v1">Production output</option></select></> : <p className="text-sm text-zinc-700"><strong>Source profile:</strong> Production baseline</p>}</div><div><label htmlFor="import-file" className="mb-1 block text-xs font-medium">Local file</label><Input id="import-file" type="file" required accept=".csv,.json,.jsonl" onChange={(event) => { const next = event.target.files?.[0] ?? null; setFile(next); setFileError(next && next.size > MAX_BYTES ? 'File exceeds 2 MiB.' : ''); fileOrProfileChanged() }} /><p className="mt-1 text-xs text-zinc-600">UTF-8 · CSV, JSON, or JSONL · up to 10,000 rows and 2 MiB</p>{fileError && <p role="alert" className="text-xs text-red-700">{fileError}</p>}</div></div>
        <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="import-source" className="mb-1 block text-xs font-medium">Source system</label><Input id="import-source" required value={sourceSystem} onChange={(event) => { setSourceSystem(event.target.value); changed() }} /></div><div><label htmlFor="import-timezone" className="mb-1 block text-xs font-medium">Source timezone</label><Input id="import-timezone" required value={timezone} onChange={(event) => { setTimezone(event.target.value); changed() }} /><p className="mt-1 text-xs text-zinc-600">IANA timezone, for example Asia/Kolkata</p></div></div>
        <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="import-cutoff" className="mb-1 block text-xs font-medium">Knowledge cutoff</label><Input id="import-cutoff" required value={cutoff} onChange={(event) => { setCutoff(event.target.value); changed() }} placeholder="2026-09-28T11:30:00+05:30" /><p className="mt-1 text-xs text-zinc-600">ISO timestamp with offset{mode === 'existing' ? '; later than the base revision’s cutoff.' : '; at or after window start.'}</p></div>{(mode === 'new' || profile === 'production-v1') && <div><label htmlFor="import-unit" className="mb-1 block text-xs font-medium">Production unit</label><Input id="import-unit" required readOnly value={unit} /><p className="mt-1 text-xs text-zinc-600">Use good_units. Counts must be 15-minute deltas.</p></div>}</div>
        <div className="flex flex-wrap gap-3 text-xs"><a className="underline underline-offset-4" href="/import-examples/production-v1.csv" download>Download baseline CSV example</a><a className="underline underline-offset-4" href="/import-examples/production-output-v1.csv" download>Download output CSV example</a><a className="underline underline-offset-4" href="/import-examples/operations-v1.csv" download>Download operations CSV example</a><a className="underline underline-offset-4" href="/import-examples/notes-v1.csv" download>Download notes CSV example</a></div>
        {csv && <div className="space-y-3"><Button type="button" size="sm" variant="outline" disabled={!file || !!fileError || busy} onClick={() => { if (file) { changed(); inspect.mutate({ file, profile: effectiveProfile, version: fileVersion.current }) } }}>{inspect.isPending ? 'Inspecting columns…' : inspection ? 'Inspect CSV again and reset mapping' : 'Inspect CSV columns'}</Button><p className="text-xs leading-5 text-zinc-600">Inspect before previewing. Match unfamiliar headers explicitly and check the original sample. Production quantities must already be 15-minute deltas.</p>{inspect.isError && <p role="alert" className="text-xs text-red-800">Could not inspect CSV: {inspect.error.message}. Check the file and retry inspection.</p>}</div>}
        {csv && inspection && <CsvColumnMapping inspection={inspection} choices={choices} scopeDefaults={Object.fromEntries(Object.entries(scopeDefaults).filter(([, value]) => value.trim()))} onChange={(name, value) => { setChoices({ ...choices, [name]: value }); changed() }} onUseScope={() => {
          const next = { ...choices }
          for (const field of inspection.fields) { const value = scopeDefaults[field.name]; if (value?.trim() && (!next[field.name] || next[field.name].kind === 'unmapped')) next[field.name] = { kind: 'constant', value: value.trim() } }
          setChoices(next); changed()
        }} />}
        {csv && missingMappings && <p role="status" className="text-xs text-amber-900">Inspect the CSV and map or explicitly supply every required field before previewing.</p>}
        <Button type="submit" size="sm" disabled={!(mode === 'new' ? newId.trim() : incidentId) || !file || !!fileError || busy || missingMappings}>{previewMutation.isPending ? 'Checking rows…' : 'Preview source'}</Button>
        {previewMutation.isError && <p role="alert" className="text-sm text-red-700">{previewMutation.error.message}</p>}
      </fieldset></form>}
      {preview && <section className="space-y-4 rounded-xl border border-zinc-200 bg-white p-5 sm:p-6" aria-label="Import preview"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="text-base font-semibold">Preview: {preview.result.status}</h2><p className="mt-1 text-xs text-zinc-600">{preview.result.row_count} rows · {preview.result.plan_buckets.length} plan · {preview.result.output_buckets.length} output · {preview.result.events.length} events</p></div><span className="rounded bg-zinc-100 px-2 py-1 font-mono text-xs">{preview.result.raw_digest.slice(0, 12)}…</span></div>
        {preview.result.issues.length ? <div className="overflow-x-auto rounded border border-red-200"><table className="w-full min-w-[500px] text-left text-sm"><thead className="bg-red-50 text-xs uppercase text-red-900"><tr><th scope="col" className="px-3 py-2">Row</th><th scope="col" className="px-3 py-2">Field</th><th scope="col" className="px-3 py-2">Issue</th></tr></thead><tbody className="divide-y divide-red-100">{preview.result.issues.map((issue, index) => <tr key={index}><td className="px-3 py-2 tabular-nums">{issue.row}</td><td className="px-3 py-2">{issue.field}</td><td className="px-3 py-2">{issue.message}</td></tr>)}</tbody></table></div> : <p className="text-sm text-zinc-700">All rows passed validation. Publication is all or nothing.</p>}
        <NormalizedSample preview={preview.result} />
        {preview.newIncident ? preview.result.plan_buckets.length === 0 && <p className="text-xs text-amber-800">A new incident requires baseline plan records in the file.</p> : preview.result.plan_buckets.length > 0 && <p className="text-xs text-amber-800">Existing baselines are immutable. This file cannot be published into the selected incident.</p>}
        <Button size="sm" disabled={preview.result.status !== 'READY' || (preview.newIncident ? preview.result.plan_buckets.length === 0 : preview.result.plan_buckets.length > 0) || publish.isPending || publish.isSuccess} onClick={() => publish.mutate(preview)}>{publish.isPending ? 'Publishing…' : publish.isSuccess ? 'Published' : publish.isError ? 'Retry same publication' : preview.newIncident ? 'Create incident' : 'Publish new revision'}</Button>
        {publish.isError && <p role="alert" className="text-sm text-red-700">Publication failed: {publish.error.message}</p>}
        {publish.data && <p role="status" className="text-sm text-zinc-700">Revision {publish.data.revision} published. <Link className="underline underline-offset-4" to={`/incidents/${encodeURIComponent(publish.data.id)}?revision=${publish.data.revision}`}>Open the new investigation</Link>.</p>}
      </section>}
    </>}
  </div>
}
