import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ArrowLeft } from 'lucide-react'
import { api } from '@/lib/api'
import { incidentApi, type IncidentImportBody, type IncidentImportPreview, type NewIncidentBody } from '@/lib/incidents'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

const MAX_BYTES = 2 * 1024 * 1024

export function IncidentImportsPage() {
  const queryClient = useQueryClient()
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities })
  const incidents = useQuery({ queryKey: ['incidents'], queryFn: incidentApi.list, enabled: capabilities.data?.imports_enabled })
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
  const [unit, setUnit] = useState('good_units')
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [preview, setPreview] = useState<{ body: IncidentImportBody; result: IncidentImportPreview; idempotencyKey: string; newIncident?: Omit<NewIncidentBody, 'preview_digest' | 'idempotency_key'> } | null>(null)
  const selected = incidents.data?.items.find((item) => item.id === incidentId)

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a local CSV, JSON, or JSONL file.')
      if (file.size > MAX_BYTES) throw new Error('File exceeds the 2 MiB import limit.')
      let rawText: string
      try { rawText = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()) }
      catch { throw new Error('File must be valid UTF-8 text.') }
      const body: IncidentImportBody = {
        incident_id: mode === 'new' ? newId.trim() : incidentId,
        base_revision: mode === 'new' ? 0 : baseRevision, cutoff: cutoff.trim(),
        raw_text: rawText, profile: mode === 'new' ? 'production-v1' : profile,
        source_system: sourceSystem.trim(), timezone: timezone.trim(),
        filename: file.name, unit: mode === 'new' || profile === 'production-v1' ? unit.trim() : null,
      }
      const newIncident: Omit<NewIncidentBody, 'preview_digest' | 'idempotency_key'> | undefined = mode === 'new' ? {
        incident_id: newId.trim(), title: newTitle.trim(),
        scope: { factory: factory.trim(), line_id: line.trim(), order_id: order.trim(), style_id: style.trim(), stage: 'sewing', unit: 'good_units' },
        window: { start: windowStart.trim(), end: windowEnd.trim() }, cutoff: cutoff.trim(), raw_text: rawText,
        source_system: sourceSystem.trim(), timezone: timezone.trim(), filename: file.name,
      } : undefined
      if (newIncident) body.scope = newIncident.scope
      return { body, result: await incidentApi.previewImport(body), newIncident }
    },
    onSuccess: ({ body, result, newIncident }) => setPreview({ body, result, newIncident, idempotencyKey: crypto.randomUUID() }),
  })
  const publish = useMutation({
    mutationFn: () => preview!.newIncident
      ? incidentApi.createIncident({ ...preview!.newIncident, preview_digest: preview!.result.preview_digest, idempotency_key: preview!.idempotencyKey })
      : incidentApi.publishImport(preview!.body, preview!.result.preview_digest, preview!.idempotencyKey),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['incidents'] }),
  })
  const changed = () => { setPreview(null); previewMutation.reset(); publish.reset() }
  const chooseIncident = (id: string) => {
    const item = incidents.data?.items.find((incident) => incident.id === id)
    setIncidentId(id)
    setBaseRevision(item?.revision ?? 1)
    setCutoff(item ? new Date(Date.parse(item.cutoff) + 30 * 60_000).toISOString() : '')
    changed()
  }

  return <div className="space-y-6">
    <div className="border-b border-zinc-200 pb-5"><Link to="/" className="inline-flex items-center gap-1.5 text-xs text-zinc-600 underline underline-offset-4"><ArrowLeft aria-hidden="true" className="size-3.5" />Incident library</Link><h1 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">Import incident evidence</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">Preview a local source file and its row diagnostics before adding it to an incident.</p></div>
    {capabilities.isPending ? <Skeleton className="h-32" /> : capabilities.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">Could not check permissions: {capabilities.error.message}</div> : !capabilities.data?.imports_enabled ? <div className="rounded border border-zinc-200 bg-white p-5 text-sm text-zinc-700">Sign in with an owner account to import source evidence.</div> : <>
      <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Publishing creates an immutable incident revision. Existing reports and reviews remain attached to their original revisions. A new baseline requires a new incident.</div>
      {incidents.isPending ? <Skeleton className="h-64" /> : incidents.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">Could not load incidents: {incidents.error.message}</div> : <form className="space-y-6 rounded-xl border border-zinc-200 bg-white p-5 sm:p-6" onSubmit={(event) => { event.preventDefault(); setPreview(null); previewMutation.mutate() }}>
        <div className="border-b border-zinc-200 pb-5"><h2 className="mb-4 text-base font-semibold">Incident destination</h2><label htmlFor="import-mode" className="mb-1 block text-xs font-medium">Import into</label><select id="import-mode" value={mode} onChange={(event) => { setMode(event.target.value as 'existing' | 'new'); changed() }} className="h-10 w-full max-w-sm rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2"><option value="existing">Existing incident · new revision</option><option value="new">New incident · baseline plan</option></select></div>
        {mode === 'existing' ? <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="import-incident" className="mb-1 block text-xs font-medium">Incident</label><select id="import-incident" required value={incidentId} onChange={(event) => chooseIncident(event.target.value)} className="h-10 w-full rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2"><option value="">Select an incident…</option>{incidents.data.items.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.title}</option>)}</select></div><div><label htmlFor="import-revision" className="mb-1 block text-xs font-medium">Base revision</label><select id="import-revision" required value={baseRevision} onChange={(event) => { setBaseRevision(Number(event.target.value)); changed() }} disabled={!selected} className="h-10 w-full rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2">{Array.from({ length: selected?.revision ?? 1 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>Revision {value}{value === selected?.revision ? ' · latest' : ' · historical'}</option>)}</select><p className="mt-1 text-xs text-zinc-600">Publication requires the latest revision.</p></div></div> : <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="new-id" className="mb-1 block text-xs font-medium">New incident ID</label><Input id="new-id" required maxLength={64} value={newId} onChange={(event) => { setNewId(event.target.value); changed() }} placeholder="INC-201" /></div><div><label htmlFor="new-title" className="mb-1 block text-xs font-medium">Incident title</label><Input id="new-title" required minLength={3} maxLength={200} value={newTitle} onChange={(event) => { setNewTitle(event.target.value); changed() }} placeholder="Delayed output on sewing line S2" /></div><div><label htmlFor="new-factory" className="mb-1 block text-xs font-medium">Factory</label><Input id="new-factory" required value={factory} onChange={(event) => { setFactory(event.target.value); changed() }} /></div><div><label htmlFor="new-line" className="mb-1 block text-xs font-medium">Sewing line</label><Input id="new-line" required value={line} onChange={(event) => { setLine(event.target.value); changed() }} /></div><div><label htmlFor="new-order" className="mb-1 block text-xs font-medium">Order ID</label><Input id="new-order" required value={order} onChange={(event) => { setOrder(event.target.value); changed() }} /></div><div><label htmlFor="new-style" className="mb-1 block text-xs font-medium">Style ID</label><Input id="new-style" required value={style} onChange={(event) => { setStyle(event.target.value); changed() }} /></div><div><label htmlFor="new-window-start" className="mb-1 block text-xs font-medium">Window start</label><Input id="new-window-start" required value={windowStart} onChange={(event) => { setWindowStart(event.target.value); changed() }} placeholder="2026-09-28T09:00:00+05:30" /></div><div><label htmlFor="new-window-end" className="mb-1 block text-xs font-medium">Window end</label><Input id="new-window-end" required value={windowEnd} onChange={(event) => { setWindowEnd(event.target.value); changed() }} placeholder="2026-09-28T12:00:00+05:30" /></div><p className="text-xs text-zinc-600 sm:col-span-2">Scope is sewing stage, good_units. The file must include matching 15-minute baseline plan records.</p></div>}
        <div className="grid gap-4 border-t border-zinc-200 pt-5 sm:grid-cols-2"><h2 className="text-base font-semibold sm:col-span-2">Source evidence</h2><div>{mode === 'existing' ? <><label htmlFor="import-profile" className="mb-1 block text-xs font-medium">Source profile</label><select id="import-profile" value={profile} onChange={(event) => { setProfile(event.target.value as IncidentImportBody['profile']); changed() }} className="h-10 w-full rounded border border-zinc-300 bg-white px-2 text-sm focus-visible:outline-2"><option value="operations-v1">Operations</option><option value="notes-v1">Notes</option><option value="production-v1">Production output</option></select></> : <p className="text-sm text-zinc-700"><strong>Source profile:</strong> Production baseline</p>}</div><div><label htmlFor="import-file" className="mb-1 block text-xs font-medium">Local file</label><Input id="import-file" type="file" required accept=".csv,.json,.jsonl" onChange={(event) => { const next = event.target.files?.[0] ?? null; setFile(next); setFileError(next && next.size > MAX_BYTES ? 'File exceeds 2 MiB.' : ''); changed() }} /><p className="mt-1 text-xs text-zinc-600">UTF-8 · CSV, JSON, or JSONL · up to 10,000 rows and 2 MiB</p>{fileError && <p role="alert" className="text-xs text-red-700">{fileError}</p>}</div></div>
        <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="import-source" className="mb-1 block text-xs font-medium">Source system</label><Input id="import-source" required value={sourceSystem} onChange={(event) => { setSourceSystem(event.target.value); changed() }} /></div><div><label htmlFor="import-timezone" className="mb-1 block text-xs font-medium">Source timezone</label><Input id="import-timezone" required value={timezone} onChange={(event) => { setTimezone(event.target.value); changed() }} /><p className="mt-1 text-xs text-zinc-600">IANA timezone, for example Asia/Kolkata</p></div></div>
        <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="import-cutoff" className="mb-1 block text-xs font-medium">Knowledge cutoff</label><Input id="import-cutoff" required value={cutoff} onChange={(event) => { setCutoff(event.target.value); changed() }} placeholder="2026-09-28T11:30:00+05:30" /><p className="mt-1 text-xs text-zinc-600">ISO timestamp with offset{mode === 'existing' ? '; later than the base revision’s cutoff.' : '; at or after window start.'}</p></div>{(mode === 'new' || profile === 'production-v1') && <div><label htmlFor="import-unit" className="mb-1 block text-xs font-medium">Production unit</label><Input id="import-unit" required value={unit} onChange={(event) => { setUnit(event.target.value); changed() }} /><p className="mt-1 text-xs text-zinc-600">Use good_units. Counts must be 15-minute deltas.</p></div>}</div>
        <Button type="submit" size="sm" disabled={!(mode === 'new' ? newId.trim() : incidentId) || !file || !!fileError || previewMutation.isPending}>{previewMutation.isPending ? 'Checking rows…' : 'Preview source'}</Button>
        {previewMutation.isError && <p role="alert" className="text-sm text-red-700">{previewMutation.error.message}</p>}
      </form>}
      {preview && <section className="space-y-4 rounded-xl border border-zinc-200 bg-white p-5 sm:p-6" aria-label="Import preview"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="text-base font-semibold">Preview: {preview.result.status}</h2><p className="mt-1 text-xs text-zinc-600">{preview.result.row_count} rows · {preview.result.plan_buckets.length} plan · {preview.result.output_buckets.length} output · {preview.result.events.length} events</p></div><span className="rounded bg-zinc-100 px-2 py-1 font-mono text-xs">{preview.result.raw_digest.slice(0, 12)}…</span></div>
        {preview.result.issues.length ? <div className="overflow-x-auto rounded border border-red-200"><table className="w-full min-w-[500px] text-left text-sm"><thead className="bg-red-50 text-xs uppercase text-red-900"><tr><th scope="col" className="px-3 py-2">Row</th><th scope="col" className="px-3 py-2">Field</th><th scope="col" className="px-3 py-2">Issue</th></tr></thead><tbody className="divide-y divide-red-100">{preview.result.issues.map((issue, index) => <tr key={index}><td className="px-3 py-2 tabular-nums">{issue.row}</td><td className="px-3 py-2">{issue.field}</td><td className="px-3 py-2">{issue.message}</td></tr>)}</tbody></table></div> : <p className="text-sm text-zinc-700">All rows passed validation. Publication is all or nothing.</p>}
        {preview.newIncident ? preview.result.plan_buckets.length === 0 && <p className="text-xs text-amber-800">A new incident requires baseline plan records in the file.</p> : preview.result.plan_buckets.length > 0 && <p className="text-xs text-amber-800">Existing baselines are immutable. This file cannot be published into the selected incident.</p>}
        <Button size="sm" disabled={preview.result.status !== 'READY' || (preview.newIncident ? preview.result.plan_buckets.length === 0 : preview.result.plan_buckets.length > 0) || publish.isPending} onClick={() => publish.mutate()}>{publish.isPending ? 'Publishing…' : preview.newIncident ? 'Create incident' : 'Publish new revision'}</Button>
        {publish.isError && <p role="alert" className="text-sm text-red-700">Publication failed: {publish.error.message}</p>}
        {publish.data && <p role="status" className="text-sm text-zinc-700">Revision {publish.data.revision} published. <Link className="underline underline-offset-4" to={`/incidents/${encodeURIComponent(publish.data.id)}?revision=${publish.data.revision}`}>Open the new investigation</Link>.</p>}
      </section>}
    </>}
  </div>
}
