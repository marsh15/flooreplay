import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { incidentApi } from '@/lib/incidents'
import { Button } from '@/components/ui/button'

export function UsagePanel() {
  const { user } = useAuth()
  const usage = useQuery({ queryKey: ['usage'], queryFn: incidentApi.usage, enabled: user?.role === 'owner', refetchInterval: 30000 })
  if (user?.role !== 'owner') return null
  return (
    <details className="mb-6 rounded-lg border bg-card text-xs print:hidden">
      <summary className="cursor-pointer rounded-lg px-4 py-3 font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">Owner API allowance</summary>
      {usage.data ? (
        <div className="space-y-4 border-t px-4 py-4">
          <dl className="grid grid-cols-3 gap-3 tabular-nums">
            <div><dt className="text-muted-foreground">Available</dt><dd className="mt-1 font-medium">₹{usage.data.available_inr.toFixed(2)}</dd></div>
            <div><dt className="text-muted-foreground">Committed</dt><dd className="mt-1 font-medium">₹{usage.data.committed_inr.toFixed(2)}</dd></div>
            <div><dt className="text-muted-foreground">Ceiling</dt><dd className="mt-1 font-medium">₹{usage.data.total_ceiling_inr}</dd></div>
          </dl>
          <p>{usage.data.active_operations} active provider operations</p>
          <dl className="space-y-2">{Object.entries(usage.data.purpose_available_inr).map(([purpose, amount]) => <div key={purpose} className="flex flex-wrap justify-between gap-2"><dt>{purpose.replaceAll('_', ' ')}</dt><dd className="tabular-nums">₹{amount.toFixed(2)} available</dd></div>)}</dl>
          <p className="leading-relaxed text-muted-foreground">Uncertain calls keep their allowance reserved. The ledger uses the configured accounting conversion.</p>
          {usage.data.entries.length ? <ul className="divide-y border-t">{usage.data.entries.map((entry) => <li className="flex flex-wrap items-center justify-between gap-2 py-2.5" key={entry.id}><span className="break-all">{entry.operation} · {entry.status}</span><span className="tabular-nums">₹{(entry.status === 'SETTLED' ? entry.charged_inr : entry.reserved_inr).toFixed(2)}</span></li>)}</ul> : <p className="text-muted-foreground">No provider operations recorded.</p>}
        </div>
      ) : usage.isError ? <div role="alert" className="space-y-2 border-t p-4"><p className="text-red-800">Allowance could not be loaded: {usage.error.message}</p><Button size="sm" variant="outline" onClick={() => void usage.refetch()}>Retry allowance</Button></div> : <p role="status" className="border-t p-4 text-muted-foreground">Loading allowance…</p>}
    </details>
  )
}
