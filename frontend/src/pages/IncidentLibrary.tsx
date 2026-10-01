import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ArrowUpRight, Search } from 'lucide-react'
import { api } from '@/lib/api'
import { useAuth } from '@/components/Auth'
import { incidentApi } from '@/lib/incidents'
import type { IncidentSummary } from '@/lib/incidents'
import { formatInstant } from '@/lib/status'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

const PAGE_SIZE = 12
const incidentLink = (item: Pick<IncidentSummary, 'id' | 'revision'>) => `/incidents/${encodeURIComponent(item.id)}?revision=${item.revision}`
const calculationLabel = (status: string) => `Calculation ${status.toLowerCase().replaceAll('_', ' ')}`
const reviewLabel = (item: IncidentSummary) => item.last_reviewed_revision == null
  ? 'No recorded human review'
  : item.last_reviewed_revision === item.revision ? 'Current revision reviewed' : `Review applies to revision ${item.last_reviewed_revision}`

const evidenceLabel = (state: string) => state === 'ALL_REPORTED_SOURCES_AVAILABLE' ? 'All reported sources available' : state.toLowerCase().replaceAll('_', ' ')
const investigationLabel = (item: IncidentSummary, authenticated: boolean) => authenticated && item.workflow ? item.workflow.investigation_state === 'RESOLVED' ? 'Resolved at this revision' : 'Open investigation · cause not confirmed by this label' : 'Sign in to see investigation state'
const actionLabel = (item: IncidentSummary, authenticated: boolean) => authenticated && item.workflow ? item.workflow.open_action_count ? `${item.workflow.open_action_count} open actions` : item.workflow.action_state === 'NO_RECORDED_ACTIONS' ? 'No recorded actions' : 'No open actions · resolution separate' : 'Sign in to see action state'

