import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { AnalysisReport, RecoveryProposal } from '@/lib/incidents'
import { formatInstant } from '@/lib/status'
import { workflowApi } from '@/lib/workflow'
import type { CompleteCheckRequest, CreateCheckRequest, IncidentWorkflowData, RespondCheckRequest, ResolveIncidentRequest, UpdateCheckRequest, WorkflowAssignee, WorkflowTask } from '@/lib/workflow'

const selectClass = 'min-h-10 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm'
const indiaInstant = (value: string) => `${value.length === 16 ? `${value}:00` : value}+05:30`
const indiaDateInput = (value: number) => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(new Date(value)).replace(' ', 'T')
const fieldLabel = (value: string) => value.replaceAll('_', ' ')
const terminal = (task: WorkflowTask) => task.status === 'COMPLETED' || task.status === 'CANCELLED'

function WriteFeedback<TData, TBody>({ mutation }: { mutation: UseMutationResult<TData, Error, TBody> }) {
  return <>
    {mutation.isSuccess && <p role="status" className="text-xs text-emerald-800">Saved to the incident history.</p>}
    {mutation.error && <div role="alert" className="space-y-2 rounded border border-red-200 bg-red-50 p-3 text-xs text-red-900">
      <p>{mutation.error.message}</p><p>If the connection failed, the server may have saved the request. Retry sends the exact same request safely. Reload the workflow before editing a conflicting request.</p>
      <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" onClick={() => { if (mutation.variables) mutation.mutate(mutation.variables) }}>Retry same request</Button><Button type="button" size="sm" variant="outline" onClick={() => mutation.reset()}>Edit as a new request</Button></div>
    </div>}
  </>
}

function AssignCheck({ proposal, report, assignees, refresh }: { proposal: RecoveryProposal; report: AnalysisReport; assignees: WorkflowAssignee[]; refresh: () => Promise<void> }) {
  const [assignee, setAssignee] = useState('')
  const [due, setDue] = useState('')
  const create = useMutation({ mutationFn: (body: CreateCheckRequest) => workflowApi.create(report.id, body), onSuccess: refresh, retry: false })
  const locked = create.isPending || create.isError || create.isSuccess
  return <form aria-label={`Assign check: ${fieldLabel(proposal.type)}`} className="space-y-3 rounded-md border border-zinc-200 p-4" onSubmit={(event) => {
    event.preventDefault()
    create.mutate({ proposal_id: proposal.id, assignee_id: assignee, due_at: indiaInstant(due), idempotency_key: crypto.randomUUID() })
  }}>
    <h4 className="text-sm font-medium">{fieldLabel(proposal.type)}</h4><p className="text-xs leading-5 text-zinc-600">{proposal.purpose}</p>
    <p className="text-xs leading-5 text-zinc-600">This assigns an evidence check. Assignment does not approve the recovery proposal or confirm its explanation.</p>
    <div><label htmlFor={`check-assignee-${proposal.id}`} className="block text-xs">Named assignee</label><select id={`check-assignee-${proposal.id}`} required className={`${selectClass} mt-1`} value={assignee} disabled={locked} onChange={(event) => setAssignee(event.target.value)}><option value="">Choose an active reviewer</option>{assignees.map((person) => <option key={person.id} value={person.id}>{person.display_name} ({person.username})</option>)}</select></div>
    <label className="block text-xs">Due at (India time)<Input type="datetime-local" step="1" required className="mt-1" value={due} disabled={locked} onChange={(event) => setDue(event.target.value)} /></label>
    <Button size="sm" disabled={locked || !assignees.length}>{create.isPending ? 'Assigning check…' : create.isSuccess ? 'Check assigned' : 'Assign evidence check'}</Button>
    <WriteFeedback mutation={create} />
  </form>
}

