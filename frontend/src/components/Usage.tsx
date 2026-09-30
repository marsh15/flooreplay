import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { incidentApi } from '@/lib/incidents'
export function UsagePanel() {
  const { user } = useAuth()
  const usage = useQuery({ queryKey: ['usage'], queryFn: incidentApi.usage, enabled: user?.role === 'owner', refetchInterval: 30000 })
  if (user?.role !== 'owner') return null
  return <details className="rounded border bg-white p-3 text-xs"><summary className="cursor-pointer font-medium">Owner API allowance</summary>{usage.data ? <div className="mt-3 space-y-2"><p>₹{usage.data.available_inr.toFixed(2)} available · ₹{usage.data.committed_inr.toFixed(2)} committed · ₹{usage.data.total_ceiling_inr} ceiling</p><p>{usage.data.active_operations} active provider operations</p>{Object.entries(usage.data.purpose_available_inr).map(([purpose, amount]) => <p key={purpose}>{purpose}: ₹{amount.toFixed(2)} available</p>)}<p>Uncertain calls keep their allowance reserved. The ledger uses the configured accounting conversion.</p><ul>{usage.data.entries.map((entry) => <li key={entry.id}>{entry.operation} · {entry.status} · ₹{(entry.status === 'SETTLED' ? entry.charged_inr : entry.reserved_inr).toFixed(2)}</li>)}</ul></div> : <p className="mt-2">{usage.error?.message ?? 'Loading allowance…'}</p>}</details>
}
