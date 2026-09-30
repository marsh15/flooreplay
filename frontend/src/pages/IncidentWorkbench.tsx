import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router'
import { incidentApi, type AnalysisReport, type Hypothesis, type RecoveryProposal } from '@/lib/incidents'
import { api } from '@/lib/api'
import { formatInstant } from '@/lib/status'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/components/Auth'
import { OpenAiPanel, HybridPanel, ExportReport } from '@/components/IncidentAi'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import savedAi from '@/data/hero-ai.json'

function EvidenceLink({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return <button type="button" onClick={() => onOpen(id)} className="rounded border border-zinc-300 bg-white px-1.5 py-0.5 font-mono text-xs text-zinc-700 underline-offset-2 hover:underline focus-visible:outline-2">{id}</button>
}

function EvidenceList({ ids, onOpen }: { ids: string[]; onOpen: (id: string) => void }) {
  return ids.length ? <span className="flex flex-wrap gap-1">{ids.map((id) => <EvidenceLink key={id} id={id} onOpen={onOpen} />)}</span> : <span className="text-xs text-zinc-500">None recorded</span>
}

function Section({ title, detail, children }: { title: string; detail?: string; children: React.ReactNode }) {
  return <section className="space-y-3"><div className="border-b border-zinc-200 pb-2"><h2 className="text-base font-semibold tracking-tight">{title}</h2>{detail && <p className="mt-0.5 text-xs text-zinc-500">{detail}</p>}</div>{children}</section>
}

function HypothesisCard({ item, onEvidence }: { item: Hypothesis; onEvidence: (id: string) => void }) {
  return <article className="rounded border border-zinc-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{item.category.replace(/_/g, ' ')}</h3><span className="rounded bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900">{item.status.replace(/_/g, ' ')}</span></div>
    <p className="mt-2 text-sm leading-6 text-zinc-700">{item.mechanism}</p>
    <dl className="mt-3 grid gap-3 border-t border-zinc-100 pt-3 text-xs sm:grid-cols-2">
      <div><dt className="mb-1 font-medium text-zinc-600">Supporting evidence</dt><dd><EvidenceList ids={item.supporting_evidence} onOpen={onEvidence} /></dd></div>
      <div><dt className="mb-1 font-medium text-zinc-600">Contradictions</dt><dd><EvidenceList ids={item.contradicting_evidence} onOpen={onEvidence} /></dd></div>
    </dl>
    <p className="mt-3 border-l-2 border-amber-500 pl-3 text-xs text-zinc-700"><strong>Next check:</strong> {item.next_check}</p>
  </article>
}

function ProposalCard({ item, report, currentRevision, canReview, onEvidence, onChanged }: { item: RecoveryProposal; report: AnalysisReport; currentRevision: number; canReview: boolean; onEvidence: (id: string) => void; onChanged: () => void }) {
  const { user } = useAuth()
  const [rationale, setRationale] = useState('')
  const [reviewOpen, setReviewOpen] = useState(false)
  const [message, setMessage] = useState('')
  const stale = report.revision !== currentRevision || report.stale === true
  const reviewState = report.reviews?.filter((review) => review.proposal_id === item.id).at(-1)?.state ?? item.state
  const submit = useMutation({ mutationFn: () => incidentApi.submitProposal(report.id, item.id), onSuccess: () => { setMessage('Submitted for human review.'); onChanged() }, onError: (error) => setMessage(error.message) })
  const review = useMutation({ mutationFn: (decision: 'APPROVED' | 'REJECTED') => incidentApi.reviewProposal(report.id, item.id, decision, rationale.trim()), onSuccess: () => { setMessage('Review recorded. No factory action was executed.'); setReviewOpen(false); onChanged() }, onError: (error) => setMessage(error.message) })
  return <article className="rounded border border-zinc-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{item.type.replace(/_/g, ' ')}</h3><span className="rounded bg-zinc-100 px-2 py-1 text-xs">{reviewState.replace(/_/g, ' ')}</span></div>
    <p className="mt-1 text-xs text-zinc-500">Owner: {item.owner_role.replace(/_/g, ' ')}</p>
    <p className="mt-2 text-sm text-zinc-700">{item.purpose}</p>
    <div className="mt-3 space-y-2 text-xs text-zinc-700">
      {item.preconditions.length > 0 && <p><strong>Before acting:</strong> {item.preconditions.join('; ')}</p>}
      {item.missing_information.length > 0 && <p><strong>Still needed:</strong> {item.missing_information.join('; ')}</p>}
      <div><span className="mb-1 block font-medium">Evidence</span><EvidenceList ids={item.supporting_evidence} onOpen={onEvidence} /></div>
    </div>
    <div className="mt-4 border-t border-zinc-100 pt-3">
      {stale && <p className="mb-2 text-xs font-medium text-amber-800">This proposal belongs to revision {report.revision}. Open the current revision before review.</p>}
      {!canReview && <p className="text-xs text-zinc-600">Sign in as an invited reviewer to record decisions.</p>}
      {canReview && reviewState === 'DRAFT' && <Button size="sm" variant="outline" disabled={stale || submit.isPending} onClick={() => submit.mutate()}>{submit.isPending ? 'Submitting…' : 'Submit for review'}</Button>}
      {canReview && reviewState === 'PENDING_REVIEW' && !reviewOpen && <Button size="sm" variant="outline" disabled={stale} onClick={() => setReviewOpen(true)}>Record review</Button>}
      {reviewOpen && <div className="space-y-2">
        <p className="text-xs">Reviewer: {user?.display_name}</p>
        <div><label htmlFor={`reason-${item.id}`} className="mb-1 block text-xs font-medium">Review rationale</label><textarea id={`reason-${item.id}`} value={rationale} onChange={(event) => setRationale(event.target.value)} className="min-h-20 w-full rounded border border-zinc-300 p-2 text-sm focus-visible:outline-2" /></div>
        <div className="flex flex-wrap gap-2"><Button size="sm" disabled={!rationale.trim() || stale || review.isPending} onClick={() => review.mutate('APPROVED')}>Approve review</Button><Button size="sm" variant="outline" disabled={!rationale.trim() || stale || review.isPending} onClick={() => review.mutate('REJECTED')}>Reject</Button><Button size="sm" variant="ghost" onClick={() => setReviewOpen(false)}>Cancel</Button></div>
      </div>}
      {message && <p role="status" className="mt-2 text-xs text-zinc-700">{message}</p>}
      <p className="mt-2 text-xs text-zinc-500">Review records a decision against this report. It does not execute a factory change.</p>
    </div>
  </article>
}

function SavedAiPanel({ onEvidence }: { onEvidence: (id: string) => void }) {
  return <Section title="Historical local-model result" detail="Qwen archive · OpenAI not evaluated · Experimental · author-reviewed synthetic case · recorded output from an earlier local run">
    <div className="rounded border border-zinc-200 bg-white p-4">
      <p className="text-xs text-zinc-600">{savedAi.model} · {savedAi.elapsed_seconds} seconds · {savedAi.execution_kind}</p>
      <p className="mt-2 text-sm text-amber-900">{savedAi.quality_notice}</p>
      <ol className="mt-4 space-y-4">
        {savedAi.claims.map((claim, index) => <li key={index} className="border-t border-zinc-100 pt-3">
          <div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-zinc-500">Claim {index + 1}</span><span className={claim.review_status === 'SUPPORTED' ? 'rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-900' : 'rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-900'}>{claim.review_status.replace(/_/g, ' ')}</span></div>
          <p className="mt-2 text-sm leading-6 text-zinc-800">{claim.text}</p>
          {claim.review_reason && <p className="mt-1 text-xs text-amber-900"><strong>Reviewer note:</strong> {claim.review_reason}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-zinc-500"><span>Evidence:</span><EvidenceList ids={claim.evidence_ids} onOpen={onEvidence} />{claim.metric_ids.length > 0 && <span>Metrics: {claim.metric_ids.join(', ')}</span>}</div>
        </li>)}
      </ol>
      {savedAi.limitations.length > 0 && <div className="mt-4 rounded bg-zinc-50 p-3 text-xs text-zinc-700"><strong>Limitations</strong><ul className="mt-1 list-disc space-y-1 pl-4">{savedAi.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
    </div>
  </Section>
}

export function IncidentWorkbenchPage() {
  const { user } = useAuth()
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const queryClient = useQueryClient()
  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities, staleTime: 60_000 })
  const library = useQuery({ queryKey: ['incidents'], queryFn: incidentApi.list })
  const summary = library.data?.items.find((item) => item.id === id)
  const revision = Number(params.get('revision') || summary?.revision || 1)
  const analysisId = params.get('analysis')
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const incident = useQuery({ queryKey: ['incident', id, revision], queryFn: () => incidentApi.revision(id, revision), enabled: !!id && (!!params.get('revision') || !!summary || library.isError) })
  const reportQuery = useQuery({ queryKey: ['incident-analysis', id, revision, analysisId], queryFn: () => analysisId ? incidentApi.analysis(analysisId) : incidentApi.analyze(id, revision), enabled: !!id && !!incident.data, retry: false })
  const report = reportQuery.data
  useEffect(() => {
    if (report && !analysisId) {
      queryClient.setQueryData(['incident-analysis', id, revision, report.id], report)
      setParams({ revision: String(revision), analysis: report.id }, { replace: true })
    }
  }, [report, analysisId, id, revision, queryClient, setParams])
  const evidence = useQuery({ queryKey: ['incident-evidence', report?.id, evidenceId], queryFn: () => incidentApi.evidence(report!.id, evidenceId!), enabled: !!report && !!evidenceId })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['incident-analysis', id, revision] })
  const changeRevision = (value: number) => { setEvidenceId(null); setParams({ revision: String(value) }) }

  return <div className="space-y-7">
    <Link to="/" className="text-xs text-zinc-600 underline underline-offset-4 hover:text-zinc-900">← Incident library</Link>
    {incident.isPending ? <div aria-busy="true" aria-label="Loading incident"><Skeleton className="h-12 w-2/3" /><Skeleton className="mt-4 h-32" /></div> : incident.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-5 text-sm text-red-800">Could not load incident: {incident.error.message} <Button variant="outline" size="sm" onClick={() => incident.refetch()}>Retry</Button></div> : <>
      <header className="border-b border-zinc-200 pb-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-700">Incident investigation</p>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold tracking-tight">{incident.data.title}</h1><p className="mt-1 text-sm text-zinc-600">{incident.data.scope.line_id} · {formatInstant(incident.data.window.start)} to {formatInstant(incident.data.window.end)}</p></div><div className="flex items-end gap-2"><div><label htmlFor="revision" className="mb-1 block text-xs font-medium text-zinc-600">Evidence revision</label><select id="revision" value={revision} onChange={(event) => changeRevision(Number(event.target.value))} className="h-9 rounded border border-zinc-300 bg-white px-3 text-sm focus-visible:outline-2">{(report?.execution_kind === 'saved_deterministic' ? [revision] : incident.data.available_revisions).map((value) => <option key={value} value={value}>Revision {value}</option>)}</select></div></div></div>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-500"><span>Knowledge cutoff: {formatInstant(incident.data.cutoff)}</span><span>Report: {report?.execution_kind === 'saved_deterministic' ? 'Saved deterministic result' : 'Live deterministic analysis'}</span><span>Factory data: synthetic</span></div>
      </header>
      {reportQuery.isPending ? <div aria-busy="true" aria-label="Building analysis" className="space-y-3"><Skeleton className="h-28" /><Skeleton className="h-48" /><Skeleton className="h-48" /></div> : reportQuery.isError ? <div role="alert" className="rounded border border-red-200 bg-red-50 p-5"><h2 className="text-sm font-semibold text-red-900">Analysis unavailable</h2><p className="mt-1 text-sm text-red-800">{reportQuery.error.message}</p><Button className="mt-3" size="sm" variant="outline" onClick={() => reportQuery.refetch()}>Retry analysis</Button></div> : report && <>
        <Section title="Observed situation" detail="Calculated from comparable complete 15-minute buckets; missing data is not counted as zero.">
          <div className="grid gap-3 sm:grid-cols-3"><div className="rounded border border-zinc-200 bg-white p-4"><p className="text-xs text-zinc-500">Baseline planned</p><p className="mt-1 text-2xl font-semibold tabular-nums">{report.metrics.planned ?? '—'}</p><p className="text-xs text-zinc-500">{report.metrics.unit.replaceAll('_', ' ')}</p></div><div className="rounded border border-zinc-200 bg-white p-4"><p className="text-xs text-zinc-500">Recorded good output</p><p className="mt-1 text-2xl font-semibold tabular-nums">{report.metrics.observed ?? '—'}</p><p className="text-xs text-zinc-500">{report.metrics.unit.replaceAll('_', ' ')}</p></div><div className="rounded border border-amber-300 bg-amber-50 p-4"><p className="text-xs text-amber-800">Observed shortfall</p><p className="mt-1 text-2xl font-semibold tabular-nums">{report.metrics.shortfall ?? '—'}</p><p className="text-xs text-amber-800">{report.metrics.status}</p></div></div>
          {report.metrics.planned != null && report.metrics.observed != null && report.metrics.planned > 0 && <div className="rounded border border-zinc-200 bg-white p-4"><div className="mb-2 flex justify-between text-xs text-zinc-600"><span>Recorded output against baseline</span><span>{Math.round(report.metrics.observed / report.metrics.planned * 100)}%</span></div><div className="h-3 overflow-hidden rounded bg-zinc-200"><div className="h-full bg-zinc-800" style={{ width: `${Math.min(100, Math.max(0, report.metrics.observed / report.metrics.planned * 100))}%` }} /></div></div>}
          <p className="text-xs text-zinc-600">{report.metrics.matched_buckets.length} matched buckets · {report.metrics.missing_buckets.length} missing · {report.metrics.unfinished_buckets.length} unfinished{report.metrics.blocked_minutes != null ? ` · ${report.metrics.blocked_minutes} established line-block minutes` : ''}</p>
          <div className="rounded border border-zinc-200 bg-white">
            <div className="border-b border-zinc-100 px-4 py-3"><h3 className="text-sm font-medium">Calculation inputs</h3><p className="mt-1 font-mono text-xs text-zinc-600">{report.metrics.formula ?? 'Formula unavailable in this report.'}</p></div>
            {report.metrics.inputs?.length ? <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><caption className="sr-only">Comparable completed 15-minute production buckets used in the reported calculation</caption><thead className="bg-zinc-50 text-xs uppercase text-zinc-500"><tr><th scope="col" className="px-4 py-2">Completed interval</th><th scope="col" className="px-4 py-2">Baseline plan</th><th scope="col" className="px-4 py-2">Recorded good output</th></tr></thead><tbody className="divide-y divide-zinc-100">{report.metrics.inputs.map((input) => <tr key={`${input.start}-${input.end}`}><th scope="row" className="whitespace-nowrap px-4 py-2 text-xs font-normal text-zinc-700">{formatInstant(input.start)} – {formatInstant(input.end)}</th><td className="px-4 py-2"><span className="mr-2 tabular-nums">{input.plan.quantity}</span><EvidenceLink id={input.plan.id} onOpen={setEvidenceId} /></td><td className="px-4 py-2"><span className="mr-2 tabular-nums">{input.output.quantity}</span><EvidenceLink id={input.output.id} onOpen={setEvidenceId} /></td></tr>)}</tbody></table></div> : <p className="px-4 py-3 text-xs text-zinc-600">{report.metrics.inputs ? 'No comparable completed buckets are available.' : 'Input breakdown is unavailable in this report.'}</p>}
          </div>
          {report.capabilities?.production?.reasons.map((reason) => <p key={reason} className="text-xs text-amber-800">{reason}</p>)}
          {report.metrics.target_pressure?.remaining_target != null && <div className="rounded border border-zinc-200 bg-white p-4 text-sm"><h3 className="font-medium">Remaining shift target</h3>{report.metrics.target_pressure.as_of && <p className="mt-1 text-xs text-zinc-600">As of recorded output: {formatInstant(report.metrics.target_pressure.as_of)}</p>}<p className="mt-1 text-zinc-700">{report.metrics.target_pressure.remaining_target} {report.metrics.unit.replaceAll('_', ' ')} across {report.metrics.target_pressure.remaining_elapsed_minutes ?? report.metrics.target_pressure.remaining_working_minutes} elapsed minutes under the report assumptions.</p><p className="mt-1 text-xs text-zinc-600">Required average: {report.metrics.target_pressure.required_units_per_hour ?? 'Unavailable'} units/hour · Baseline: {report.metrics.target_pressure.baseline_units_per_hour ?? 'Unavailable'} units/hour</p><p className="mt-1 text-xs text-zinc-500">{report.metrics.target_pressure.assumptions.join(' ')}</p></div>}
        </Section>
        <Section title="Evidence timeline" detail="Events are ordered by occurrence. Availability at the cutoff determines which records are included.">
          {report.timeline.length ? <div className="overflow-x-auto rounded border border-zinc-200 bg-white"><table className="w-full min-w-[650px] text-left text-sm"><thead className="border-b bg-zinc-50 text-xs uppercase text-zinc-500"><tr><th scope="col" className="px-4 py-2">When</th><th scope="col" className="px-4 py-2">Lane</th><th scope="col" className="px-4 py-2">Observation</th><th scope="col" className="px-4 py-2">Source</th></tr></thead><tbody className="divide-y divide-zinc-100">{report.timeline.map((event) => <tr key={event.id}><td className="whitespace-nowrap px-4 py-3 text-xs tabular-nums text-zinc-600">{formatInstant(event.occurred_at ?? event.start ?? '')}{event.end ? ` – ${formatInstant(event.end)}` : ''}</td><td className="px-4 py-3 text-xs font-medium uppercase tracking-wide text-zinc-500">{event.lane}</td><td className="px-4 py-3">{event.summary}{event.assertion && <span className="ml-2 text-xs text-amber-800">Source assertion</span>}</td><td className="px-4 py-3"><EvidenceLink id={event.id} onOpen={setEvidenceId} /></td></tr>)}</tbody></table></div> : <p className="rounded border border-dashed p-5 text-sm text-zinc-600">No timeline events are available at this cutoff.</p>}
        </Section>
        <Section title="Explanations and open questions" detail="A sequence of events alone does not establish causation.">
          {report.hypotheses.length ? <div className="grid gap-3 lg:grid-cols-2">{report.hypotheses.map((item, index) => <HypothesisCard key={`${item.category}-${index}`} item={item} onEvidence={setEvidenceId} />)}</div> : <p className="rounded border border-dashed p-5 text-sm text-zinc-600">Current evidence does not support a specific contributor.</p>}
        </Section>
        <HybridPanel report={report} enabled={capabilities.data?.ai?.index_ready === true && capabilities.data?.reviews_enabled === true} />
        <Section title="Historical precedents" detail="Live lexical search. Similar cases can guide checks; differences limit what can be inferred.">{report.precedents?.length ? <div className="grid gap-3 lg:grid-cols-2">{report.precedents.map((item, index) => <article key={item.id ?? item.incident_id ?? index} className="rounded border bg-white p-4"><h3 className="text-sm font-semibold">{item.title ?? item.incident_id ?? 'Historical incident'}</h3>{item.match_reason || item.match_reasons?.length ? <p className="mt-2 text-xs text-zinc-700"><strong>Similar:</strong> {item.match_reason ?? item.match_reasons?.join('; ')}</p> : null}{item.differences?.length ? <p className="mt-2 text-xs text-zinc-700"><strong>Different:</strong> {item.differences.join('; ')}</p> : null}{(item.incident_id || item.id) && <Link className="mt-3 inline-block text-xs underline" to={`/incidents/${encodeURIComponent(item.incident_id ?? item.id!)}`}>Open precedent</Link>}</article>)}</div> : <p className="rounded border border-dashed p-5 text-sm text-zinc-600">No eligible historical precedents were retrieved.</p>}</Section>
        <Section title="Recovery options" detail="Proposals are versioned requests for human review.">{report.proposals.length ? <div className="grid gap-3 lg:grid-cols-2">{report.proposals.map((item) => <ProposalCard key={`${report.id}-${item.id}-${item.state}`} item={item} report={report} currentRevision={summary?.revision ?? revision} canReview={capabilities.data?.reviews_enabled === true && report.execution_kind !== 'saved_deterministic'} onEvidence={setEvidenceId} onChanged={refresh} />)}</div> : <p className="rounded border border-dashed p-5 text-sm text-zinc-600">No action proposal is supported by this evidence.</p>}</Section>
        <Section title="Shift update" detail="Evidence-linked report summary"><blockquote className="border-l-2 border-zinc-900 bg-white py-3 pl-4 text-sm leading-7 text-zinc-700">{report.summary}</blockquote><ExportReport report={report} enabled={capabilities.data?.reviews_enabled === true} /></Section>
        {report.incident_id === savedAi.incident_id && report.revision === savedAi.revision && <SavedAiPanel onEvidence={setEvidenceId} />}
        <OpenAiPanel key={`${report.id}:${user?.id ?? 'anonymous'}`} report={report} enabled={capabilities.data?.ai?.generation_available === true && report.execution_kind !== 'saved_deterministic'} reasons={capabilities.data?.ai?.reason ? [capabilities.data.ai.reason.replaceAll('_', ' ').toLowerCase()] : ['OpenAI drafts are available to authenticated reviewers.']} onEvidence={setEvidenceId} />
      </>}
    </>}
    <Sheet open={evidenceId !== null} onOpenChange={(open) => { if (!open) setEvidenceId(null) }}><SheetContent className="overflow-y-auto"><SheetHeader><SheetTitle>Source evidence</SheetTitle><SheetDescription>{evidenceId}</SheetDescription></SheetHeader><div className="px-4 pb-6">{evidence.isPending ? <Skeleton className="h-32" /> : evidence.isError ? <p role="alert" className="text-sm text-red-700">{evidence.error.message}</p> : evidence.data ? <dl className="space-y-3 text-sm">{Object.entries(evidence.data).map(([key, value]) => <div key={key} className="border-b border-zinc-100 pb-2"><dt className="text-xs font-medium uppercase tracking-wide text-zinc-500">{key.replace(/_/g, ' ')}</dt><dd className="mt-1 break-words font-mono text-xs text-zinc-800">{typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '—')}</dd></div>)}</dl> : null}</div></SheetContent></Sheet>
  </div>
}