function UpdateCheck({ task, assignees, canManage, canStart, refresh }: { task: WorkflowTask; assignees: WorkflowAssignee[]; canManage: boolean; canStart: boolean; refresh: () => Promise<void> }) {
  const [comment, setComment] = useState('')
  const [assignee, setAssignee] = useState('')
  const [due, setDue] = useState('')
  const update = useMutation({ mutationFn: (body: UpdateCheckRequest) => workflowApi.update(task.id, body), onSuccess: refresh, retry: false })
  const locked = update.isPending || update.isError
  const send = (status: UpdateCheckRequest['status']) => update.mutate({
    status, comment: comment.trim(), assignee_id: assignee || null, due_at: due ? indiaInstant(due) : null,
    expected_updated_at: task.updated_at, idempotency_key: crypto.randomUUID(),
  })
  return <details className="print:hidden"><summary className="cursor-pointer py-2 text-xs font-medium underline underline-offset-4">Comments and assignment history</summary>
    <form className="mt-2 space-y-3" onSubmit={(event) => { event.preventDefault(); send(null) }}>
      <label className="block text-xs">Comment or reassignment reason<textarea required minLength={3} className={`${selectClass} mt-1 min-h-20 p-3`} value={comment} disabled={locked} onChange={(event) => setComment(event.target.value)} /></label>
      {canManage && !terminal(task) && <div className="grid gap-3 sm:grid-cols-2">
        <div><label htmlFor={`reassign-${task.id}`} className="block text-xs">Reassign to</label><select id={`reassign-${task.id}`} className={`${selectClass} mt-1`} value={assignee} disabled={locked} onChange={(event) => setAssignee(event.target.value)}><option value="">Keep {task.assignee_name}</option>{assignees.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></div>
        <label className="block text-xs">New due at (India time)<Input type="datetime-local" step="1" className="mt-1" value={due} disabled={locked} onChange={(event) => setDue(event.target.value)} /></label>
      </div>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={locked || comment.trim().length < 3}>Save comment or assignment</Button>
        {canStart && task.status === 'OPEN' && <Button type="button" variant="outline" size="sm" disabled={locked || comment.trim().length < 3} onClick={() => send('IN_PROGRESS')}>Start check</Button>}
        {canManage && !terminal(task) && <Button type="button" variant="outline" size="sm" disabled={locked || comment.trim().length < 3} onClick={() => send('CANCELLED')}>Cancel check with reason</Button>}
      </div>
      <WriteFeedback mutation={update} />
    </form>
  </details>
}

function SourceResponse({ task, currentRevision, onPublished }: { task: WorkflowTask; currentRevision: number; onPublished: (revision: number) => Promise<void> }) {
  const [summary, setSummary] = useState('')
  const [sourceRef, setSourceRef] = useState('')
  const [occurred, setOccurred] = useState('')
  const [details, setDetails] = useState<Record<string, string>>({})
  const [blocking, setBlocking] = useState(false)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const respond = useMutation({ mutationFn: (body: RespondCheckRequest) => workflowApi.respond(task.id, body), onSuccess: async (result) => { if (result.response) await onPublished(result.response.revision) }, retry: false })
  const locked = respond.isPending || respond.isError
  return <details className="print:hidden"><summary className="cursor-pointer py-2 text-xs font-medium underline underline-offset-4">Record source response</summary>
    <form className="mt-2 space-y-3" onSubmit={(event) => {
      event.preventDefault()
      respond.mutate({ base_revision: currentRevision, summary: summary.trim(), source_ref: sourceRef.trim(), occurred_at: indiaInstant(occurred), details: { ...details }, line_blocking: blocking, start: blocking ? indiaInstant(start) : null, end: blocking ? indiaInstant(end) : null, idempotency_key: crypto.randomUUID() })
    }}>
      <p className="text-xs leading-5 text-zinc-600">Use a source record or a named observation. Saving appends structured evidence to revision {currentRevision + 1} and opens that revision; earlier reports remain intact.</p>
      <label className="block text-xs">Response summary<textarea required className={`${selectClass} mt-1 min-h-20 p-3`} value={summary} disabled={locked} onChange={(event) => setSummary(event.target.value)} /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs">Source record reference<Input required className="mt-1" value={sourceRef} disabled={locked} onChange={(event) => setSourceRef(event.target.value)} /></label>
        <label className="block text-xs">Observation occurred at (India time)<Input type="datetime-local" step="1" required className="mt-1" value={occurred} disabled={locked} onChange={(event) => setOccurred(event.target.value)} /></label>
      </div>
      {task.requested_fields.map((name) => <label key={name} className="block text-xs">{fieldLabel(name)}<Input required className="mt-1" value={details[name] ?? ''} disabled={locked} onChange={(event) => setDetails({ ...details, [name]: event.target.value })} /></label>)}
      <label className="flex items-start gap-2 text-xs"><input type="checkbox" className="mt-0.5" checked={blocking} disabled={locked} onChange={(event) => setBlocking(event.target.checked)} />Source explicitly confirms a line-wide production block</label>
      {blocking && <div className="grid gap-3 sm:grid-cols-2"><label className="block text-xs">Confirmed block start (India time)<Input type="datetime-local" step="1" required className="mt-1" value={start} disabled={locked} onChange={(event) => setStart(event.target.value)} /></label><label className="block text-xs">Confirmed block end (India time)<Input type="datetime-local" step="1" required className="mt-1" value={end} disabled={locked} onChange={(event) => setEnd(event.target.value)} /></label></div>}
      <Button size="sm" disabled={locked}>{respond.isPending ? 'Publishing response…' : 'Publish source response as new revision'}</Button>
      <WriteFeedback mutation={respond} />
    </form>
  </details>
}

function CompleteCheck({ task, refresh }: { task: WorkflowTask; refresh: () => Promise<void> }) {
  const [action, setAction] = useState('')
  const [completed, setCompleted] = useState('')
  const [units, setUnits] = useState('')
  const [observed, setObserved] = useState('')
  const [assessment, setAssessment] = useState('')
  const [uncertainty, setUncertainty] = useState('')
  const complete = useMutation({ mutationFn: (body: CompleteCheckRequest) => workflowApi.complete(task.id, body), onSuccess: refresh, retry: false })
  const locked = complete.isPending || complete.isError
  return <details className="print:hidden"><summary className="cursor-pointer py-2 text-xs font-medium underline underline-offset-4">Record action and measured outcome</summary>
    <form className="mt-2 space-y-3" onSubmit={(event) => {
      event.preventDefault()
      complete.mutate({ action_taken: action.trim(), actual_completed_at: indiaInstant(completed), observed_good_units: units === '' ? null : Number(units), observed_at: units === '' ? null : indiaInstant(observed), assessment: assessment.trim(), remaining_uncertainty: uncertainty.trim(), idempotency_key: crypto.randomUUID() })
    }}>
      <p className="text-xs leading-5 text-zinc-600">Completing this check records what happened. It does not resolve the incident or prove that the action caused production to recover.</p>
      <label className="block text-xs">Action actually taken<textarea required className={`${selectClass} mt-1 min-h-20 p-3`} value={action} disabled={locked} onChange={(event) => setAction(event.target.value)} /></label>
      <label className="block text-xs">Actual completion at (India time)<Input type="datetime-local" step="1" required className="mt-1" min={indiaDateInput(Math.ceil(Date.parse(task.created_at) / 1000) * 1000)} value={completed} disabled={locked} onChange={(event) => setCompleted(event.target.value)} /></label>
      <div className="grid gap-3 sm:grid-cols-2"><label className="block text-xs">Observed good units (optional)<Input type="number" min="0" step="1" className="mt-1" value={units} disabled={locked} onChange={(event) => setUnits(event.target.value)} /></label><label className="block text-xs">Output observed at (India time)<Input type="datetime-local" step="1" required={units !== ''} min={completed || undefined} className="mt-1" value={observed} disabled={locked || units === ''} onChange={(event) => setObserved(event.target.value)} /></label></div>
      <label className="block text-xs">Outcome assessment<textarea required className={`${selectClass} mt-1 min-h-20 p-3`} value={assessment} disabled={locked} onChange={(event) => setAssessment(event.target.value)} /></label>
      <label className="block text-xs">Remaining uncertainty<textarea required className={`${selectClass} mt-1 min-h-20 p-3`} placeholder="Record unresolved questions, or explicitly say none identified." value={uncertainty} disabled={locked} onChange={(event) => setUncertainty(event.target.value)} /></label>
      <Button size="sm" disabled={locked}>{complete.isPending ? 'Saving outcome…' : 'Complete check and record outcome'}</Button>
      <WriteFeedback mutation={complete} />
    </form>
  </details>
}

function TaskCard({ task, currentRevision, assignees, refresh, onPublished }: { task: WorkflowTask; currentRevision: number; assignees: WorkflowAssignee[]; refresh: () => Promise<void>; onPublished: (revision: number) => Promise<void> }) {
  const { user } = useAuth()
  const canAct = user?.role === 'owner' || user?.id === task.assignee_id
  const canManage = user?.role === 'owner' || user?.id === task.created_by
  return <article aria-label={`Evidence check: ${task.question}`} className="space-y-3 rounded-md border border-zinc-200 bg-white p-4 print:break-inside-avoid">
    <div className="flex flex-wrap items-start justify-between gap-2"><h4 className="max-w-2xl text-sm font-medium leading-6">{task.question}</h4><span className={`rounded px-2 py-1 text-xs ${task.overdue ? 'bg-amber-100 text-amber-900' : 'bg-zinc-100 text-zinc-700'}`}>{fieldLabel(task.status.toLowerCase())}{task.overdue ? ' · overdue' : ''}</span></div>
    <p className="text-xs leading-5 text-zinc-600">Assigned to {task.assignee_name} · due {formatInstant(task.due_at)} · requested against revision {task.revision}</p>
    {task.response && <div className="rounded bg-zinc-50 p-3 text-xs leading-5"><p className="font-medium">Source response · evidence revision {task.response.revision}</p><p>{task.response.summary}</p><p>Source: {task.response.source_ref} · observation {formatInstant(task.response.occurred_at)} · evidence {task.response.evidence_id}</p><dl className="mt-2 space-y-1">{Object.entries(task.response.details).map(([name, value]) => <div key={name}><dt className="inline font-medium">{fieldLabel(name)}: </dt><dd className="inline">{value}</dd></div>)}</dl></div>}
    {task.outcome && <div className="rounded border border-emerald-200 p-3 text-xs leading-5"><p className="font-medium">Recorded outcome</p><p>{task.outcome.action_taken} · completed {formatInstant(task.outcome.actual_completed_at)}</p>{task.outcome.observed_good_units !== null && <p>{task.outcome.observed_good_units} observed good units{task.outcome.observed_at && <> at {formatInstant(task.outcome.observed_at)}</>}</p>}<p>Assessment: {task.outcome.assessment}</p><p>Remaining uncertainty: {task.outcome.remaining_uncertainty}</p></div>}
    <UpdateCheck key={`${task.id}:${task.updated_at}`} task={task} assignees={assignees} canManage={canManage} canStart={canAct} refresh={refresh} />
    {canAct && (task.status === 'OPEN' || task.status === 'IN_PROGRESS') && <SourceResponse task={task} currentRevision={currentRevision} onPublished={onPublished} />}
    {canAct && task.status === 'ANSWERED' && <CompleteCheck task={task} refresh={refresh} />}
    {task.activities.length > 0 && <details className="text-xs print:break-inside-avoid"><summary className="cursor-pointer py-2 font-medium">Audit history ({task.activities.length})</summary><ol className="mt-2 space-y-2 border-l border-zinc-200 pl-3">{task.activities.map((activity) => <li key={activity.id} className="leading-5"><p>{fieldLabel(activity.kind)} · {activity.actor} · {formatInstant(activity.created_at)}</p><p className="text-zinc-600">{activity.text}</p></li>)}</ol></details>}
  </article>
}

function ResolutionControl({ workflow, refresh }: { workflow: IncidentWorkflowData; refresh: () => Promise<void> }) {
  const [rationale, setRationale] = useState('')
  const resolution = useMutation({ mutationFn: (body: ResolveIncidentRequest) => workflowApi.resolution(workflow.incident_id, body), onSuccess: refresh, retry: false })
  const ready = workflow.tasks.some((task) => task.status === 'COMPLETED') && workflow.tasks.every(terminal)
  return <form className="space-y-3 rounded border border-zinc-200 p-4 print:hidden" onSubmit={(event) => {
    event.preventDefault()
    resolution.mutate({ base_revision: workflow.current_revision, state: workflow.resolution === 'OPEN' ? 'RESOLVED' : 'OPEN', rationale: rationale.trim(), idempotency_key: crypto.randomUUID() })
  }}>
    <h3 className="text-sm font-medium">Separate incident decision</h3>
    <p className="text-xs leading-5 text-zinc-600">A supervisor records resolution separately from check completion. Resolve only after all checks are completed or cancelled and at least one completed outcome is recorded.</p>
    <label className="block text-xs">Resolution or reopening rationale<textarea required className={`${selectClass} mt-1 min-h-20 p-3`} value={rationale} disabled={resolution.isPending || resolution.isError} onChange={(event) => setRationale(event.target.value)} /></label>
    <Button size="sm" disabled={resolution.isPending || resolution.isError || (workflow.resolution === 'OPEN' && !ready)}>{resolution.isPending ? 'Saving decision…' : workflow.resolution === 'OPEN' ? 'Record incident resolved' : 'Reopen incident'}</Button>
    <WriteFeedback mutation={resolution} />
  </form>
}

export function IncidentWorkflow({ report, currentRevision, onRevisionPublished }: { report: AnalysisReport; currentRevision: number; onRevisionPublished: (revision: number) => void }) {
  const { user } = useAuth()
  const client = useQueryClient()
  const enabled = !!user && report.execution_kind !== 'saved_deterministic'
  const workflow = useQuery({ queryKey: ['incident-workflow', report.incident_id, user?.id, currentRevision, report.revision], queryFn: () => workflowApi.get(report.incident_id), enabled, retry: false })
  const assignees = useQuery({ queryKey: ['workflow-assignees', user?.id], queryFn: workflowApi.assignees, enabled, retry: false })
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: ['incident-workflow', report.incident_id] }), client.invalidateQueries({ queryKey: ['incidents'] })]) }
  const published = async (revision: number) => { await refresh(); await client.invalidateQueries({ queryKey: ['incident', report.incident_id] }); onRevisionPublished(revision) }
  const data = workflow.data
  const latest = data?.current_revision ?? currentRevision
  const assignableProposals = report.proposals.filter((proposal) => !data?.tasks.some((task) => task.proposal_id === proposal.id && !terminal(task)))
  return <section id="assigned-checks" aria-labelledby="incident-workflow-heading" className="space-y-4 border-t border-zinc-200 pt-6">
    <div><h2 id="incident-workflow-heading" className="text-lg font-semibold tracking-tight">Assigned checks and outcomes</h2><p className="mt-1 max-w-3xl text-sm leading-6 text-zinc-600">Turn a recovery proposal into a named evidence check, preserve the source response, and record the action and observed result. This workflow shows the latest incident state, separately from the report revision above.</p></div>
    {!enabled ? <p className="rounded border border-zinc-200 p-4 text-sm text-zinc-600">{report.execution_kind === 'saved_deterministic' ? 'Saved reports show the investigation offline. Assignments and outcome history require the live API and reviewer sign-in.' : 'Sign in as an owner or invited reviewer to view private assignments, outcomes, and the shift handover. Published source responses appear in the incident evidence.'}</p> : workflow.isPending ? <p role="status" className="text-sm">Loading assigned checks…</p> : workflow.isError ? <div role="alert" className="space-y-2 rounded border border-red-200 p-4 text-sm text-red-800"><p>Workflow unavailable: {workflow.error.message}</p><Button size="sm" variant="outline" onClick={() => workflow.refetch()}>Reload workflow</Button></div> : data && <>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-zinc-50 p-4"><div><p className="text-sm font-medium">Incident {data.resolution.toLowerCase()}</p><p className="mt-1 text-xs text-zinc-600">{data.tasks.filter((task) => !terminal(task)).length} outstanding checks · {data.tasks.filter((task) => task.overdue).length} overdue · {data.tasks.filter((task) => task.status === 'COMPLETED').length} recorded outcomes</p>{data.resolution_rationale && <p className="mt-2 text-xs leading-5">Decision rationale: {data.resolution_rationale}</p>}</div><Button variant="outline" size="sm" className="print:hidden" onClick={() => workflow.refetch()}>Reload workflow</Button></div>
      <section id="shift-handover" aria-labelledby="shift-handover-heading" className="space-y-2 rounded-md border border-zinc-200 p-4 print:break-inside-avoid"><h3 id="shift-handover-heading" className="text-sm font-semibold">Shift handover</h3><p className="text-sm leading-6">{data.handover.summary}</p><p className="text-xs text-zinc-600">Evidence available by {formatInstant(data.handover.cutoff)} · latest revision {latest}</p>{data.handover.uncertainties.length > 0 && <ul className="list-disc space-y-1 pl-4 text-xs leading-5">{data.handover.uncertainties.map((value, index) => <li key={`${index}-${value}`}>{value}</li>)}</ul>}<p className="text-xs font-medium">Outstanding checks</p>{data.handover.outstanding_checks.length ? <ul className="space-y-1 text-xs leading-5">{data.handover.outstanding_checks.map((task) => <li key={task.id}>{task.question} · {task.assignee_name} · due {formatInstant(task.due_at)}{task.overdue ? ' · overdue' : ''}</li>)}</ul> : <p className="text-xs text-zinc-600">No outstanding checks recorded.</p>}<Button type="button" variant="outline" size="sm" className="print:hidden" onClick={() => window.print()}>Print report and handover</Button></section>
      {data.tasks.length ? <div className="space-y-3">{data.tasks.map((task) => <TaskCard key={task.id} task={task} currentRevision={latest} assignees={assignees.data?.items ?? []} refresh={refresh} onPublished={published} />)}</div> : <p className="rounded border border-dashed border-zinc-300 p-4 text-sm text-zinc-600">No evidence checks assigned yet.</p>}
      <div className="space-y-3 print:hidden"><h3 className="text-sm font-semibold">Assign a next check</h3>{report.revision !== latest ? <div className="space-y-2 text-xs text-amber-900"><p>This report is revision {report.revision}. Open revision {latest} to create checks against current evidence.</p><Button type="button" size="sm" variant="outline" onClick={() => onRevisionPublished(latest)}>Open latest evidence revision</Button></div> : data.resolution === 'RESOLVED' ? <p className="text-xs text-zinc-600">Reopen the incident before assigning another check.</p> : assignees.isPending ? <p role="status" className="text-xs">Loading active reviewers…</p> : assignees.isError ? <div role="alert" className="space-y-2 text-xs text-red-800"><p>Assignees unavailable: {assignees.error.message}</p><Button type="button" size="sm" variant="outline" onClick={() => assignees.refetch()}>Reload assignees</Button></div> : <div className="grid gap-3 lg:grid-cols-2">{assignableProposals.length === 0 && <p className="text-xs text-zinc-600">{report.proposals.length ? 'Each current proposal already has an outstanding check.' : 'No recovery proposal supports a new check at this revision.'}</p>}{assignableProposals.map((proposal) => <AssignCheck key={`${report.id}:${proposal.id}`} proposal={proposal} report={report} assignees={assignees.data?.items ?? []} refresh={refresh} />)}</div>}</div>
      <ResolutionControl workflow={data} refresh={refresh} />
      {data.resolution_activities?.length > 0 && <details className="text-xs"><summary className="cursor-pointer py-2 font-medium">Incident decision history</summary><ol className="space-y-2">{data.resolution_activities.map((activity) => <li key={activity.id}>{fieldLabel(activity.kind)} · {activity.actor} · {formatInstant(activity.created_at)}<p>{activity.text}</p></li>)}</ol></details>}
    </>}
  </section>
}
