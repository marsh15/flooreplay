import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { incidentApi } from '@/lib/incidents'
import type { AiClaim, AiClaimReviewRequest, AiPacket, AiReviewPacket, AiReviewReport, AiRunAssessmentRequest, ReviewDeclaration, ReviewFlag, ReviewJudgment } from '@/lib/incidents'

const selectClass = 'mt-1 min-h-10 w-full rounded-md border border-input bg-background px-3 text-sm'
const textareaClass = 'mt-1 min-h-20 w-full rounded-md border border-input bg-background p-3 text-sm leading-6'
const label = (value: string) => value.replaceAll('_', ' ')
const flags: ReviewFlag[] = ['attribution_error', 'unsupported_conclusion', 'omitted_contradiction', 'appropriate_abstention', 'useful_next_check']
const lines = (text: string) => text.split('\n').map((line) => line.trim()).filter(Boolean)
const initialDeclaration: ReviewDeclaration = { reviewer_kind: 'unspecified', qualifications: '', independent: false }
const declarationReady = (value: ReviewDeclaration) => value.reviewer_kind !== 'human' && !value.independent || value.qualifications.trim().length >= 3

function MutationFeedback<TData, TBody>({ mutation }: { mutation: UseMutationResult<TData, Error, TBody> }) {
  return <>{mutation.isSuccess && <p role="status" className="text-xs text-emerald-800">Annotation saved against this exact output. Operational approval remains separate.</p>}{mutation.error && <div role="alert" className="space-y-2 rounded border border-red-200 bg-red-50 p-3 text-xs text-red-900"><p>{mutation.error.message}</p><p>Retry sends the same output identity, annotation, and request key. Reload the review packet if the output identity conflicts.</p><div className="flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => { if (mutation.variables) mutation.mutate(mutation.variables) }}>Retry same annotation</Button><Button type="button" variant="ghost" size="sm" onClick={() => mutation.reset()}>Edit as a new annotation</Button></div></div>}</>
}

function DeclarationFields({ value, onChange, disabled, selfReview = false }: { value: ReviewDeclaration; onChange: (value: ReviewDeclaration) => void; disabled: boolean; selfReview?: boolean }) {
  return <fieldset disabled={disabled} className="space-y-3 rounded border border-zinc-200 p-3">
    <legend className="px-1 text-xs font-medium">Reviewer declaration</legend>
    <label className="block text-xs">Reviewer kind<select className={selectClass} value={value.reviewer_kind} onChange={(event) => { const kind = event.target.value; if (kind === 'human' || kind === 'ai_assistant' || kind === 'unspecified') onChange({ ...value, reviewer_kind: kind }) }}><option value="unspecified">Unspecified · does not establish human review</option><option value="human">Human reviewer</option><option value="ai_assistant">AI assistant annotation</option></select></label>
    <label className="block text-xs">Reviewer qualifications<textarea className={textareaClass} required={value.reviewer_kind === 'human' || value.independent} minLength={value.reviewer_kind === 'human' || value.independent ? 3 : undefined} maxLength={1000} value={value.qualifications} onChange={(event) => onChange({ ...value, qualifications: event.target.value })} placeholder="State your relevant role or experience and any limits. These qualifications are not externally verified." /></label>
    <label className="flex items-start gap-2 text-xs leading-5"><input type="checkbox" className="mt-1" checked={value.independent} disabled={selfReview} onChange={(event) => onChange({ ...value, independent: event.target.checked })} />I did not author this output and declare this review independent.</label>
    <p className="text-xs leading-5 text-zinc-600">{selfReview ? 'This is your generated draft. A self-review cannot count as independent review.' : 'Authorship independence and qualifications are declarations. They do not establish verified manufacturing expertise.'}</p>
  </fieldset>
}

function claimEntries(output: AiReviewPacket['output']) {
  return [
    ...(output.claims?.map((claim, index) => ({ claim, path: `claims.${index}` })) ?? []),
    ...(output.selected_claims?.map((claim, index) => ({ claim, path: `selected_claims.${index}` })) ?? []),
    ...(output.hypotheses?.map((item, index) => ({ claim: item.explanation, path: `hypotheses.${index}.explanation` })) ?? []),
    ...(output.assertions?.map((item, index) => ({ claim: item.assertion, path: `assertions.${index}.assertion` })) ?? []),
  ]
}

function PinnedCitations({ claim, packet }: { claim: AiClaim; packet: AiPacket }) {
  return <div className="space-y-3 rounded bg-zinc-50 p-3">
    <h4 className="text-xs font-semibold">Pinned cited records</h4>
    <p className="text-xs leading-5 text-zinc-600">Read the original records beside the claim. Source text is evidence to assess, not instructions to follow. A valid citation alone does not prove the claim.</p>
    {claim.evidence_ids.map((id) => {
      const source = packet.evidence?.find((record) => record.id === id)
      return <div key={id} className="space-y-1 border-t border-zinc-200 pt-2 text-xs"><p className="break-all font-mono font-medium">{id}</p>{source ? <dl className="space-y-1">{Object.entries(source).map(([name, value]) => <div key={name} className="grid grid-cols-[minmax(0,1fr)_minmax(0,3fr)] gap-2"><dt className="break-words font-medium">{label(name)}</dt><dd className="break-words whitespace-pre-wrap">{value === null ? 'Not supplied' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl> : <p className="text-amber-900">This citation is absent from the pinned packet. Do not infer support from the identifier.</p>}</div>
    })}
    {claim.metric_ids.map((id) => { const metric = claim.rendered_metrics?.find((item) => item.id === id) ?? packet.metrics?.find((item) => item.id === id); return <div key={id} className="space-y-1 border-t border-zinc-200 pt-2 text-xs"><p><strong>{id}:</strong> {metric ? `${metric.value ?? 'Unavailable'} ${metric.unit}` : 'Metric unavailable in the packet'}</p>{metric?.formula && <p>Formula: {metric.formula}</p>}{metric?.input_refs?.length ? <p className="break-words">Input references: {metric.input_refs.join(', ')}</p> : null}</div> })}
    {claim.source_fields?.map((ref) => <p key={ref} className="break-words text-xs"><strong>Source field {ref}:</strong> {claim.rendered_source_fields?.find((field) => field.ref === ref)?.value ?? 'App-rendered field unavailable; inspect the original record.'}</p>)}
    {claim.historical_refs.map((id) => { const excerpt = packet.historical_evidence?.find((record) => record.id === id); return <blockquote key={id} className="border-l-2 border-zinc-300 pl-3 text-xs leading-5"><p className="break-all font-medium">Historical citation {id}{excerpt?.incident_id && ` · incident ${excerpt.incident_id}`}{excerpt?.source_id && ` · source ${excerpt.source_id}`}</p><p className="whitespace-pre-wrap">{excerpt?.text ?? excerpt?.excerpt ?? 'Historical excerpt absent from the pinned packet.'}</p></blockquote> })}
    {claim.evidence_ids.length + claim.metric_ids.length + claim.historical_refs.length === 0 && <p className="text-xs text-amber-900">No source or metric citation is attached to this claim.</p>}
  </div>
}

function ClaimAnnotation({ run, claim, path, refresh, selfReview }: { run: AiReviewPacket; claim: AiClaim; path: string; refresh: () => Promise<void>; selfReview: boolean }) {
  const [judgment, setJudgment] = useState<ReviewJudgment>('insufficient_evidence')
  const [selectedFlags, setSelectedFlags] = useState<ReviewFlag[]>([])
  const [rationale, setRationale] = useState('')
  const [declaration, setDeclaration] = useState<ReviewDeclaration>(initialDeclaration)
  const mutation = useMutation({ mutationFn: (body: AiClaimReviewRequest) => incidentApi.reviewAiClaim(run.id, body), onSuccess: refresh, retry: false })
  const locked = mutation.isPending || mutation.isError
  const history = run.claim_reviews.filter((review) => review.claim_path === path)
  return <article aria-label={`Claim ${path}`} className="space-y-4 rounded-md border border-zinc-200 p-4">
    <div className="grid gap-4 lg:grid-cols-2"><div className="space-y-3"><h3 className="text-sm font-semibold">Claim · {path}</h3><p className="text-sm leading-6">{claim.text}</p><p className="text-xs text-zinc-600">Judge the wording against its cited records, including what the records cannot establish.</p></div><PinnedCitations claim={claim} packet={run.packet} /></div>
    {history.length > 0 && <details className="space-y-2 text-xs"><summary className="cursor-pointer font-medium">Append-only claim annotations ({history.length})</summary><ol className="space-y-2 pt-2">{history.map((review) => <li key={review.id} className="rounded bg-zinc-50 p-2 leading-5"><p>{label(review.judgment ?? (review.supported ? 'supported' : 'unsupported'))} · actor {review.actor} · {label(review.reviewer_kind ?? 'unspecified')}{review.independent ? ' · declared independent' : ' · independence not declared'}</p><p>{review.rationale}</p><p>Qualifications: {review.qualifications || 'Not declared'}</p>{review.flags?.length ? <p>Flags: {review.flags.map(label).join(', ')}</p> : null}<p className="break-all font-mono">{review.output_digest} · {review.created_at}</p></li>)}</ol></details>}
    <form aria-label={`Claim support review ${path}`} className="space-y-3" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate({ output_digest: run.output_digest, idempotency_key: crypto.randomUUID(), claim_path: path, judgment, flags: [...selectedFlags], ...declaration, qualifications: declaration.qualifications.trim(), rationale: rationale.trim() })
    }}>
      <fieldset disabled={locked} className="space-y-3"><legend className="mb-2 text-xs font-semibold">Factual support annotation</legend>
        <label className="block text-xs">Claim support<select className={selectClass} value={judgment} onChange={(event) => { const value = event.target.value; if (value === 'supported' || value === 'unsupported' || value === 'insufficient_evidence') setJudgment(value) }}><option value="insufficient_evidence">Insufficient evidence to decide</option><option value="supported">Supported by cited evidence</option><option value="unsupported">Unsupported by cited evidence</option></select></label>
        <fieldset className="space-y-2"><legend className="mb-2 text-xs font-medium">Review flags (optional)</legend>{flags.map((flag) => <label key={flag} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={selectedFlags.includes(flag)} onChange={(event) => setSelectedFlags(event.target.checked ? [...selectedFlags, flag] : selectedFlags.filter((item) => item !== flag))} />{label(flag)}</label>)}</fieldset>
        <DeclarationFields value={declaration} onChange={setDeclaration} disabled={locked} selfReview={selfReview} />
        <label className="block text-xs">Support rationale<textarea className={textareaClass} required minLength={3} maxLength={1000} value={rationale} onChange={(event) => setRationale(event.target.value)} /></label>
      </fieldset>
      <Button type="submit" variant="outline" size="sm" disabled={locked || rationale.trim().length < 3 || !declarationReady(declaration)}>{mutation.isPending ? 'Saving annotation…' : mutation.isSuccess ? 'Record another support annotation' : 'Record support review'}</Button>
      <MutationFeedback mutation={mutation} />
    </form>
  </article>
}

function RunAssessment({ run, refresh, selfReview }: { run: AiReviewPacket; refresh: () => Promise<void>; selfReview: boolean }) {
  const [declaration, setDeclaration] = useState<ReviewDeclaration>(initialDeclaration)
  const [usefulness, setUsefulness] = useState<AiRunAssessmentRequest['usefulness']>('uncertain')
  const [abstention, setAbstention] = useState<AiRunAssessmentRequest['abstention']>('not_applicable')
  const [omissions, setOmissions] = useState('')
  const [attribution, setAttribution] = useState('')
  const [rationale, setRationale] = useState('')
  const [limitations, setLimitations] = useState('')
  const mutation = useMutation({ mutationFn: (body: AiRunAssessmentRequest) => incidentApi.assessAiRun(run.id, body), onSuccess: refresh, retry: false })
  const locked = mutation.isPending || mutation.isError
  return <section className="space-y-3 rounded-md border border-zinc-200 p-4"><h3 className="text-base font-semibold">Whole-draft assessment</h3><p className="text-xs leading-5 text-zinc-600">Claim checks can miss omitted contradictions, unhelpful next checks, and inappropriate abstention. Assess those separately; this does not approve a recovery action.</p>
    <form aria-label="Whole-draft assessment" className="space-y-3" onSubmit={(event) => {
      event.preventDefault()
      if (lines(omissions).length > 12 || lines(attribution).length > 12) return
      mutation.mutate({ output_digest: run.output_digest, idempotency_key: crypto.randomUUID(), ...declaration, qualifications: declaration.qualifications.trim(), usefulness, abstention, omitted_contradictions: lines(omissions), attribution_errors: lines(attribution), rationale: rationale.trim(), limitations: limitations.trim() })
    }}><fieldset disabled={locked} className="space-y-3">
      <label className="block text-xs">Usefulness of this draft<select className={selectClass} value={usefulness} onChange={(event) => { const value = event.target.value; if (value === 'useful' || value === 'not_useful' || value === 'uncertain') setUsefulness(value) }}><option value="uncertain">Uncertain</option><option value="useful">Useful</option><option value="not_useful">Not useful</option></select></label>
      <label className="block text-xs">Abstention judgment<select className={selectClass} value={abstention} onChange={(event) => { const value = event.target.value; if (value === 'appropriate' || value === 'inappropriate' || value === 'not_applicable') setAbstention(value) }}><option value="not_applicable">Not applicable</option><option value="appropriate">Appropriate abstention</option><option value="inappropriate">Inappropriate abstention</option></select></label>
      <label className="block text-xs">Omitted contradictions (one per line, up to 12; blank if none identified)<textarea className={textareaClass} value={omissions} maxLength={5000} onChange={(event) => setOmissions(event.target.value)} /></label>
      <label className="block text-xs">Attribution errors (one per line, up to 12; blank if none identified)<textarea className={textareaClass} value={attribution} maxLength={5000} onChange={(event) => setAttribution(event.target.value)} /></label>
      <DeclarationFields value={declaration} onChange={setDeclaration} disabled={locked} selfReview={selfReview} />
      <label className="block text-xs">Assessment rationale<textarea className={textareaClass} required minLength={3} maxLength={2000} value={rationale} onChange={(event) => setRationale(event.target.value)} /></label>
      <label className="block text-xs">Assessment limitations<textarea className={textareaClass} required minLength={3} maxLength={2000} value={limitations} onChange={(event) => setLimitations(event.target.value)} placeholder="State unavailable records, uncertainty, and the limits of your expertise." /></label>
    </fieldset><Button size="sm" variant="outline" disabled={locked || rationale.trim().length < 3 || limitations.trim().length < 3 || lines(omissions).length > 12 || lines(attribution).length > 12 || !declarationReady(declaration)}>{mutation.isPending ? 'Saving assessment…' : 'Record whole-draft assessment'}</Button><MutationFeedback mutation={mutation} /></form>
  </section>
}

function ReviewStatements({ title, items }: { title: string; items?: string[] }) {
  return items?.length ? <div><h4 className="font-medium">{title}</h4><ul className="mt-1 list-disc space-y-1 pl-4">{items.map((item, index) => <li key={index} className="whitespace-pre-wrap break-words">{item}</li>)}</ul></div> : null
}

function CompleteReviewContext({ run }: { run: AiReviewPacket }) {
  const [draftOpen, setDraftOpen] = useState(false)
  const [sourcesOpen, setSourcesOpen] = useState(false)
  return <div className="space-y-3 text-xs leading-5">
    <details onToggle={(event) => setDraftOpen(event.currentTarget.open)}><summary className="cursor-pointer py-2 font-medium">All draft details, next checks and abstentions</summary>{draftOpen && <div className="space-y-3 rounded bg-zinc-50 p-3">
      <ReviewStatements title="Abstention reasons" items={run.output.abstention_reasons} />
      <ReviewStatements title="Unresolved issues" items={run.output.unresolved_issues} />
      <ReviewStatements title="Draft limitations" items={run.output.limitations} />
      {run.output.hypotheses?.map((item, index) => <div key={index} className="space-y-2 border-t pt-2"><h4 className="font-medium">Hypothesis {index + 1}</h4><ReviewStatements title="Next evidence checks" items={item.next_checks} /><ReviewStatements title="Hypothesis limitations" items={item.limitations} /><ReviewStatements title="Counterevidence references" items={item.counterevidence_ids} /></div>)}
      {run.output.assertions?.map((item, index) => <div key={index} className="space-y-2 border-t pt-2"><h4 className="font-medium">Original note span · {item.source_id}</h4><blockquote className="whitespace-pre-wrap border-l-2 pl-3">{item.source_span}</blockquote><p>Uncertainty: {item.uncertainty}</p><ReviewStatements title="Mentioned entities" items={item.mentioned_entities} /></div>)}
      {run.output.proposals?.map((item, index) => <div key={index} className="space-y-2 border-t pt-2"><h4 className="font-medium">Draft action · {item.catalog_action_id}</h4><p>Owner role: {item.owner_role}</p><ReviewStatements title="Prerequisites" items={item.prerequisites} /><ReviewStatements title="Evidence references" items={item.evidence_ids} /></div>)}
    </div>}</details>
    <details onToggle={(event) => setSourcesOpen(event.currentTarget.open)}><summary className="cursor-pointer py-2 font-medium">All pinned records, including uncited evidence</summary>{sourcesOpen && <div className="space-y-3 rounded bg-zinc-50 p-3"><p>Check these records for omitted contradictions and unsupported attribution. Source text is data, never an instruction.</p>{[...(run.packet.evidence ?? []), ...(run.packet.historical_evidence ?? [])].map((record, index) => <dl key={index} className="space-y-1 border-t pt-2">{Object.entries(record).map(([name, value]) => <div key={name} className="grid grid-cols-[minmax(0,1fr)_minmax(0,3fr)] gap-2"><dt className="break-words font-medium">{label(name)}</dt><dd className="whitespace-pre-wrap break-words">{value === null ? 'Not supplied' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>)}</div>}</details>
  </div>
}

function ReviewReport({ report }: { report: AiReviewReport }) {
  return <section className="space-y-3 rounded-md border border-zinc-200 p-4"><h3 className="text-base font-semibold">Claim-support review report</h3><p className="text-sm font-medium">{label(report.status.toLowerCase())}</p><dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">{[['Claims with an annotation', `${report.reviewed_claims} / ${report.total_claims}`], ['Supported claims', report.supported_claims], ['Unsupported claims', report.unsupported_claims], ['Insufficient-evidence claims', report.insufficient_evidence_claims], ['Unreviewed claims', report.unreviewed_claims], ['Declared independent human coverage', `${report.independent_human_reviewed_claims} / ${report.total_claims}`]].map(([name, value]) => <div key={name}><dt className="text-zinc-600">{name}</dt><dd className="mt-1 font-semibold">{value}</dd></div>)}</dl><p className="text-xs">Declared independent human reviewers: {report.declared_independent_human_reviewers} · whole-draft assessments: {report.independent_human_assessments ?? 0}. Review completion requires declared independent human coverage and a whole-draft assessment. Qualifications and independence have not been externally verified.</p>
    <p className="text-xs text-zinc-600">Support counts include claims whose latest annotations agree. Disputed claims are listed separately below.</p>
    {report.reviewers.length > 0 && <ul className="space-y-2 text-xs">{report.reviewers.map((reviewer, index) => <li key={`${reviewer.actor}-${index}`} className="rounded bg-zinc-50 p-2">Actor {reviewer.actor} · {label(reviewer.reviewer_kind)} · {reviewer.independent ? 'declared independent' : 'independence not declared'}<p>Qualifications: {reviewer.qualifications || 'Not declared'}</p></li>)}</ul>}
    {report.disagreements.length > 0 && <div className="space-y-2"><h4 className="text-sm font-medium">Reviewer disagreements</h4><ul className="space-y-1 text-xs">{report.disagreements.map((item) => <li key={item.claim_path}>{item.claim_path}: {item.judgments.map(label).join(' / ')} · actors {item.actors.join(', ')}</li>)}</ul><p className="text-xs text-zinc-600">Disagreements compare each actor’s latest annotation per claim. Earlier annotations remain in the audit history.</p></div>}
    {report.assessments.length > 0 && <details className="space-y-2 text-xs"><summary className="cursor-pointer font-medium">Whole-draft assessment history ({report.assessments.length})</summary><ul className="space-y-2 pt-2">{report.assessments.map((assessment) => <li key={assessment.id} className="rounded bg-zinc-50 p-3 leading-5"><p>Actor {assessment.actor} · {label(assessment.reviewer_kind)} · usefulness {label(assessment.usefulness)} · abstention {label(assessment.abstention)}</p><p>{assessment.rationale}</p><p>Omissions: {assessment.omitted_contradictions.join('; ') || 'None identified'}</p><p>Attribution: {assessment.attribution_errors.join('; ') || 'None identified'}</p><p>Limitations: {assessment.limitations}</p></li>)}</ul></details>}
    {report.limitations.map((item, index) => <p key={index} className="text-xs leading-5 text-amber-900">{item}</p>)}
    <Button variant="outline" size="sm" onClick={() => { const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `claim-support-${report.run_id}.json`; anchor.click(); URL.revokeObjectURL(url) }}>Download claim-support report</Button>
  </section>
}

export function SemanticRunReview({ runId, selfReview = false }: { runId: string; selfReview?: boolean }) {
  const { user } = useAuth()
  const client = useQueryClient()
  const packet = useQuery({ queryKey: ['ai-review-packet', user?.id, runId], queryFn: () => incidentApi.aiReviewPacket(runId), enabled: !!user, retry: false })
  const report = useQuery({ queryKey: ['ai-review-report', user?.id, runId], queryFn: () => incidentApi.aiReviewReport(runId), enabled: !!user, retry: false })
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: ['ai-review-packet'] }), client.invalidateQueries({ queryKey: ['ai-review-report'] }), client.invalidateQueries({ queryKey: ['ai-review-queue'] }), client.invalidateQueries({ queryKey: ['incident-evaluation'] })]) }
  if (!user) return <p className="text-xs text-zinc-600">Sign in as a reviewer to examine the pinned review packet.</p>
  if (packet.isPending) return <p role="status" className="text-xs">Loading pinned review packet…</p>
  if (packet.isError) return <div role="alert" className="space-y-2 rounded border border-amber-200 p-3 text-xs text-amber-900"><p>Review packet unavailable: {packet.error.message}</p><Button size="sm" variant="outline" onClick={() => packet.refetch()}>Reload review packet</Button></div>
  const run = packet.data
  const requesterReview = selfReview || run.requested_by === user.id
  return <section aria-label={`Semantic review ${run.id}`} className="space-y-4 border-t border-zinc-200 pt-4">
    <div><h2 className="text-base font-semibold">Review pinned output and evidence</h2><dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2"><div><dt className="text-zinc-600">Run / deterministic analysis</dt><dd className="break-all font-mono">{run.id} / {run.analysis_id}{run.packet.analysis_digest && <span className="mt-1 block">Analysis digest: {run.packet.analysis_digest}</span>}</dd></div><div><dt className="text-zinc-600">Provider / model / task</dt><dd>{run.provider} / {run.model ?? 'Not supplied'} / {run.task}</dd></div><div><dt className="text-zinc-600">Evidence incident / revision / cutoff</dt><dd>{run.packet.incident_id ?? 'Not supplied'} / {run.packet.revision ?? 'Not supplied'} / {run.packet.cutoff ?? 'Not supplied'}</dd></div><div><dt className="text-zinc-600">Exact output digest</dt><dd className="break-all font-mono">{run.output_digest}</dd></div></dl>{run.packet.incident_id && run.packet.revision != null && <Link className="mt-3 inline-block text-xs underline underline-offset-4" to={`/incidents/${encodeURIComponent(run.packet.incident_id)}?revision=${run.packet.revision}&analysis=${encodeURIComponent(run.analysis_id)}`}>Open pinned calculation and source inputs</Link>}</div>
    {claimEntries(run.output).map(({ claim, path }) => <ClaimAnnotation key={`${run.id}:${run.output_digest}:${path}:${user.id}`} run={run} claim={claim} path={path} refresh={refresh} selfReview={requesterReview} />)}
    {!(claimEntries(run.output).length) && <p className="text-xs text-zinc-600">No factual claims are present. Assess the draft’s abstention and usefulness below.</p>}
    <CompleteReviewContext key={`${run.id}:${run.output_digest}`} run={run} />
    <RunAssessment key={`${run.id}:${run.output_digest}:${user.id}`} run={run} refresh={refresh} selfReview={requesterReview} />
    {report.data && <ReviewReport report={report.data} />}
    {report.isError && <p role="alert" className="text-xs text-red-800">Review report unavailable: {report.error.message}</p>}
  </section>
}

