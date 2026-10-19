import { useLayoutEffect, useState } from 'react'
import { ArrowLeft, FileText } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useParams, useSearchParams } from 'react-router'
import {
  incidentApi,
  type AnalysisReport,
  type Hypothesis,
  type RecoveryProposal,
} from '@/lib/incidents'
import { api } from '@/lib/api'
import { formatInstant } from '@/lib/status'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/components/Auth'
import {
  OpenAiPanel,
  HybridPanel,
  ExportReport,
  PrecedentConditions,
} from '@/components/IncidentAi'
import { Skeleton } from '@/components/ui/skeleton'
import {
  BoardStat,
  EvidenceLink,
  EvidenceList,
  FieldLabel,
  Limits,
  NativeSelect,
  PageHeader,
  Section,
  StatusTag,
  type Tone,
} from '@/components/board'
import { SectionRail } from '@/components/SectionRail'
import { BucketStrip } from '@/components/BucketStrip'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import savedAi from '@/data/hero-ai.json'
import { RevisionComparison } from '@/components/RevisionComparison'
import { IncidentWorkflow } from '@/components/IncidentWorkflow'
import { SupervisorReport } from '@/components/SupervisorReport'

function hypothesisTone(status: string): Tone {
  const value = status.toUpperCase()
  if (value === 'SUPPORTED') return 'success'
  if (value.includes('CONTRADICT')) return 'danger'
  return 'limit'
}

function HypothesisCard({
  item,
  onEvidence,
}: {
  item: Hypothesis
  onEvidence: (id: string) => void
}) {
  return (
    <article className="rounded-sm border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-bold">{item.category.replace(/_/g, ' ')}</h3>
        <StatusTag tone={hypothesisTone(item.status)}>{item.status.replace(/_/g, ' ')}</StatusTag>
      </div>
      <p className="mt-2 text-sm leading-6 text-foreground">{item.mechanism}</p>
      <dl className="mt-3 grid gap-3 border-t border-border pt-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="mb-1 font-semibold text-muted-foreground">Supporting evidence</dt>
          <dd>
            <EvidenceList ids={item.supporting_evidence} onOpen={onEvidence} />
          </dd>
        </div>
        <div>
          <dt className="mb-1 font-semibold text-muted-foreground">Contradictions</dt>
          <dd>
            <EvidenceList ids={item.contradicting_evidence} onOpen={onEvidence} />
          </dd>
        </div>
      </dl>
      <Limits className="mt-3">
        <strong>Next check:</strong> {item.next_check}
      </Limits>
    </article>
  )
}