export function IncidentLibraryPage() {
  const { user } = useAuth()
  const [query, setQuery] = useState('')
  const [view, setView] = useState<'cases' | 'engineering'>('cases')
  const [line, setLine] = useState('')
  const [calculation, setCalculation] = useState('')
  const [date, setDate] = useState('')
  const [evidence, setEvidence] = useState('')
  const [assignee, setAssignee] = useState('')
  const [actions, setActions] = useState('')
  const [page, setPage] = useState(1)
  const incidents = useQuery({ queryKey: ['incidents', user?.id ?? 'public'], queryFn: incidentApi.list })
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities, staleTime: 60_000 })
  const saved = incidents.data?.execution_kind === 'saved_deterministic'
  const search = useQuery({ queryKey: ['incident-search', query, view], queryFn: () => incidentApi.search(query.trim(), view), enabled: !!query.trim() && !saved && !!incidents.data, retry: false })
  const items = incidents.data?.items ?? []
  const hero = items.find((item) => item.id === 'INC-001')
  const fixtures = items.filter((item) => item.library_group === 'engineering_fixture')
  const cases = items.filter((item) => item.library_group !== 'engineering_fixture')
  const selected = view === 'engineering' ? fixtures : cases
  const filtered = selected.filter((item) => (!line || item.line === line) && (!calculation || item.status === calculation) && (!date || item.window_start.slice(0, 10) === date) && (!evidence || (item.evidence_state ?? 'UNKNOWN') === evidence) && (saved || !user || ((!assignee || item.workflow?.assignees.some((person) => person.id === assignee)) && (!actions || (actions === 'open' ? (item.workflow?.open_action_count ?? 0) > 0 : item.workflow?.open_action_count === 0)))))
  const eligibleIds = new Set(filtered.map((item) => item.id))
  const searchItems = search.data?.items.filter((item) => eligibleIds.has(item.id)) ?? []
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)
  const selectClass = 'min-h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-zinc-200 pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Incident library</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">Understand a production delay, check its source records, and decide what needs human follow-up.</p>
        </div>
        <span className="text-xs leading-5 text-zinc-600">Demo examples use synthetic data · deterministic analysis</span>
      </div>

      {hero && <section aria-labelledby="first-investigation" className="rounded-xl border border-zinc-200 bg-zinc-50 p-5 sm:p-6">
        <h2 id="first-investigation" className="text-lg font-semibold tracking-tight">Start with one production delay</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-600">Line S4 started late. Follow the recorded output, inspect the fabric-transfer evidence, and compare what was known before and after a later maintenance update.</p>
        <ol className="my-4 grid gap-3 text-sm text-zinc-700 sm:grid-cols-3">
          <li><span className="font-medium">1. Measure the gap.</span> Compare planned and recorded good units.</li>
          <li><span className="font-medium">2. Check the explanation.</span> Open the cited records and missing sources.</li>
          <li><span className="font-medium">3. Choose a next check.</span> Review the evidence before approving a proposal.</li>
        </ol>
        <Link to={incidentLink(hero)} className="inline-flex min-h-10 items-center gap-2 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2">Start the example investigation<ArrowUpRight aria-hidden="true" className="size-4" /></Link>
        <div className="mt-4"><Link to="/demo" className="text-sm font-medium underline underline-offset-4">Try the safe action demo</Link><p className="mt-1 text-xs leading-5 text-zinc-600">No account needed. Complete a browser-only simulation and reset it without changing shared records.</p></div>
        <p className="mt-3 text-xs leading-5 text-zinc-600">The knowledge cutoff means “records available by this time.” Later information stays in a separate revision. Finish by checking whether the proposed next step is supported; a complete calculation does not confirm a cause or resolve an incident.</p>
      </section>}

      {!hero && <section className="rounded-xl border border-zinc-200 bg-zinc-50 p-5"><Link to="/demo" className="text-sm font-medium underline underline-offset-4">Try the safe action demo</Link><p className="mt-1 text-xs leading-5 text-zinc-600">No account needed. Complete a browser-only simulation and reset it without changing shared records.</p></section>}

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="w-full max-w-sm">
          <label htmlFor="incident-search" className="mb-1 block text-xs font-medium text-zinc-700">Search incident evidence</label>
          <div className="relative"><Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-500" /><Input className="pl-9" id="incident-search" type="search" placeholder="Search live incident evidence" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
        </div>
        {capabilities.data?.imports_enabled && <Link to="/incidents/imports" className="inline-flex min-h-10 items-center gap-2 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 focus-visible:outline-2">Import incident evidence<ArrowUpRight aria-hidden="true" className="size-4" /></Link>}
      </div>

      {saved && <div role="status" className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">API unavailable. Showing bundled saved demo cases. The example investigation is available offline. Live search, review, and OpenAI drafts are unavailable.</div>}

      {incidents.isPending ? (
        <div className="space-y-2" aria-label="Loading incidents" aria-busy="true"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
      ) : incidents.isError ? (
        <div role="alert" className="rounded border border-red-200 bg-red-50 p-5">
          <h2 className="text-sm font-semibold text-red-900">Incident library unavailable</h2>
          <p className="mt-1 text-sm text-red-800">{incidents.error.message}</p>
          <Button className="mt-3" size="sm" variant="outline" onClick={() => incidents.refetch()}>Retry</Button>
        </div>
      ) : query.trim() ? (
        saved ? <div className="rounded border border-dashed border-amber-300 bg-white p-5 text-sm text-zinc-700">Live search is unavailable while the API is offline. Clear the search to browse the saved cases. <Button size="sm" variant="outline" className="mt-3 block" onClick={() => setQuery('')}>Clear search</Button></div> : search.isPending ? <Skeleton className="h-24" /> : search.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-5 text-sm text-red-800">Live search unavailable: {search.error.message}</div> : searchItems.length ? <div className="space-y-2"><p className="text-xs text-zinc-500">{searchItems.length} retrieved results matching the current library view and filters. Search retrieves a limited set from the historical evidence corpus.</p>{searchItems.map((item) => <article key={`${item.id}-${item.revision}`} className="rounded border border-zinc-200 bg-white p-4"><Link className="text-sm font-medium underline underline-offset-4" to={incidentLink(item)}>{item.title}</Link><p className="mt-1 text-xs text-zinc-600">{item.line} · {item.match_reason}</p>{item.differences.length > 0 && <p className="mt-1 text-xs text-zinc-500">{item.differences.join(' ')}</p>}</article>)}</div> : <div className="rounded border border-dashed border-zinc-300 bg-white p-5 text-sm text-zinc-600">No retrieved results match this query in the current view and filters. Clear the search to change filters.</div>
      ) : <>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Library view">
          <Button variant={view === 'cases' ? 'default' : 'outline'} aria-pressed={view === 'cases'} onClick={() => { setView('cases'); setPage(1); setLine(''); setCalculation(''); setDate(''); setEvidence(''); setAssignee(''); setActions('') }}>Demo and imported cases ({cases.length})</Button>
          <Button variant={view === 'engineering' ? 'default' : 'outline'} aria-pressed={view === 'engineering'} onClick={() => { setView('engineering'); setPage(1); setLine(''); setCalculation(''); setDate(''); setEvidence(''); setAssignee(''); setActions('') }}>Engineering fixtures ({fixtures.length})</Button>
        </div>
        <p className="text-sm leading-6 text-zinc-600">{view === 'engineering' ? 'Generated historical, development, and locked evaluation fixtures. These cases test system behavior; they are not factory observations.' : 'Curated demo investigations and all imported cases. Generated evaluation fixtures are available in the engineering view.'}</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-xs font-medium text-zinc-700">Line<select className={`${selectClass} mt-1`} value={line} onChange={(event) => { setLine(event.target.value); setPage(1) }}><option value="">All lines</option>{[...new Set(selected.map((item) => item.line))].sort().map((value) => <option key={value}>{value}</option>)}</select></label>
          <label className="text-xs font-medium text-zinc-700">Calculation coverage<select className={`${selectClass} mt-1`} value={calculation} onChange={(event) => { setCalculation(event.target.value); setPage(1) }}><option value="">All calculation states</option>{[...new Set(selected.map((item) => item.status))].sort().map((value) => <option key={value} value={value}>{calculationLabel(value)}</option>)}</select></label>
          <label htmlFor="incident-date" className="text-xs font-medium text-zinc-700">Window start date (source timezone)<Input className="mt-1" id="incident-date" type="date" value={date} onChange={(event) => { setDate(event.target.value); setPage(1) }} /></label>
          <label className="text-xs font-medium text-zinc-700">Evidence state<select className={`${selectClass} mt-1`} value={evidence} onChange={(event) => { setEvidence(event.target.value); setPage(1) }}><option value="">All evidence states</option>{[...new Set(selected.map((item) => item.evidence_state ?? 'UNKNOWN'))].sort().map((value) => <option key={value} value={value}>{evidenceLabel(value)}</option>)}</select></label>
          <label className="text-xs font-medium text-zinc-700">Assignee (open actions)<select disabled={!user || saved} className={`${selectClass} mt-1 disabled:bg-zinc-100`} value={user && !saved ? assignee : ''} onChange={(event) => { setAssignee(event.target.value); setPage(1) }}><option value="">{user ? 'All assignees' : 'Sign in to filter assignees'}</option>{user && !saved && [...new Map(selected.flatMap((item) => item.workflow?.assignees ?? []).map((person) => [person.id, person])).values()].map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
          <label className="text-xs font-medium text-zinc-700">Actions<select disabled={!user || saved} className={`${selectClass} mt-1 disabled:bg-zinc-100`} value={user && !saved ? actions : ''} onChange={(event) => { setActions(event.target.value); setPage(1) }}><option value="">{user ? 'All action states' : 'Sign in to filter actions'}</option><option value="open">Has open actions</option><option value="none">No open actions</option></select></label>
        </div>
        <p className="text-xs leading-5 text-zinc-600">Calculation coverage describes comparable production buckets. Evidence coverage describes available sources. Human review and action completion require separate confirmation in the investigation.</p>
        {filtered.length === 0 ? <div className="rounded border border-dashed border-zinc-300 bg-white p-8 text-center text-sm text-zinc-600">{selected.length === 0 ? 'No cases are available in this view.' : 'No cases match these filters.'}</div> : <>
          <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
            <div className="divide-y divide-zinc-200 md:hidden">{visible.map((item) => <article key={item.id} className="p-4">
              <Link className="text-base font-semibold leading-6 text-zinc-900 underline decoration-zinc-300 underline-offset-4 focus-visible:outline-2" to={incidentLink(item)}>{item.title}</Link>
              <p className="mt-1 text-xs text-zinc-600">{item.line} · revision {item.revision}</p>
              <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                <div className="col-span-2"><dt className="text-zinc-500">Investigation window</dt><dd className="mt-1">{formatInstant(item.window_start)} to {formatInstant(item.window_end)}</dd></div>
                <div><dt className="text-zinc-500">Observed shortfall</dt><dd className="mt-1 font-medium tabular-nums">{item.shortfall == null ? 'Unavailable' : `${item.shortfall} good units`}</dd></div>
                <div><dt className="text-zinc-500">Calculation coverage</dt><dd className="mt-1">{calculationLabel(item.status)}</dd></div>
                <div className="col-span-2"><dt className="text-zinc-500">Evidence coverage</dt><dd className="mt-1">{item.evidence_completeness ?? 'Coverage not reported'}</dd></div>
                <div className="col-span-2"><dt className="text-zinc-500">Human review</dt><dd className="mt-1">{saved ? 'Review state unavailable offline' : reviewLabel(item)}</dd></div>
                <div className="col-span-2"><dt className="text-zinc-500">Investigation state</dt><dd className="mt-1">{saved ? 'State unavailable offline' : investigationLabel(item, !!user)}</dd></div><div className="col-span-2"><dt className="text-zinc-500">Action state</dt><dd className="mt-1">{saved ? 'State unavailable offline' : actionLabel(item, !!user)}</dd></div>
              </dl>
            </article>)}</div>
            <div className="hidden overflow-x-auto md:block"><table className="w-full min-w-[900px] text-left text-sm">
              <caption className="sr-only">Recorded incidents with separate calculation, evidence, human review, and action states</caption>
              <thead className="border-b border-zinc-200 bg-zinc-50 text-xs text-zinc-500"><tr>{['Incident / line', 'Investigation window', 'Observed shortfall', 'Calculation coverage', 'Evidence coverage', 'Human review / actions'].map((label) => <th key={label} scope="col" className="px-4 py-3 font-medium">{label}</th>)}</tr></thead>
              <tbody className="divide-y divide-zinc-100">{visible.map((item) => <tr key={item.id} className="align-top hover:bg-zinc-50">
                <td className="px-4 py-4"><Link className="font-medium text-zinc-900 underline decoration-zinc-300 underline-offset-4 hover:decoration-zinc-900 focus-visible:outline-2" to={incidentLink(item)}>{item.title}</Link><span className="mt-1 block text-xs text-zinc-500">{item.line} · revision {item.revision}</span></td>
                <td className="px-4 py-4 text-zinc-700">{formatInstant(item.window_start)}<span className="block text-xs text-zinc-500">to {formatInstant(item.window_end)}</span></td>
                <td className="px-4 py-4 font-medium tabular-nums">{item.shortfall == null ? 'Unavailable' : `${item.shortfall} good units`}</td>
                <td className="px-4 py-4 text-xs text-zinc-700">{calculationLabel(item.status)}</td>
                <td className="px-4 py-4 text-xs text-zinc-600">{item.evidence_completeness ?? 'Coverage not reported'}</td>
                <td className="px-4 py-4 text-xs text-zinc-600">{saved ? 'Review state unavailable offline' : reviewLabel(item)}<span className="mt-2 block">Investigation: {saved ? 'State unavailable offline' : investigationLabel(item, !!user)}</span><span className="mt-2 block">Actions: {saved ? 'State unavailable offline' : actionLabel(item, !!user)}</span></td>
              </tr>)}</tbody>
            </table></div>
          </div>
          <nav aria-label="Incident pages" className="flex flex-wrap items-center justify-between gap-3">
            <p role="status" className="text-xs text-zinc-500">Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filtered.length)} of {filtered.length} cases · page {currentPage} of {totalPages}</p>
            <div className="flex gap-2"><Button variant="outline" size="sm" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous page</Button><Button variant="outline" size="sm" disabled={currentPage === totalPages} onClick={() => setPage(currentPage + 1)}>Next page</Button></div>
          </nav>
        </>}
      </>}
      <p className="text-xs leading-5 text-zinc-600">Later records create a new revision and preserve the earlier view. An unrecorded source or review is not evidence that no problem exists.</p>
    </div>
  )
}