export function SemanticReviewInbox() {
  const { user } = useAuth()
  return <ReviewInbox key={user?.id ?? 'anonymous'} />
}
function ReviewInbox() {
  const { user } = useAuth()
  const [selected, setSelected] = useState('')
  const queue = useQuery({ queryKey: ['ai-review-queue', user?.id], queryFn: incidentApi.aiReviewQueue, enabled: !!user, retry: false })
  return <section id="semantic-review-inbox" className="space-y-4 rounded-xl border border-zinc-200 bg-white p-5 sm:p-6"><h2 className="text-lg font-semibold">Claim-support review inbox</h2><p className="text-sm leading-6 text-zinc-600">Review drafts deliberately published by their creator or an owner. Inspect claim wording beside the exact cited records, annotate support, and assess omissions and useful next checks. AI annotations and self-review remain distinct from declared independent human review.</p>
    {!user ? <p className="text-xs text-zinc-600">Sign in as an invited reviewer to open published review packets. Reviewing a saved draft starts no provider request.</p> : queue.isPending ? <p role="status" className="text-xs">Loading published review packets…</p> : queue.isError ? <div role="alert" className="space-y-2 text-xs text-red-800"><p>Review inbox unavailable: {queue.error.message}</p><Button size="sm" variant="outline" onClick={() => queue.refetch()}>Reload review inbox</Button></div> : <>
      {queue.data.items.length === 0 ? <p className="text-sm text-zinc-600">No completed draft has been published for review.</p> : <><label htmlFor="semantic-review-run" className="block text-xs font-medium">Published output</label><select id="semantic-review-run" className={selectClass} value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Choose a draft to inspect</option>{queue.data.items.map((run) => <option key={run.id} value={run.id}>{run.id} · {run.model ?? 'Model not supplied'} · {run.task} · {run.reviewed_claims}/{run.claim_count} claims annotated</option>)}</select></>}
      <Button size="sm" variant="outline" onClick={() => queue.refetch()}>Refresh review inbox</Button>
      {selected && <SemanticRunReview key={`${selected}:${user.id}`} runId={selected} />}
    </>}
  </section>
}
