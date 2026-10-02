import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { incidentApi, type AnalysisReport, type IncidentRevision } from '@/lib/incidents'
import { formatInstant } from '@/lib/status'
import { Button } from '@/components/ui/button'

type RecordChange = { id: string; kind: 'added' | 'removed' | 'changed'; correction: string | null }

function availableRecords(revision: IncidentRevision) {
  return [...revision.events, ...revision.plan_buckets, ...revision.output_buckets].filter((record) =>
    typeof record.available_at === 'string' && Date.parse(record.available_at) <= Date.parse(revision.cutoff))
}

function recordChanges(before: IncidentRevision, after: IncidentRevision): RecordChange[] {
  const left = new Map(availableRecords(before).map((record) => [record.id, record]))
  const right = new Map(availableRecords(after).map((record) => [record.id, record]))
  return [...new Set([...left.keys(), ...right.keys()])].flatMap((id): RecordChange[] => {
    const oldRecord = left.get(id)
    const newRecord = right.get(id)
    if (JSON.stringify(oldRecord) === JSON.stringify(newRecord)) return []
    return [{ id, kind: !oldRecord ? 'added' : !newRecord ? 'removed' : 'changed', correction: typeof newRecord?.supersedes_id === 'string' ? newRecord.supersedes_id : typeof newRecord?.supersedes === 'string' ? newRecord.supersedes : null }]
  })
}

export function RevisionComparison({ incident, report }: { incident: IncidentRevision; report: AnalysisReport }) {
  const [open, setOpen] = useState(false)
  const earlier = incident.available_revisions.filter((value) => value < incident.revision)
  const [chosen, setChosen] = useState<number | null>(null)
  const baseline = chosen ?? earlier.at(-1)
  const comparison = useQuery({
    queryKey: ['revision-comparison', incident.id, baseline],
    enabled: open && baseline !== undefined,
    queryFn: async () => {
      if (baseline === undefined) throw new Error('Choose an earlier revision.')
      const revision = await incidentApi.revision(incident.id, baseline)
      const analysis = await incidentApi.analyze(incident.id, baseline)
      if (analysis.execution_kind === 'saved_deterministic') throw new Error('A live earlier revision is needed for comparison.')
      return { revision, analysis }
    },
    retry: false,
  })
  if (!earlier.length || report.execution_kind === 'saved_deterministic') return null
  const changes = comparison.data ? recordChanges(comparison.data.revision, incident) : []
  const previous = comparison.data?.analysis
  return <section className="rounded border border-zinc-200 bg-white p-4 print:hidden" aria-label="Revision comparison">
    <Button variant="outline" size="sm" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'Hide revision comparison' : 'Compare revisions'}</Button>
    {open && <div className="mt-4 space-y-4">
      <h2 className="text-lg font-semibold">What changed in revision {incident.revision}?</h2>
      <div><label htmlFor="compare-revision" className="mr-2 text-xs font-medium">Compare with</label><select id="compare-revision" value={baseline} onChange={(event) => setChosen(Number(event.target.value))} className="rounded border p-2 text-sm">{earlier.map((value) => <option key={value} value={value}>Revision {value}</option>)}</select></div>
      {comparison.isPending ? <p role="status" className="text-sm">Loading earlier evidence and calculation…</p> : comparison.isError ? <p role="alert" className="text-sm text-red-800">{comparison.error.message}</p> : previous && <>
        <p className="text-xs text-zinc-600">Evidence available by {formatInstant(previous.cutoff)} compared with {formatInstant(report.cutoff)}. Later records stay excluded from the earlier calculation.</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Metrics across evidence revisions</caption><thead><tr><th className="p-2" scope="col">Calculation</th><th className="p-2" scope="col">Revision {baseline}</th><th className="p-2" scope="col">Revision {incident.revision}</th></tr></thead><tbody>{(['planned', 'observed', 'shortfall', 'blocked_minutes'] satisfies (keyof AnalysisReport['metrics'])[]).map((key) => <tr key={key} className="border-t"><th scope="row" className="p-2 font-normal">{key.replaceAll('_', ' ')}</th><td className="p-2">{previous.metrics[key] ?? 'Unknown'}</td><td className="p-2">{report.metrics[key] ?? 'Unknown'}</td></tr>)}</tbody></table></div>
        <p className="text-xs text-zinc-600">{(report.metrics.inputs ?? []).filter((input) => !(previous.metrics.inputs ?? []).some((old) => Date.parse(old.start) === Date.parse(input.start) && Date.parse(old.end) === Date.parse(input.end))).length} newly comparable production intervals. New intervals change the calculation window; correction records can change an existing observation.</p>
        <h3 className="text-sm font-medium">Source record changes</h3>
        {changes.length ? <ul className="space-y-1 text-xs">{changes.map((change) => <li key={change.id} className="rounded bg-zinc-50 p-2"><span className="font-medium">{change.kind}: {change.id}</span>{change.correction && <span> · corrects {change.correction}; original record retained</span>}</li>)}</ul> : <p className="text-xs">No source record changes available at these cutoffs.</p>}
        <h3 className="text-sm font-medium">Explanation changes</h3>
        {report.hypotheses.map((hypothesis) => {
          const old = previous.hypotheses.find((item) => item.category === hypothesis.category)
          return <p key={hypothesis.category} className="text-xs">{hypothesis.category.replaceAll('_', ' ')}: {old?.status ?? 'Absent'} → {hypothesis.status}{old?.next_check !== hypothesis.next_check && <span> · next check updated: {hypothesis.next_check}</span>}</p>
        })}
        {previous.hypotheses.filter((old) => !report.hypotheses.some((item) => item.category === old.category)).map((old) => <p key={old.category} className="text-xs">{old.category.replaceAll('_', ' ')}: {old.status} → absent in this revision</p>)}
        <p className="rounded bg-amber-50 p-3 text-xs text-amber-950">Review proposals against revision {incident.revision}. Earlier approvals remain attached to their original report and do not approve the updated evidence.</p>
      </>}
    </div>}
  </section>
}