function ProposalCard({
  item,
  report,
  currentRevision,
  canReview,
  onEvidence,
  onChanged,
}: {
  item: RecoveryProposal
  report: AnalysisReport
  currentRevision: number
  canReview: boolean
  onEvidence: (id: string) => void
  onChanged: () => void
}) {
  const { user } = useAuth()
  const [rationale, setRationale] = useState('')
  const [reviewOpen, setReviewOpen] = useState(false)
  const [message, setMessage] = useState('')
  const stale = report.revision !== currentRevision || report.stale === true
  const reviewState =
    report.reviews?.filter((review) => review.proposal_id === item.id).at(-1)?.state ?? item.state
  const submit = useMutation({
    mutationFn: () => incidentApi.submitProposal(report.id, item.id),
    onSuccess: () => {
      setMessage('Submitted for human review.')
      onChanged()
    },
    onError: (error) => setMessage(error.message),
  })
  const review = useMutation({
    mutationFn: (decision: 'APPROVED' | 'REJECTED') =>
      incidentApi.reviewProposal(report.id, item.id, decision, rationale.trim()),
    onSuccess: () => {
      setMessage('Review recorded. No factory action was executed.')
      setReviewOpen(false)
      onChanged()
    },
    onError: (error) => setMessage(error.message),
  })
  return (
    <article className="rounded-sm border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-bold">{item.type.replace(/_/g, ' ')}</h3>
        <StatusTag>{reviewState.replace(/_/g, ' ')}</StatusTag>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Owner: {item.owner_role.replace(/_/g, ' ')}
      </p>
      <p className="mt-2 text-sm text-foreground">{item.purpose}</p>
      <div className="mt-3 space-y-2 text-sm text-foreground">
        {item.preconditions.length > 0 && (
          <p>
            <strong>Before acting:</strong> {item.preconditions.join('; ')}
          </p>
        )}
        {item.missing_information.length > 0 && (
          <p>
            <strong>Still needed:</strong> {item.missing_information.join('; ')}
          </p>
        )}
        <div>
          <span className="mb-1 block font-semibold">Evidence</span>
          <EvidenceList ids={item.supporting_evidence} onOpen={onEvidence} />
        </div>
      </div>
      <div className="mt-4 border-t border-border pt-3 print:hidden">
        {stale && (
          <p className="mb-2 text-sm font-semibold text-limit-foreground">
            This proposal belongs to revision {report.revision}. Open the current revision before
            review.
          </p>
        )}
        {!canReview && (
          <p className="text-sm text-muted-foreground">
            Sign in as an invited reviewer to record decisions.
          </p>
        )}
        {canReview && reviewState === 'DRAFT' && (
          <Button
            size="sm"
            variant="outline"
            disabled={stale || submit.isPending}
            onClick={() => submit.mutate()}
          >
            {submit.isPending ? 'Submitting…' : 'Submit for review'}
          </Button>
        )}
        {canReview && reviewState === 'PENDING_REVIEW' && !reviewOpen && (
          <Button size="sm" variant="outline" disabled={stale} onClick={() => setReviewOpen(true)}>
            Record review
          </Button>
        )}
        {reviewOpen && (
          <div className="space-y-2">
            <p className="text-sm">Reviewer: {user?.display_name}</p>
            <div>
              <label htmlFor={`reason-${item.id}`} className="mb-1 block text-sm font-semibold">
                Review rationale
              </label>
              <textarea
                id={`reason-${item.id}`}
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                className="min-h-20 w-full rounded-md border border-input bg-card p-2 text-sm focus-visible:outline-2"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={!rationale.trim() || stale || review.isPending}
                onClick={() => review.mutate('APPROVED')}
              >
                Approve review
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!rationale.trim() || stale || review.isPending}
                onClick={() => review.mutate('REJECTED')}
              >
                Reject
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setReviewOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {message && (
          <p role="status" className="mt-2 text-sm text-foreground">
            {message}
          </p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Review records a decision against this report. It does not execute a factory change.
        </p>
      </div>
    </article>
  )
}

function SavedAiPanel({ onEvidence }: { onEvidence: (id: string) => void }) {
  return (
    <Section
      title="Historical local-model result"
      detail="Qwen archive · historical provider evidence · Experimental · author-reviewed synthetic case · recorded output from an earlier local run"
    >
      <div className="rounded-sm border border-border bg-card p-4">
        <p className="text-sm text-muted-foreground">
          {savedAi.model} · {savedAi.elapsed_seconds} seconds · {savedAi.execution_kind}
        </p>
        <p className="mt-2 text-sm text-limit-foreground">{savedAi.quality_notice}</p>
        <ol className="mt-4 space-y-4">
          {savedAi.claims.map((claim, index) => (
            <li key={index} className="border-t border-border pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-muted-foreground">
                  Claim {index + 1}
                </span>
                <StatusTag tone={claim.review_status === 'SUPPORTED' ? 'success' : 'limit'}>
                  {claim.review_status.replace(/_/g, ' ')}
                </StatusTag>
              </div>
              <p className="mt-2 text-sm leading-6 text-foreground">{claim.text}</p>
              {claim.review_reason && (
                <p className="mt-1 text-sm text-limit-foreground">
                  <strong>Reviewer note:</strong> {claim.review_reason}
                </p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <span>Evidence:</span>
                <EvidenceList ids={claim.evidence_ids} onOpen={onEvidence} />
                {claim.metric_ids.length > 0 && <span>Metrics: {claim.metric_ids.join(', ')}</span>}
              </div>
            </li>
          ))}
        </ol>
        {savedAi.limitations.length > 0 && (
          <Limits tone="neutral" className="mt-4">
            <strong>Limitations</strong>
            <ul className="mt-1 list-disc space-y-1 pl-4">
              {savedAi.limitations.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </Limits>
        )}
      </div>
    </Section>
  )
}

const RAIL_TITLES = [
  'Observed situation',
  'Evidence timeline',
  'Explanations and open questions',
  'Recovery options',
  'Assigned checks',
  'Shift handover',
  'Shift update',
] as const

export function IncidentWorkbenchPage() {
  const { user } = useAuth()
  const { id = '' } = useParams()
  const { pathname } = useLocation()
  const [params, setParams] = useSearchParams()
  const queryClient = useQueryClient()
  const capabilities = useQuery({
    queryKey: ['capabilities', user?.id ?? 'public'],
    queryFn: api.capabilities,
    staleTime: 60_000,
  })
  const library = useQuery({
    queryKey: ['incidents', user?.id ?? 'public'],
    queryFn: incidentApi.list,
  })
  const summary = library.data?.items.find((item) => item.id === id)
  const requestedRevision = params.get('revision')
  const revision = requestedRevision === null ? (summary?.revision ?? 1) : Number(requestedRevision)
  // Reject 0, fractions, NaN and padded forms instead of requesting a revision that cannot exist.
  const validRevision =
    Number.isSafeInteger(revision) &&
    revision > 0 &&
    (requestedRevision === null || /^[1-9]\d*$/.test(requestedRevision))
  const analysisId = params.get('analysis')
  const [evidenceId, setEvidenceId] = useState<string | null>(null)
  const incident = useQuery({
    queryKey: ['incident', id, revision, user?.id ?? 'public'],
    queryFn: () => incidentApi.revision(id, revision),
    enabled: validRevision && !!id && (!!params.get('revision') || !!summary || library.isError),
  })
  const reportQuery = useQuery({
    queryKey: ['incident-analysis', id, revision, analysisId, user?.id ?? 'public'],
    queryFn: () =>
      analysisId ? incidentApi.analysis(analysisId) : incidentApi.analyze(id, revision),
    enabled: !!id && !!incident.data,
    retry: false,
  })
  const report = reportQuery.data
  useLayoutEffect(() => {
    const currentParams = new URLSearchParams(window.location.search)
    if (
      report &&
      !analysisId &&
      window.location.pathname === pathname &&
      currentParams.get('revision') === params.get('revision') &&
      currentParams.get('analysis') === analysisId
    ) {
      queryClient.setQueryData(
        ['incident-analysis', id, revision, report.id, user?.id ?? 'public'],
        report,
      )
      setParams({ revision: String(revision), analysis: report.id }, { replace: true })
    }
  }, [report, analysisId, id, revision, params, pathname, user?.id, queryClient, setParams])
  const evidence = useQuery({
    queryKey: ['incident-evidence', report?.id, evidenceId],
    queryFn: () => incidentApi.evidence(report!.id, evidenceId!),
    enabled: !!report && !!evidenceId,
  })
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['incident-analysis', id, revision] })
  const changeRevision = (value: number) => {
    setEvidenceId(null)
    setParams({ revision: String(value) })
  }

  if (!validRevision)
    return (
      <div role="alert" className="space-y-6">
        <PageHeader title="Invalid evidence revision">
          <p className="mt-2 max-w-2xl text-base text-muted-foreground">
            Choose a positive whole-number revision, or open the latest investigation.
          </p>
        </PageHeader>
        <Button asChild>
          <Link to={`/incidents/${encodeURIComponent(id)}`}>Open latest investigation</Link>
        </Button>
      </div>
    )

  return (
    <div className="investigation-workbench space-y-10">
      <Link
        to="/"
        className="inline-flex min-h-8 items-center gap-2 rounded-sm text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" size={14} />
        Incident library
      </Link>
      {incident.isPending ? (
        <div aria-busy="true" aria-label="Loading incident">
          <Skeleton className="h-12 w-2/3" />
          <Skeleton className="mt-4 h-32" />
        </div>
      ) : incident.isError ? (
        <div
          role="alert"
          className="rounded-sm border border-danger-border bg-danger p-5 text-sm text-danger-foreground"
        >
          Could not load incident: {incident.error.message}{' '}
          <Button variant="outline" size="sm" onClick={() => incident.refetch()}>
            Retry
          </Button>
        </div>
      ) : (
        <>
          <PageHeader
            title={incident.data.title}
            actions={
              <div>
                <FieldLabel htmlFor="revision">Evidence revision</FieldLabel>
                <NativeSelect
                  id="revision"
                  value={revision}
                  onChange={(event) => changeRevision(Number(event.target.value))}
                >
                  {(report?.execution_kind === 'saved_deterministic'
                    ? [revision]
                    : incident.data.available_revisions
                  ).map((value) => (
                    <option key={value} value={value}>
                      Revision {value}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            }
          >
            <p className="mt-2 text-base text-muted-foreground">
              {incident.data.scope.line_id} · {formatInstant(incident.data.window.start)} to{' '}
              {formatInstant(incident.data.window.end)}
            </p>
            <div className="mt-4 flex flex-col gap-1 text-sm text-muted-foreground sm:flex-row sm:flex-wrap sm:gap-0 sm:divide-x sm:divide-border sm:[&>span]:px-4 sm:[&>span:first-child]:pl-0">
              <span>Evidence available by: {formatInstant(incident.data.cutoff)}</span>
              <span>
                Report:{' '}
                {reportQuery.isPending
                  ? 'Building analysis'
                  : reportQuery.isError
                    ? 'Analysis unavailable'
                    : report?.execution_kind === 'saved_deterministic'
                      ? 'Saved deterministic result'
                      : 'Live deterministic analysis'}
              </span>
              <span>
                {incident.data.workspace_id && incident.data.workspace_id !== 'public-demo'
                  ? 'Private workspace records'
                  : 'Factory data: synthetic'}
              </span>
            </div>
          </PageHeader>
          {reportQuery.isPending ? (
            <div aria-busy="true" aria-label="Building analysis" className="space-y-3">
              <Skeleton className="h-28" />
              <Skeleton className="h-48" />
              <Skeleton className="h-48" />
            </div>
          ) : reportQuery.isError ? (
            <div role="alert" className="rounded-sm border border-danger-border bg-danger p-5">
              <h2 className="text-sm font-semibold text-danger-foreground">Analysis unavailable</h2>
              <p className="mt-1 text-sm text-danger-foreground">{reportQuery.error.message}</p>
              <Button
                className="mt-3"
                size="sm"
                variant="outline"
                onClick={() => reportQuery.refetch()}
              >
                Retry analysis
              </Button>
            </div>
          ) : (
            report && (
              <>
                <p className="hidden text-xs print:block">
                  FloorReplay · Evidence revision {report.revision} · Report {report.id} · Evidence
                  available by {formatInstant(report.cutoff)} ·{' '}
                  {incident.data.workspace_id && incident.data.workspace_id !== 'public-demo'
                    ? 'Private workspace records'
                    : 'Synthetic data'}
                </p>
                <RevisionComparison
                  key={`${id}:${revision}`}
                  incident={incident.data}
                  report={report}
                />
                <SupervisorReport
                  key={`${report.id}:${user?.id ?? 'anonymous'}`}
                  report={report}
                  incident={incident.data}
                  currentRevision={summary?.revision ?? revision}
                />
                <aside
                  className="rounded-sm border border-border bg-card p-4 print:hidden"
                  aria-label="Investigation guide"
                >
                  <h2 className="text-base font-bold">Follow the investigation</h2>
                  <ol className="mt-2 grid gap-3 text-sm sm:grid-cols-3">
                    <li>
                      <a
                        className="font-semibold text-primary underline"
                        href="#observed-situation"
                      >
                        1. Measure the difference
                      </a>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Compare planned and recorded output, then check missing intervals.
                      </p>
                    </li>
                    <li>
                      <a
                        className="font-semibold text-primary underline"
                        href="#explanations-and-open-questions"
                      >
                        2. Check the explanation
                      </a>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Read supporting and contradicting records before choosing a cause.
                      </p>
                    </li>
                    <li>
                      <a className="font-semibold text-primary underline" href="#recovery-options">
                        3. Choose the next check
                      </a>
                      <p className="mt-1 text-sm text-muted-foreground">
                        Read the prerequisites and responsible role. Share the supervisor report or
                        assign a check with reviewer access.
                      </p>
                    </li>
                  </ol>
                  <p className="mt-3 text-sm text-muted-foreground">
                    “Knowledge cutoff” means the time by which evidence had reached the system. A
                    late-arriving record may describe an earlier event, but appears only in a later
                    evidence revision.
                  </p>
                </aside>
                <p className="text-sm text-muted-foreground">
                  Calculation coverage: {report.metrics.status.toLowerCase()}. Proposal approval,
                  check completion, and incident resolution are separate decisions.
                </p>
                <SectionRail titles={RAIL_TITLES} />
                <Section
                  title="Observed situation"
                  detail="Calculated from comparable complete 15-minute buckets; missing data is not counted as zero."
                >
                  <dl className="grid divide-y divide-border overflow-hidden rounded-sm border-2 border-foreground bg-card sm:grid-cols-3 sm:divide-x sm:divide-y-0">
                    <BoardStat
                      label="Baseline planned"
                      value={report.metrics.planned ?? '—'}
                      note={report.metrics.unit.replaceAll('_', ' ')}
                    />
                    <BoardStat
                      label="Recorded good output"
                      value={report.metrics.observed ?? '—'}
                      note={report.metrics.unit.replaceAll('_', ' ')}
                    />
                    <BoardStat
                      tone="limit"
                      label="Observed shortfall"
                      value={report.metrics.shortfall ?? '—'}
                      note={report.metrics.status}
                    />
                  </dl>
                  {report.metrics.planned != null &&
                    report.metrics.observed != null &&
                    report.metrics.planned > 0 && (
                      <div className="rounded-sm border border-border bg-card p-4">
                        <div className="mb-2 flex justify-between text-xs text-muted-foreground">
                          <span>Recorded output against baseline</span>
                          <span>
                            {Math.round((report.metrics.observed / report.metrics.planned) * 100)}%
                          </span>
                        </div>
                        <div className="h-3 overflow-hidden rounded-sm bg-secondary">
                          <div
                            className="h-full bg-primary"
                            style={{
                              width: `${Math.min(100, Math.max(0, (report.metrics.observed / report.metrics.planned) * 100))}%`,
                            }}
                          />
                        </div>
                      </div>
                    )}
                  <BucketStrip
                    incident={incident.data}
                    metric={report.metrics}
                    onOpen={setEvidenceId}
                  />
                  <p className="text-sm text-muted-foreground">
                    {report.metrics.matched_buckets.length} matched buckets ·{' '}
                    {report.metrics.missing_buckets.length} missing ·{' '}
                    {report.metrics.unfinished_buckets.length} unfinished
                    {report.metrics.blocked_minutes != null
                      ? ` · ${report.metrics.blocked_minutes} established line-block minutes`
                      : ''}
                  </p>
                  <div className="rounded-sm border border-border bg-card">
                    <div className="border-b border-border px-4 py-3">
                      <h3 className="text-sm font-medium">Calculation inputs</h3>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        {report.metrics.formula ?? 'Formula unavailable in this report.'}
                      </p>
                    </div>
                    {report.metrics.inputs?.length ? (
                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[560px] text-left text-sm">
                          <caption className="sr-only">
                            Comparable completed 15-minute production buckets used in the reported
                            calculation
                          </caption>
                          <thead className="bg-secondary text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                            <tr>
                              <th scope="col" className="px-4 py-2">
                                Completed interval
                              </th>
                              <th scope="col" className="px-4 py-2">
                                Baseline plan
                              </th>
                              <th scope="col" className="px-4 py-2">
                                Recorded good output
                              </th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-border">
                            {report.metrics.inputs.map((input) => (
                              <tr key={`${input.start}-${input.end}`}>
                                <th
                                  scope="row"
                                  className="whitespace-nowrap px-4 py-2 text-xs font-normal text-foreground"
                                >
                                  {formatInstant(input.start)} – {formatInstant(input.end)}
                                </th>
                                <td className="px-4 py-2">
                                  <span className="mr-2 tabular-nums">{input.plan.quantity}</span>
                                  <EvidenceLink id={input.plan.id} onOpen={setEvidenceId} />
                                </td>
                                <td className="px-4 py-2">
                                  <span className="mr-2 tabular-nums">{input.output.quantity}</span>
                                  <EvidenceLink id={input.output.id} onOpen={setEvidenceId} />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="px-4 py-3 text-xs text-muted-foreground">
                        {report.metrics.inputs
                          ? 'No comparable completed buckets are available.'
                          : 'Input breakdown is unavailable in this report.'}
                      </p>
                    )}
                  </div>
                  {report.capabilities?.production?.reasons.map((reason) => (
                    <p key={reason} className="text-xs text-limit-foreground">
                      {reason}
                    </p>
                  ))}
                  {report.metrics.target_pressure?.remaining_target != null && (
                    <div className="rounded-sm border border-border bg-card p-4 text-sm">
                      <h3 className="font-medium">Remaining shift target</h3>
                      {report.metrics.target_pressure.as_of && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          As of recorded output:{' '}
                          {formatInstant(report.metrics.target_pressure.as_of)}
                        </p>
                      )}
                      {report.metrics.target_pressure.planned_non_working ? (
                        <>
                          <p className="mt-1 text-foreground">
                            {report.metrics.target_pressure.remaining_target}{' '}
                            {report.metrics.unit.replaceAll('_', ' ')} across{' '}
                            {report.metrics.target_pressure.remaining_working_minutes} working
                            minutes: {report.metrics.target_pressure.remaining_elapsed_minutes}{' '}
                            elapsed, less{' '}
                            {report.metrics.target_pressure.planned_non_working.remaining_minutes}{' '}
                            declared non-working.
                          </p>
                          {report.metrics.target_pressure.planned_non_working.remaining_segments
                            .length > 0 && (
                            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                              {report.metrics.target_pressure.planned_non_working.remaining_segments.map(
                                (segment) => (
                                  <li key={segment.start}>
                                    {formatInstant(segment.start)} to {formatInstant(segment.end)}{' '}
                                    ·{' '}
                                    {segment.evidence.map((id) => (
                                      <EvidenceLink key={id} id={id} onOpen={setEvidenceId} />
                                    ))}
                                  </li>
                                ),
                              )}
                            </ul>
                          )}
                        </>
                      ) : (
                        <p className="mt-1 text-foreground">
                          {report.metrics.target_pressure.remaining_target}{' '}
                          {report.metrics.unit.replaceAll('_', ' ')} across{' '}
                          {report.metrics.target_pressure.remaining_elapsed_minutes ??
                            report.metrics.target_pressure.remaining_working_minutes}{' '}
                          elapsed minutes under the report assumptions.
                        </p>
                      )}
                      <p className="mt-1 text-xs text-muted-foreground">
                        Required average:{' '}
                        {report.metrics.target_pressure.required_units_per_hour ?? 'Unavailable'}{' '}
                        units/hour · Baseline:{' '}
                        {report.metrics.target_pressure.baseline_units_per_hour ?? 'Unavailable'}{' '}
                        units/hour
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {report.metrics.target_pressure.assumptions.join(' ')}
                      </p>
                    </div>
                  )}
                </Section>
                <Section
                  title="Evidence timeline"
                  detail="Events are ordered by occurrence. Availability at the cutoff determines which records are included."
                >
                  {report.timeline.length ? (
                    <div className="overflow-x-auto rounded-sm border border-border bg-card">
                      <table className="w-full min-w-[650px] text-left text-sm">
                        <thead className="border-b bg-secondary text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          <tr>
                            <th scope="col" className="px-4 py-2">
                              When
                            </th>
                            <th scope="col" className="px-4 py-2">
                              Lane
                            </th>
                            <th scope="col" className="px-4 py-2">
                              Observation
                            </th>
                            <th scope="col" className="px-4 py-2">
                              Source
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                          {report.timeline.map((event) => (
                            <tr key={event.id}>
                              <td className="whitespace-nowrap px-4 py-3 text-xs tabular-nums text-muted-foreground">
                                {formatInstant(event.occurred_at ?? event.start ?? '')}
                                {event.end ? ` – ${formatInstant(event.end)}` : ''}
                              </td>
                              <td className="px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                {event.lane ?? event.type.replaceAll('_', ' ')}
                              </td>
                              <td className="px-4 py-3">
                                {event.summary}
                                {event.assertion && (
                                  <StatusTag tone="limit" className="ml-2">
                                    Source assertion
                                  </StatusTag>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                <EvidenceLink id={event.id} onOpen={setEvidenceId} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="rounded-sm border border-dashed p-5 text-sm text-muted-foreground">
                      No timeline events are available at this cutoff.
                    </p>
                  )}
                </Section>
                <Section
                  title="Explanations and open questions"
                  detail="A sequence of events alone does not establish causation."
                >
                  {report.hypotheses.length ? (
                    <div className="grid gap-3 lg:grid-cols-2">
                      {report.hypotheses.map((item, index) => (
                        <HypothesisCard
                          key={`${item.category}-${index}`}
                          item={item}
                          onEvidence={setEvidenceId}
                        />
                      ))}
                    </div>
                  ) : (
                    <p className="rounded-sm border border-dashed p-5 text-sm text-muted-foreground">
                      Current evidence does not support a specific contributor.
                    </p>
                  )}
                </Section>
                <HybridPanel
                  key={`hybrid:${report.id}:${user?.id ?? 'public'}`}
                  report={report}
                  enabled={
                    capabilities.data?.ai?.index_ready === true &&
                    capabilities.data?.reviews_enabled === true
                  }
                />
                <Section
                  title="Historical precedents"
                  detail="Live lexical search. Similar cases can guide checks; differences limit what can be inferred."
                >
                  {report.precedents?.length ? (
                    <div className="grid gap-3 lg:grid-cols-2">
                      {report.precedents.map((item, index) => (
                        <article
                          key={item.id ?? item.incident_id ?? index}
                          className="rounded-sm border bg-card p-4"
                        >
                          <h3 className="text-sm font-semibold">
                            {item.title ?? item.incident_id ?? 'Historical incident'}
                          </h3>
                          {item.match_reason || item.match_reasons?.length ? (
                            <p className="mt-2 text-sm text-foreground">
                              <strong>Similar:</strong>{' '}
                              {item.match_reason ?? item.match_reasons?.join('; ')}
                            </p>
                          ) : null}
                          {item.differences?.length ? (
                            <p className="mt-2 text-sm text-foreground">
                              <strong>Different:</strong> {item.differences.join('; ')}
                            </p>
                          ) : null}
                          <div className="mt-2">
                            <PrecedentConditions item={item} />
                          </div>
                          {(item.incident_id || item.id) && (
                            <Link
                              className="mt-3 inline-block text-sm font-semibold text-primary underline"
                              to={`/incidents/${encodeURIComponent(item.incident_id ?? item.id!)}`}
                            >
                              Open precedent
                            </Link>
                          )}
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="rounded-sm border border-dashed p-5 text-sm text-muted-foreground">
                      No useful precedent was found among eligible historical records. Verify
                      current conditions before borrowing an action.
                    </p>
                  )}
                </Section>
                <Section
                  title="Recovery options"
                  detail="Proposals are versioned requests for human review."
                >
                  {report.proposals.length ? (
                    <div className="grid gap-3 lg:grid-cols-2">
                      {report.proposals.map((item) => (
                        <ProposalCard
                          key={`${report.id}-${item.id}-${item.state}`}
                          item={item}
                          report={report}
                          currentRevision={summary?.revision ?? revision}
                          canReview={
                            capabilities.data?.reviews_enabled === true &&
                            report.execution_kind !== 'saved_deterministic'
                          }
                          onEvidence={setEvidenceId}
                          onChanged={refresh}
                        />
                      ))}
                    </div>
                  ) : (
                    <p className="rounded-sm border border-dashed p-5 text-sm text-muted-foreground">
                      No action proposal is supported by this evidence.
                    </p>
                  )}
                </Section>
                <IncidentWorkflow
                  key={`${id}:${user?.id ?? 'anonymous'}`}
                  report={report}
                  currentRevision={summary?.revision ?? revision}
                  onRevisionPublished={changeRevision}
                />
                <Section title="Shift update" detail="Evidence-linked report summary">
                  <blockquote className="rounded-sm border border-border bg-card p-5 text-sm leading-7 text-foreground">
                    {report.summary}
                  </blockquote>
                  <ExportReport
                    report={report}
                    enabled={capabilities.data?.reviews_enabled === true}
                  />
                </Section>
                {report.incident_id === savedAi.incident_id &&
                  report.revision === savedAi.revision && (
                    <SavedAiPanel onEvidence={setEvidenceId} />
                  )}
                <div className="print:hidden">
                  <OpenAiPanel
                    key={`${report.id}:${user?.id ?? 'anonymous'}`}
                    report={report}
                    enabled={
                      capabilities.data?.ai?.generation_available === true &&
                      report.execution_kind !== 'saved_deterministic'
                    }
                    reasons={
                      capabilities.data?.ai?.reason
                        ? [capabilities.data.ai.reason.replaceAll('_', ' ').toLowerCase()]
                        : ['OpenAI drafts are available to authenticated reviewers.']
                    }
                    onEvidence={setEvidenceId}
                  />
                </div>
              </>
            )
          )}
        </>
      )}
      <Sheet
        open={evidenceId !== null}
        onOpenChange={(open) => {
          if (!open) setEvidenceId(null)
        }}
      >
        <SheetContent className="overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <FileText aria-hidden="true" size={18} />
              Source evidence
            </SheetTitle>
            <SheetDescription className="break-all font-mono text-xs">
              {evidenceId}
            </SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">
            {evidence.isPending ? (
              <Skeleton className="h-32" />
            ) : evidence.isError ? (
              <p role="alert" className="text-sm text-danger-foreground">
                {evidence.error.message}
              </p>
            ) : evidence.data ? (
              <dl className="space-y-3 text-sm">
                {Object.entries(evidence.data).map(([key, value]) => (
                  <div key={key} className="border-b border-border pb-2">
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {key.replace(/_/g, ' ')}
                    </dt>
                    <dd className="mt-1 whitespace-pre-wrap break-words font-mono text-xs leading-5 text-foreground">
                      {typeof value === 'object'
                        ? JSON.stringify(value, null, 2)
                        : String(value ?? '—')}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
