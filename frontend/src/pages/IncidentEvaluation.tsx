import { useQuery } from '@tanstack/react-query'
import { incidentApi, type IncidentEvaluationReport } from '@/lib/incidents'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

const title = (key: string) => key.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())

function valueText(value: unknown): string {
  if (value == null) return 'Not reported'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(valueText).join(', ')
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${title(key)}: ${valueText(item)}`).join(' · ')
}

function Metric({ name, data }: { name: string; data: unknown }) {
  const detail = data && typeof data === 'object' && !Array.isArray(data) ? data as Record<string, unknown> : null
  const shown = detail?.value ?? detail?.score ?? detail?.rate ?? data
  const numerator = detail?.numerator ?? detail?.passed ?? detail?.correct
  const denominator = detail?.denominator ?? detail?.total ?? detail?.evaluated
  const display = denominator === 0 && numerator == null ? 'Not evaluated' : detail?.value == null && detail?.score == null && detail?.rate == null && numerator != null && denominator != null ? `${valueText(numerator)} / ${valueText(denominator)}` : valueText(shown)
  return <div className="rounded border border-zinc-200 bg-white p-4">
    <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-600">{title(name)}</h3>
    <p className="mt-2 text-2xl font-semibold tabular-nums">{display}</p>
    <p className="mt-1 text-xs text-zinc-500">{denominator != null ? `Denominator: ${valueText(denominator)}${denominator === 0 ? ' · no measured cases' : ''}` : 'Denominator not reported'}</p>
    {detail?.unit != null && <p className="mt-1 text-xs text-zinc-500">Unit: {valueText(detail.unit)}</p>}
  </div>
}

function RetrievalComparison({ data }: { data: NonNullable<IncidentEvaluationReport['baseline_comparison']> }) {
  const rows = [
    { name: 'Baseline · title only', value: data.baseline, failures: data.failed_baseline_queries },
    { name: 'Candidate · cutoff-visible evidence card', value: data.candidate, failures: data.failed_candidate_queries },
  ]
  return <section className="space-y-3">
    <div className="border-b border-zinc-200 pb-2"><h2 className="text-base font-semibold">Common-label retrieval comparison</h2><p className="mt-0.5 text-xs text-zinc-500">Both configurations use the same {data.label_revision} relevance labels. Counts are top-five results.</p></div>
    <div className="overflow-x-auto rounded border border-zinc-200 bg-white"><table className="w-full min-w-[600px] text-left text-sm"><caption className="sr-only">Title-only baseline and cutoff-visible evidence-card retrieval measured against common labels</caption><thead className="border-b bg-zinc-50 text-xs uppercase text-zinc-500"><tr><th scope="col" className="px-4 py-2">Retriever</th><th scope="col" className="px-4 py-2">Hit at 5</th><th scope="col" className="px-4 py-2">Recall at 5</th></tr></thead><tbody className="divide-y divide-zinc-100">{rows.map((row) => <tr key={row.name}><th scope="row" className="px-4 py-3 text-sm font-medium">{row.name}<span className="mt-1 block font-mono text-xs font-normal text-zinc-500">{row.value.configuration}</span></th><td className="px-4 py-3 font-mono text-sm tabular-nums">{row.value.hit_at_5.passed} / {row.value.hit_at_5.total}</td><td className="px-4 py-3 font-mono text-sm tabular-nums">{row.value.recall_at_5.passed} / {row.value.recall_at_5.total}</td></tr>)}</tbody></table></div>
    <dl className="grid gap-3 text-xs sm:grid-cols-2">{rows.map((row) => <div key={row.name} className="rounded border border-zinc-200 bg-white p-3"><dt className="font-medium text-zinc-700">Failed queries · {row.name}</dt><dd className="mt-1 text-zinc-600">{row.failures.length ? row.failures.join(', ') : 'None in this labeled set'}</dd></div>)}</dl>
  </section>
}

export function IncidentEvaluationPage() {
  const report = useQuery({ queryKey: ['incident-evaluation', 'incident-core-v1'], queryFn: () => incidentApi.evaluationReport('incident-core-v1'), retry: false })
  return <div className="space-y-7">
    <header className="border-b border-zinc-200 pb-5"><p className="text-xs font-semibold uppercase tracking-widest text-amber-700">Engineering view</p><h1 className="mt-2 text-2xl font-semibold tracking-tight">Incident evaluation lab</h1><p className="mt-1 max-w-2xl text-sm text-zinc-600">Measured quality on a pinned synthetic dataset. Failures and limitations stay visible alongside scores.</p></header>
    {report.isPending ? <div className="space-y-3" aria-busy="true" aria-label="Loading evaluation report"><Skeleton className="h-20" /><Skeleton className="h-36" /><Skeleton className="h-48" /></div> : report.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-5"><h2 className="text-sm font-semibold text-red-900">Evaluation report unavailable</h2><p className="mt-1 text-sm text-red-800">{report.error.message}</p><Button className="mt-3" variant="outline" size="sm" onClick={() => report.refetch()}>Retry</Button></div> : <>
      {report.data.execution_kind === 'saved_evaluation' && <p role="status" className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">API unavailable. Showing the bundled saved evaluation report.</p>}
      <section className="rounded border border-zinc-200 bg-white p-4"><h2 className="text-sm font-semibold">Pinned run</h2><dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4"><div><dt className="text-zinc-500">Dataset revision</dt><dd className="mt-1 font-mono">{report.data.dataset_revision}</dd></div><div><dt className="text-zinc-500">Label revision</dt><dd className="mt-1 font-mono">{report.data.label_revision}</dd></div><div><dt className="text-zinc-500">Cases</dt><dd className="mt-1 font-mono">{report.data.case_count}</dd></div><div><dt className="text-zinc-500">Execution mode</dt><dd className="mt-1 font-mono">{report.data.execution_kind ? title(report.data.execution_kind) : 'Not reported'}</dd></div></dl><p className="mt-3 border-t border-zinc-100 pt-3 text-xs text-zinc-600"><strong>Configuration:</strong> {valueText(report.data.configuration)}</p>{report.data.runtime != null && <p className="mt-1 text-xs text-zinc-600"><strong>Runtime:</strong> {valueText(report.data.runtime)}</p>}{report.data.hardware != null && <p className="mt-1 text-xs text-zinc-600"><strong>Hardware:</strong> {valueText(report.data.hardware)}</p>}{report.data.model != null && <p className="mt-1 text-xs text-zinc-600"><strong>Model:</strong> {valueText(report.data.model)}</p>}</section>

      <section className="space-y-3"><div className="border-b border-zinc-200 pb-2"><h2 className="text-base font-semibold">Measured results</h2><p className="mt-0.5 text-xs text-zinc-500">Each metric states its reported denominator. Missing denominators are shown explicitly.</p></div>{Object.keys(report.data.metrics).length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(report.data.metrics).map(([name, data]) => <Metric key={name} name={name} data={data} />)}</div> : <p className="rounded border border-dashed p-5 text-sm text-zinc-600">No metrics were published in this report.</p>}</section>

      {report.data.baseline_comparison && <RetrievalComparison data={report.data.baseline_comparison} />}

      <section className="space-y-3"><div className="border-b border-zinc-200 pb-2"><h2 className="text-base font-semibold">Failed cases</h2><p className="mt-0.5 text-xs text-zinc-500">{report.data.failures.length} reported failures</p></div>{report.data.failures.length ? <ul className="space-y-2">{report.data.failures.map((failure, index) => <li key={index} className="rounded border border-amber-200 bg-amber-50 p-4"><h3 className="text-sm font-semibold">{valueText(failure.case ?? failure.case_id ?? failure.id ?? `Case ${index + 1}`)}</h3><dl className="mt-2 space-y-1 text-xs text-zinc-700">{Object.entries(failure).filter(([key]) => !['case', 'case_id', 'id'].includes(key)).map(([key, value]) => <div key={key}><dt className="inline font-medium">{title(key)}: </dt><dd className="inline">{valueText(value)}</dd></div>)}</dl></li>)}</ul> : <p className="rounded border border-zinc-200 bg-white p-5 text-sm text-zinc-600">No failures are listed. Check the metric denominators and limitations before drawing conclusions.</p>}</section>

      {report.data.cases.length > 0 && <section className="space-y-3"><div className="border-b border-zinc-200 pb-2"><h2 className="text-base font-semibold">Case results</h2><p className="mt-0.5 text-xs text-zinc-500">All {report.data.cases.length} published case records</p></div><div className="overflow-x-auto rounded border border-zinc-200 bg-white"><table className="w-full min-w-[640px] text-left text-sm"><thead className="border-b bg-zinc-50 text-xs uppercase text-zinc-500"><tr><th scope="col" className="px-4 py-2">Case</th><th scope="col" className="px-4 py-2">Result</th><th scope="col" className="px-4 py-2">Details</th></tr></thead><tbody className="divide-y divide-zinc-100">{report.data.cases.map((item, index) => <tr key={index}><td className="px-4 py-3 font-mono text-xs">{valueText(item.incident_id ?? item.case_id ?? item.id ?? index + 1)}</td><td className="px-4 py-3">{valueText(item.status ?? item.verdict ?? item.result ?? (item.numeric_pass === true && item.category_pass === true ? 'PASS' : 'FAIL'))}</td><td className="px-4 py-3 text-xs text-zinc-600">{Object.entries(item).filter(([key]) => !['incident_id', 'case_id', 'id', 'status', 'verdict', 'result'].includes(key)).map(([key, value]) => `${title(key)}: ${valueText(value)}`).join(' · ')}</td></tr>)}</tbody></table></div></section>}

      {!!report.data.retrieval_cases?.length && <section className="space-y-3"><div className="border-b border-zinc-200 pb-2"><h2 className="text-base font-semibold">Retrieval checks</h2><p className="mt-0.5 text-xs text-zinc-500">Relevant labels and retrieved IDs from live lexical search</p></div><div className="overflow-x-auto rounded border border-zinc-200 bg-white"><table className="w-full min-w-[640px] text-left text-sm"><thead className="border-b bg-zinc-50 text-xs uppercase text-zinc-500"><tr><th scope="col" className="px-4 py-2">Query</th><th scope="col" className="px-4 py-2">Relevant</th><th scope="col" className="px-4 py-2">Retrieved</th><th scope="col" className="px-4 py-2">Hits</th></tr></thead><tbody className="divide-y divide-zinc-100">{report.data.retrieval_cases.map((item, index) => <tr key={index}><td className="px-4 py-3">{valueText(item.query)}</td><td className="px-4 py-3 font-mono text-xs">{valueText(item.relevant)}</td><td className="px-4 py-3 font-mono text-xs">{valueText(item.retrieved)}</td><td className="px-4 py-3 font-mono text-xs">{valueText(item.hits)}</td></tr>)}</tbody></table></div></section>}

      <section className="space-y-3"><div className="border-b border-zinc-200 pb-2"><h2 className="text-base font-semibold">Limits of this evaluation</h2></div>{report.data.limitations.length ? <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-700">{report.data.limitations.map((limit, index) => <li key={index}>{limit}</li>)}</ul> : <p className="text-sm text-zinc-600">No limitations were supplied with this report.</p>}</section>
    </>}
  </div>
}
