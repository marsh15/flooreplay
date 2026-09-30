import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '@/lib/api'
import { incidentApi } from '@/lib/incidents'
import { formatInstant } from '@/lib/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

export function IncidentLibraryPage() {
  const [query, setQuery] = useState('')
  const incidents = useQuery({ queryKey: ['incidents'], queryFn: incidentApi.list })
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities, staleTime: 60_000 })
  const saved = incidents.data?.execution_kind === 'saved_deterministic'
  const search = useQuery({ queryKey: ['incident-search', query], queryFn: () => incidentApi.search(query.trim()), enabled: !!query.trim() && !saved && !!incidents.data, retry: false })
  const items = incidents.data?.items ?? []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-zinc-200 pb-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-amber-700">Manufacturing incident intelligence</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Incident library</h1>
          <p className="mt-1 max-w-2xl text-sm text-zinc-600">Investigate a line delay from recorded production, operational evidence, and human review.</p>
        </div>
        <span className="rounded border border-zinc-200 bg-white px-3 py-1.5 text-xs text-zinc-600">Synthetic data · deterministic analysis</span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="w-full max-w-sm">
          <label htmlFor="incident-search" className="mb-1 block text-xs font-medium text-zinc-700">Find an incident</label>
          <Input id="incident-search" type="search" placeholder="Search incident or line" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        {incidents.data && !query && <p className="text-xs text-zinc-500" role="status">{items.length} incidents</p>}
        {capabilities.data?.imports_enabled && <Link to="/incidents/imports" className="rounded border border-zinc-300 bg-white px-3 py-2 text-xs font-medium text-zinc-700 hover:bg-zinc-50 focus-visible:outline-2">Import incident evidence</Link>}
      </div>

      {saved && <div role="status" className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">API unavailable. Showing one bundled saved deterministic investigation. Live search, review, and OpenAI drafts are unavailable.</div>}

      {incidents.isPending ? (
        <div className="space-y-2" aria-label="Loading incidents" aria-busy="true"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
      ) : incidents.isError ? (
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-5">
          <h2 className="text-sm font-semibold text-red-900">Incident library unavailable</h2>
          <p className="mt-1 text-sm text-red-800">{incidents.error.message}</p>
          <Button className="mt-3" size="sm" variant="outline" onClick={() => incidents.refetch()}>Retry</Button>
        </div>
      ) : query.trim() ? (
        saved ? <div className="rounded border border-dashed border-amber-300 bg-white p-5 text-sm text-zinc-700">Live search is unavailable while the API is offline. Clear the search to open the bundled investigation.</div> : search.isPending ? <Skeleton className="h-24" /> : search.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-5 text-sm text-red-800">Live search unavailable: {search.error.message}</div> : search.data.items.length ? <div className="space-y-2"><p className="text-xs text-zinc-500">{search.data.items.length} live lexical results</p>{search.data.items.map((item) => <article key={`${item.id}-${item.revision}`} className="rounded border border-zinc-200 bg-white p-4"><Link className="text-sm font-medium underline underline-offset-4" to={`/incidents/${encodeURIComponent(item.id)}?revision=${item.revision}`}>{item.title}</Link><p className="mt-1 text-xs text-zinc-600">{item.line} · {item.match_reason}</p>{item.differences.length > 0 && <p className="mt-1 text-xs text-zinc-500">{item.differences.join(' ')}</p>}</article>)}</div> : <div className="rounded border border-dashed border-zinc-300 bg-white p-5 text-sm text-zinc-600">No live search results match this query.</div>
      ) : items.length === 0 ? (
        <div className="rounded border border-dashed border-zinc-300 bg-white p-10 text-center text-sm text-zinc-600">No incidents are available yet.</div>
      ) : (
        <div className="overflow-x-auto rounded border border-zinc-200 bg-white">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500"><tr>
              <th scope="col" className="px-4 py-3 font-medium">Incident / line</th>
              <th scope="col" className="px-4 py-3 font-medium">Investigation window</th>
              <th scope="col" className="px-4 py-3 font-medium">Observed shortfall</th>
              <th scope="col" className="px-4 py-3 font-medium">Evidence</th>
              <th scope="col" className="px-4 py-3 font-medium">Analysis</th>
            </tr></thead>
            <tbody className="divide-y divide-zinc-100">
              {items.map((item, index) => <tr key={item.id} className={index === 0 ? 'bg-amber-50/40' : ''}>
                <td className="px-4 py-4"><Link className="font-medium text-zinc-900 underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-900 focus-visible:outline-2" to={`/incidents/${encodeURIComponent(item.id)}?revision=${item.revision}`}>{item.title}</Link><span className="mt-1 block text-xs text-zinc-500">{item.line} · revision {item.revision}{index === 0 ? ' · featured investigation' : ''}</span></td>
                <td className="px-4 py-4 text-zinc-700">{formatInstant(item.window_start)}<span className="block text-xs text-zinc-500">to {formatInstant(item.window_end)}</span></td>
                <td className="px-4 py-4 font-medium tabular-nums">{item.shortfall == null ? 'Unavailable' : `${item.shortfall} good units`}</td>
                <td className="px-4 py-4 text-zinc-600">{item.evidence_completeness ?? 'See report'}</td>
                <td className="px-4 py-4"><span className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-700">{item.status}</span></td>
              </tr>)}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-zinc-500">A report uses evidence available by its knowledge cutoff. Later records create a new revision and preserve the earlier view.</p>
    </div>
  )
}
