/**
 * Replay workbench: inspect pinned evidence, execute a configuration, and
 * trace the result. Reading order: outcome first, then event and interval,
 * context issues, proposal or abstention, constraint results, manifest.
 * Every issue and failed constraint links to the source row that caused it.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import {
  api,
  ApiError,
  CONSTRAINT_NAMES,
  type EvidenceRef,
  type ReplayAttempt,
  type ReviewCheckResult,
} from '@/lib/api'
import { formatInstant, formatInterval, OUTCOME_META, shortDigest } from '@/lib/status'
import { ExpectationBadge, LifecycleBadge, Mono, OutcomeBadge, VerdictBadge } from '@/components/status'
import { EvidenceDrawer } from '@/components/EvidenceDrawer'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

function EvidenceChip({
  evidence,
  onOpen,
}: {
  evidence: EvidenceRef
  onOpen: (evidence: EvidenceRef) => void
}) {
  const label = evidence.source_ref || evidence.field || evidence.snapshot_id
  return (
    <button
      type="button"
      onClick={() => onOpen(evidence)}
      className="inline-flex items-center rounded border border-zinc-300 bg-white px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 transition-colors hover:border-zinc-400 hover:text-zinc-900 focus-visible:outline-2"
      title={`Open ${evidence.snapshot_id}`}
    >
      {evidence.snapshot_id === 'event' ? 'event' : evidence.snapshot_id.replace('SNAP-', '')}
      {label !== evidence.snapshot_id ? `:${label}` : ''}
    </button>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">{title}</h2>
      {children}
    </section>
  )
}

function ReviewOutcome({ review }: { review: ReviewCheckResult }) {
  const tone =
    review.outcome === 'STILL_SUPPORTED'
      ? 'border-emerald-600/30 bg-emerald-600/5'
      : review.outcome === 'BLOCKED_CONTEXT'
        ? 'border-red-600/30 bg-red-600/5'
        : 'border-amber-600/30 bg-amber-500/10'
  return (
    <div className={cn('rounded-md border p-2.5', tone)}>
      <p className="text-sm font-medium">{review.outcome.replace(/_/g, ' ').toLowerCase()}</p>
      <p className="mt-0.5 text-xs text-zinc-500">
        Checked against {review.target_scenario_id}@{review.target_scenario_revision}; the original
        replay is untouched.
      </p>
      {review.reason_codes.length > 0 ? (
        <p className="mt-1 text-xs">
          reasons: <Mono>{review.reason_codes.join(', ')}</Mono>
        </p>
      ) : null}
      {review.changed_paths.length > 0 ? (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-zinc-500">
            {review.changed_paths.length} changed path(s)
          </summary>
          <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto pl-4">
            {review.changed_paths.map((path) => (
              <li key={path} className="list-disc text-xs">
                <Mono>{path}</Mono>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {review.issues.length > 0 ? (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-red-700">
          {review.issues.slice(0, 6).map((issue, index) => (
            <li key={index}>
              <Mono>{issue.code}</Mono> {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function WorkbenchPage() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [sessionAttempts, setSessionAttempts] = useState<ReplayAttempt[]>([])
  const [activeAttemptId, setActiveAttemptId] = useState<string | null>(null)
  const [loadedFromSaved, setLoadedFromSaved] = useState(false)
  const [drawerEvidence, setDrawerEvidence] = useState<EvidenceRef | null>(null)

  const scenariosQuery = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios })
  const configsQuery = useQuery({ queryKey: ['configurations'], queryFn: api.configurations })

  const scenarios = scenariosQuery.data?.items ?? []
  const configurations = configsQuery.data?.items ?? []

  const scenarioParam = searchParams.get('scenario')
  const revisionParam = Number(searchParams.get('revision') ?? 0)
  const configParam = searchParams.get('config')

  const selected =
    scenarios.find((s) => s.scenario_id === scenarioParam && s.revision === revisionParam) ??
    scenarios[0]
  const selectedConfig =
    configurations.find((c) => c.id === configParam) ??
    configurations.find((c) => c.id === 'CFG-IMPROVED-V1') ??
    configurations[0]

  const detailQuery = useQuery({
    queryKey: ['scenario', selected?.scenario_id, selected?.revision],
    queryFn: () => api.scenario(selected!.scenario_id, selected!.revision),
    enabled: selected != null,
  })

  const activeAttempt = useMemo(
    () => sessionAttempts.find((a) => a.id === activeAttemptId) ?? sessionAttempts[0] ?? null,
    [sessionAttempts, activeAttemptId],
  )

  const runMutation = useMutation({
    mutationFn: (input: { scenarioId: string; revision: number; configId: string }) =>
      api.runReplay({
        scenario_id: input.scenarioId,
        scenario_revision: input.revision,
        configuration_id: input.configId,
        idempotency_key: `ui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      }),
    onSuccess: (attempt) => {
      setSessionAttempts((prev) => [attempt, ...prev])
      setActiveAttemptId(attempt.id)
      setLoadedFromSaved(false)
      setReviewResult(null)
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
    },
  })

  const savedMutation = useMutation({
    mutationFn: (input: { scenarioId: string; revision: number; configId: string }) =>
      api.latestReplay(input.scenarioId, input.revision, input.configId),
    onSuccess: (attempt) => {
      setSessionAttempts((prev) => [attempt, ...prev.filter((a) => a.id !== attempt.id)])
      setActiveAttemptId(attempt.id)
      setLoadedFromSaved(true)
    },
  })

  const [reviewTargetKey, setReviewTargetKey] = useState('')
  const [reviewResult, setReviewResult] = useState<ReviewCheckResult | null>(null)
  const reviewMutation = useMutation({
    mutationFn: (input: { scenarioId: string; revision: number }) =>
      api.reviewCheck({
        original_replay_id: activeAttemptId ?? '',
        target_scenario_id: input.scenarioId,
        target_scenario_revision: input.revision,
      }),
    onSuccess: setReviewResult,
  })

  function select(scenarioId: string, revision: number) {
    setSessionAttempts([])
    setActiveAttemptId(null)
    setLoadedFromSaved(false)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('scenario', scenarioId)
      next.set('revision', String(revision))
      if (configParam) next.set('config', configParam)
      return next
    })
  }

  function selectConfig(configId: string) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (selected) {
        next.set('scenario', selected.scenario_id)
        next.set('revision', String(selected.revision))
      }
      next.set('config', configId)
      return next
    })
  }

  if (scenariosQuery.isPending || configsQuery.isPending) {
    return (
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Skeleton className="h-96" />
        <Skeleton className="h-96" />
      </div>
    )
  }

  if (scenariosQuery.isError || configsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>The workbench could not load its inputs</AlertTitle>
        <AlertDescription>
          {(scenariosQuery.error ?? configsQuery.error)?.message}
        </AlertDescription>
      </Alert>
    )
  }

  const result = activeAttempt?.result
  const hasReplayResult = result != null && 'outcome' in result && result.outcome != null

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        {/* ------------------------- Inputs column ------------------------- */}
        <div className="space-y-4">
          <div className="rounded-lg border bg-white p-3">
            <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
              Scenario revision
            </h2>
            <div className="mt-2 space-y-1.5">
              {scenarios.map((scenario) => {
                const active =
                  selected?.scenario_id === scenario.scenario_id &&
                  selected?.revision === scenario.revision
                return (
                  <button
                    key={`${scenario.scenario_id}@${scenario.revision}`}
                    type="button"
                    onClick={() => select(scenario.scenario_id, scenario.revision)}
                    aria-pressed={active}
                    className={cn(
                      'w-full rounded-md border px-2.5 py-2 text-left text-sm transition-colors focus-visible:outline-2',
                      active
                        ? 'border-zinc-900 bg-zinc-900 text-white'
                        : 'border-zinc-200 bg-white hover:border-zinc-400',
                    )}
                  >
                    <span className="block leading-snug font-medium">{scenario.title}</span>
                    <Mono className={active ? 'text-zinc-300' : 'text-zinc-400'}>
                      {scenario.scenario_id}@{scenario.revision}
                    </Mono>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="rounded-lg border bg-white p-3">
            <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
              Execution configuration
            </h2>
            <div className="mt-2 space-y-1.5">
              {configurations.map((config) => {
                const active = selectedConfig?.id === config.id
                return (
                  <button
                    key={config.id}
                    type="button"
                    onClick={() => selectConfig(config.id)}
                    aria-pressed={active}
                    className={cn(
                      'w-full rounded-md border px-2.5 py-2 text-left text-sm transition-colors focus-visible:outline-2',
                      active
                        ? 'border-zinc-900 bg-zinc-900 text-white'
                        : 'border-zinc-200 bg-white hover:border-zinc-400',
                    )}
                  >
                    <span className="font-medium">{config.name}</span>
                    {config.known_limitation ? (
                      <span
                        className={cn(
                          'mt-0.5 block text-xs leading-snug',
                          active ? 'text-amber-200' : 'text-amber-700',
                        )}
                      >
                        {config.known_limitation}
                      </span>
                    ) : null}
                  </button>
                )
              })}
            </div>
          </div>

          {detailQuery.data ? (
            <div className="rounded-lg border bg-white p-3">
              <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
                Pinned evidence
              </h2>
              <dl className="mt-2 space-y-1.5 text-xs">
                <div className="flex justify-between gap-2">
                  <dt className="text-zinc-500">Event</dt>
                  <dd className="text-right">
                    <Mono>{detailQuery.data.event.subject_operator_id}</Mono> unavailable ·{' '}
                    {formatInstant(detailQuery.data.event.observed_at)}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-zinc-500">Decision at</dt>
                  <dd>{formatInstant(detailQuery.data.decision_at)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-zinc-500">Coverage</dt>
                  <dd className="text-right">
                    <Mono>{detailQuery.data.target.slot_id}</Mono>
                    <br />
                    {formatInterval(detailQuery.data.target.starts_at, detailQuery.data.target.ends_at)}
                  </dd>
                </div>
              </dl>
              <Separator className="my-2" />
              <ul className="space-y-1">
                {detailQuery.data.pinned_snapshot_ids.map((snapshotId) => (
                  <li key={snapshotId}>
                    <EvidenceChip
                      evidence={{ snapshot_id: snapshotId }}
                      onOpen={setDrawerEvidence}
                    />
                  </li>
                ))}
              </ul>
            </div>
          ) : detailQuery.isPending ? (
            <Skeleton className="h-44" />
          ) : null}

          <Button
            className="w-full"
            disabled={!selected || !selectedConfig || runMutation.isPending}
            onClick={() =>
              selected &&
              selectedConfig &&
              runMutation.mutate({
                scenarioId: selected.scenario_id,
                revision: selected.revision,
                configId: selectedConfig.id,
              })
            }
          >
            {runMutation.isPending ? 'Executing replay…' : 'Run replay'}
          </Button>
          <Button
            variant="ghost"
            className="w-full text-xs text-zinc-500"
            disabled={
              !selected || !selectedConfig || savedMutation.isPending || runMutation.isPending
            }
            onClick={() =>
              selected &&
              selectedConfig &&
              savedMutation.mutate({
                scenarioId: selected.scenario_id,
                revision: selected.revision,
                configId: selectedConfig.id,
              })
            }
          >
            {savedMutation.isPending
              ? 'Loading saved report…'
              : 'Open latest saved report for this selection'}
          </Button>
          {savedMutation.isError ? (
            <p className="text-xs text-zinc-400">
              No saved report exists for this selection yet.
            </p>
          ) : null}
          {runMutation.isError ? (
            runMutation.error instanceof ApiError && runMutation.error.code === 'RATE_LIMITED' ? (
              <Alert variant="destructive">
                <AlertTitle>Execution limit reached</AlertTitle>
                <AlertDescription>
                  {runMutation.error.message} Use “Open latest saved report” above, or try again
                  when the limit window resets.
                </AlertDescription>
              </Alert>
            ) : (
              <Alert variant="destructive">
                <AlertTitle>Execution failed</AlertTitle>
                <AlertDescription>{runMutation.error.message}</AlertDescription>
              </Alert>
            )
          ) : null}
        </div>

        {/* ------------------------- Result column ------------------------- */}
        <div className="space-y-5">
          {!activeAttempt ? (
            <div className="rounded-lg border border-dashed bg-white p-12 text-center">
              <p className="text-sm font-medium">No replay executed for this selection yet</p>
              <p className="mx-auto mt-1 max-w-sm text-sm text-zinc-500">
                Press <span className="font-medium">Run replay</span> to execute the pinned
                scenario against the selected configuration. The result is persisted before it is
                shown.
              </p>
            </div>
          ) : (
            <>
              <div className="rounded-lg border bg-white p-4">
                <div className="flex flex-wrap items-center gap-2">
                  {activeAttempt.domain_outcome ? (
                    <OutcomeBadge outcome={activeAttempt.domain_outcome} />
                  ) : (
                    <Badge variant="outline" className="text-xs">
                      No domain outcome
                    </Badge>
                  )}
                  <LifecycleBadge lifecycle={activeAttempt.lifecycle} />
                  <ExpectationBadge verdict={activeAttempt.expectation_verdict} />
                  <span className="ml-auto text-xs text-zinc-400">
                    {loadedFromSaved ? 'Saved report' : 'Persisted attempt'} ·{' '}
                    {formatInstant(activeAttempt.created_at)}
                  </span>
                </div>
                {loadedFromSaved ? (
                  <p className="mt-2 rounded-md border border-amber-600/25 bg-amber-500/10 p-2 text-xs text-amber-800">
                    Loaded from history for this exact selection — not a fresh execution. Press{' '}
                    <span className="font-medium">Run replay</span> to execute now.
                  </p>
                ) : null}
                {activeAttempt.domain_outcome ? (
                  <p className="mt-2 text-sm text-zinc-600">
                    {OUTCOME_META[activeAttempt.domain_outcome].hint}
                  </p>
                ) : null}
                {activeAttempt.expectation_failures?.length ? (
                  <div className="mt-2 rounded-md border border-red-600/25 bg-red-600/5 p-2">
                    <p className="text-xs font-medium text-red-800">Expectation failures</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-red-700">
                      {activeAttempt.expectation_failures.map((failure) => (
                        <li key={failure}>{failure}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>

              {hasReplayResult && result && 'outcome' in result ? (
                <>
                  <Section title="Event and proposed interval">
                    <div className="rounded-lg border bg-white p-3 text-sm">
                      {detailQuery.data ? (
                        <p>
                          <Mono>{detailQuery.data.event.subject_operator_id}</Mono> reported
                          unavailable at {formatInstant(detailQuery.data.event.observed_at)} (
                          <Mono>{detailQuery.data.event.source_ref}</Mono>). Coverage target:{' '}
                          <Mono>{detailQuery.data.target.slot_id}</Mono> on{' '}
                          <Mono>{detailQuery.data.target.machine_id}</Mono>,{' '}
                          {formatInterval(
                            detailQuery.data.target.starts_at,
                            detailQuery.data.target.ends_at,
                          )}
                          .
                        </p>
                      ) : null}
                    </div>
                  </Section>

                  {result.gate_issues.length > 0 ? (
                    <Section title={`Context issues (${result.gate_issues.length})`}>
                      <ul className="space-y-1.5">
                        {result.gate_issues.map((issue, index) => (
                          <li
                            key={`${issue.code}-${issue.subject}-${index}`}
                            className="rounded-lg border bg-white p-2.5"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <Mono className="font-semibold text-zinc-700">{issue.code}</Mono>
                              <Badge variant="secondary" className="text-[10px]">
                                {issue.severity}
                              </Badge>
                              {issue.subject ? (
                                <Mono className="text-zinc-500">{issue.subject}</Mono>
                              ) : null}
                              <span className="ml-auto flex gap-1">
                                {issue.evidence.map((evidence, evidenceIndex) => (
                                  <EvidenceChip
                                    key={evidenceIndex}
                                    evidence={evidence}
                                    onOpen={setDrawerEvidence}
                                  />
                                ))}
                              </span>
                            </div>
                            <p className="mt-1 text-sm text-zinc-700">{issue.message}</p>
                          </li>
                        ))}
                      </ul>
                    </Section>
                  ) : null}

                  <Section title="Recommendation">
                    {result.proposal ? (
                      <div className="space-y-2 rounded-lg border bg-white p-3">
                        <p className="text-sm">
                          Proposes <Mono className="font-semibold">{result.proposal.operator_id}</Mono>{' '}
                          to cover <Mono>{result.proposal.target_slot_id}</Mono> on{' '}
                          <Mono>{result.proposal.machine_id}</Mono>,{' '}
                          {formatInterval(result.proposal.starts_at, result.proposal.ends_at)}.
                        </p>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
                          {result.proposal.ranking_factors.map(([factor, value]) => (
                            <span key={factor}>
                              {factor.replace(/_/g, ' ')}: <Mono>{value}</Mono>
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : result.abstention ? (
                      <div className="rounded-lg border bg-white p-3">
                        <p className="text-sm">
                          Abstained:{' '}
                          <Mono className="font-semibold">{result.abstention.reason_code}</Mono>
                        </p>
                        {result.abstention.candidate_exclusions.length > 0 ? (
                          <p className="mt-1 text-xs text-zinc-500">
                            {result.abstention.candidate_exclusions.length} candidate(s) excluded;
                            inspect each in the persisted report.
                          </p>
                        ) : null}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed bg-white p-3">
                        <p className="text-sm text-zinc-500">
                          No recommendation was produced: the context gate stopped this replay
                          before the policy ran.
                        </p>
                      </div>
                    )}
                  </Section>

                  {result.constraints.length > 0 ? (
                    <Section title="Independent constraint checks">
                      <div className="overflow-x-auto rounded-lg border bg-white">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-16">Rule</TableHead>
                              <TableHead className="w-32">Verdict</TableHead>
                              <TableHead>Check</TableHead>
                              <TableHead className="w-[30%]">Finding</TableHead>
                              <TableHead className="w-40">Evidence</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {result.constraints.map((constraint) => (
                              <TableRow key={constraint.code}>
                                <TableCell>
                                  <Mono className="font-semibold">{constraint.code}</Mono>
                                </TableCell>
                                <TableCell>
                                  <VerdictBadge verdict={constraint.verdict} />
                                </TableCell>
                                <TableCell className="text-sm">
                                  {CONSTRAINT_NAMES[constraint.code] ?? constraint.code}
                                </TableCell>
                                <TableCell
                                  className={cn(
                                    'whitespace-normal break-words text-sm',
                                    constraint.verdict === 'FAIL' && 'text-red-700',
                                    constraint.verdict === 'NOT_EVALUATED' && 'text-zinc-400',
                                  )}
                                >
                                  {constraint.message}
                                </TableCell>
                                <TableCell>
                                  <span className="flex flex-wrap gap-1">
                                    {constraint.evidence.map((evidence, index) => (
                                      <EvidenceChip
                                        key={index}
                                        evidence={evidence}
                                        onOpen={setDrawerEvidence}
                                      />
                                    ))}
                                  </span>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </Section>
                  ) : null}

                  <Section title="Evidence and execution manifest">
                    <div className="space-y-1 rounded-lg border bg-white p-3 text-xs">
                      <p>
                        Context digest: <Mono>{activeAttempt.context_digest}</Mono>
                      </p>
                      <p>
                        Manifest digest: <Mono>{activeAttempt.manifest_digest}</Mono>
                      </p>
                      {result.ranked_candidates.length > 0 ? (
                        <p>
                          Policy ranking:{' '}
                          {result.ranked_candidates.map((operator) => (
                            <Mono key={operator} className="mr-2">
                              {operator}
                            </Mono>
                          ))}
                        </p>
                      ) : null}
                      <a
                        href={`/api/v1/replays/${activeAttempt.id}/export`}
                        className="inline-block underline underline-offset-4 hover:no-underline focus-visible:outline-2"
                        download
                      >
                        Download portable JSON report
                      </a>
                    </div>
                  </Section>

                  {result.proposal ? (
                    <Section title="Later-context review">
                      <div className="space-y-2 rounded-lg border bg-white p-3">
                        <p className="text-xs text-zinc-500">
                          Check this proposal against an explicit later scenario revision. The
                          original replay is never altered.
                        </p>
                        <div className="flex flex-wrap items-center gap-2">
                          <select
                            value={reviewTargetKey}
                            onChange={(event) => setReviewTargetKey(event.target.value)}
                            className="rounded-md border border-zinc-300 px-2 py-1.5 text-sm focus-visible:outline-2"
                            aria-label="Later scenario revision"
                          >
                            <option value="">Select later revision…</option>
                            {scenarios
                              .filter(
                                (scenario) =>
                                  !(
                                    scenario.scenario_id === activeAttempt.scenario_id &&
                                    scenario.revision === activeAttempt.scenario_revision
                                  ),
                              )
                              .map((scenario) => (
                                <option
                                  key={`${scenario.scenario_id}@${scenario.revision}`}
                                  value={`${scenario.scenario_id}@${scenario.revision}`}
                                >
                                  {scenario.scenario_id}@{scenario.revision} · {scenario.title.slice(0, 40)}
                                </option>
                              ))}
                          </select>
                          <Button
                            size="sm"
                            disabled={!reviewTargetKey || reviewMutation.isPending}
                            onClick={() => {
                              const [scenarioId, revision] = reviewTargetKey.split('@')
                              reviewMutation.mutate({
                                scenarioId,
                                revision: Number(revision),
                              })
                            }}
                          >
                            {reviewMutation.isPending ? 'Checking…' : 'Run review check'}
                          </Button>
                          {reviewMutation.isError ? (
                            <span className="text-xs text-red-700">{reviewMutation.error.message}</span>
                          ) : null}
                        </div>
                        {reviewResult ? <ReviewOutcome review={reviewResult} /> : null}
                      </div>
                    </Section>
                  ) : null}
                </>
              ) : result && 'execution_error' in result ? (
                <Alert variant="destructive">
                  <AlertTitle>Execution error: {result.execution_error.code}</AlertTitle>
                  <AlertDescription>{result.execution_error.message}</AlertDescription>
                </Alert>
              ) : null}
            </>
          )}

          {sessionAttempts.length > 1 ? (
            <Section title="Executions in this session">
              <div className="overflow-x-auto rounded-lg border bg-white">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Attempt</TableHead>
                      <TableHead className="w-32">Configuration</TableHead>
                      <TableHead className="w-44">Outcome</TableHead>
                      <TableHead className="w-36">Expectation</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sessionAttempts.map((attempt) => (
                      <TableRow
                        key={attempt.id}
                        onClick={() => setActiveAttemptId(attempt.id)}
                        className={cn(
                          'cursor-pointer',
                          attempt.id === activeAttempt?.id && 'bg-zinc-100',
                        )}
                      >
                        <TableCell>
                          <Mono>{shortDigest(attempt.id)}</Mono>
                        </TableCell>
                        <TableCell>
                          <Mono>{attempt.configuration_id.replace('CFG-', '')}</Mono>
                        </TableCell>
                        <TableCell>
                          {attempt.domain_outcome ? (
                            <OutcomeBadge outcome={attempt.domain_outcome} />
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <ExpectationBadge verdict={attempt.expectation_verdict} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Section>
          ) : null}
        </div>
      </div>

      <EvidenceDrawer
        evidence={drawerEvidence}
        open={drawerEvidence !== null}
        onOpenChange={(open) => {
          if (!open) setDrawerEvidence(null)
        }}
      />
    </div>
  )
}
