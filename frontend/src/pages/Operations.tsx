import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { Button } from '@/components/ui/button'
import { getOperations } from '@/lib/operations'

export function OperationsPage() {
  const { user } = useAuth()
  const [query, setQuery] = useState('')
  const report = useQuery({ queryKey: ['operations', user?.id, query], queryFn: () => getOperations(query), enabled: user?.role === 'owner', retry: false })
  return <div className="space-y-6">
    <header><h1 className="text-2xl font-semibold">Operational evidence</h1><p className="mt-2 text-sm text-zinc-600">Find your request receipts, provider operations and retained reservations. Source text and questions are excluded.</p></header>
    {user?.role !== 'owner' ? <p>Sign in as an owner to inspect your operations.</p> : <>
      <label className="block text-sm">Search request, incident or operation ID<input className="mt-1 block w-full rounded border p-2" value={query} onChange={(event) => setQuery(event.target.value)} /></label><Button variant="outline" onClick={() => void report.refetch()}>Refresh evidence</Button>
      {report.isPending && <p role="status">Loading operational evidence…</p>}{report.error && <p role="alert">{report.error.message}</p>}
      {report.data && <>
        <section className="space-y-3"><h2 className="font-semibold">Alerts requiring action</h2>{report.data.alerts.length ? report.data.alerts.map((alert, index) => <article key={index} className="rounded border border-amber-300 p-4"><h3>{alert.severity} · {alert.code}</h3><p className="break-all font-mono text-xs">{alert.operation_id ?? alert.request_id}</p><p className="mt-2 text-sm">{alert.remediation}</p><a className="mt-2 inline-block text-xs underline" href="#operations-runbook">Open response runbook</a></article>) : <p>No alerts in this owner scope and receipt window.</p>}</section>
        <section className="space-y-3"><h2 className="font-semibold">Durable AI operations</h2><p className="text-sm">{report.data.recovery_policy}</p>{report.data.operations.map((operation) => <article key={operation.id} className="rounded border p-4"><h3>{operation.task} · {operation.status}</h3><p className="break-all text-xs">Operation: {operation.id}<br />Request: {operation.request_id ?? 'Not recorded'}<br />Incident: {operation.incident_id ?? 'Not recorded'} · Analysis: {operation.analysis_id}<br />Latency: {operation.elapsed_seconds == null ? 'Not terminal or not recorded' : `${operation.elapsed_seconds}s`}</p><details><summary className="mt-2 text-xs">Provider receipt identifiers</summary><pre className="overflow-x-auto text-xs">{JSON.stringify(operation.provider_receipts, null, 2)}</pre></details></article>)}</section>
        <section><h2 className="font-semibold">Request receipts and import health</h2><div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">Actor-scoped request receipts</caption><thead><tr><th className="p-2">Request ID</th><th className="p-2">Route</th><th className="p-2">Status</th><th className="p-2">Latency</th></tr></thead><tbody>{report.data.events.map((event) => <tr key={event.request_id} className="border-t"><td className="p-2 font-mono">{event.request_id}</td><td className="p-2">{event.method} {event.route}</td><td className="p-2">{event.status_code} {event.failure_category}</td><td className="p-2">{event.elapsed_seconds}s</td></tr>)}</tbody></table></div></section>
        <section><h2 className="font-semibold">Your allowance reservations</h2>{report.data.allowance_entries.map((entry) => <p className="break-all text-xs" key={entry.id}>{entry.id} · {entry.operation} · {entry.status} · reserved ₹{entry.reserved_inr.toFixed(2)} · charged ₹{entry.charged_inr.toFixed(2)}</p>)}<p className="mt-2 text-xs">The shared ceiling is enforced when reserving paid calls; this view contains your entries only.</p></section>
        <section id="operations-runbook" className="rounded border p-4"><h2 className="font-semibold">Response runbook</h2><p className="mt-2 text-sm">For a failed request, search its ID in host logs and check readiness and the deployed commit. For uncertain provider work, compare receipt IDs against provider billing; retain the reservation until reconciliation. Use the deterministic investigation while resolving failures. Escalate unresolved failures to the application owner.</p></section><ul className="list-disc pl-5 text-xs">{report.data.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
      </>}
    </>}
  </div>
}
