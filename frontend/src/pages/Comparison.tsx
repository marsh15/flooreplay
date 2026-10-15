import { useAuth } from '@/components/Auth'
/**
 * Comparison report: which behavior changed between two configurations,
 * and whether expectations regressed. Totals are actual counts; a row
 * opens a side-by-side result view. An interrupted suite can never pass.
 */

import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  api,
  type Classification,
  type ComparisonItem,
  type ComparisonReport,
  type ComparisonSide,
} from '@/lib/api'
import { formatInstant, OUTCOME_META } from '@/lib/status'
import { Mono, OutcomeBadge } from '@/components/status'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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

const CLASSIFICATION_META: Record<Classification, { label: string; tone: string }> = {
  UNCHANGED_PASS: {
    label: 'Unchanged pass',
    tone: 'bg-success text-success-foreground border-success-border',
  },
  FIXED: {
    label: 'Fixed',
    tone: 'bg-success text-success-foreground border-success-border font-semibold',
  },
  REGRESSION: {
    label: 'Regression',
    tone: 'bg-danger text-danger-foreground border-danger-border font-semibold',
  },
  UNCHANGED_FAIL: {
    label: 'Unchanged fail',
    tone: 'bg-danger text-danger-foreground border-danger-border',
  },
  NOT_COMPARABLE: { label: 'Not comparable', tone: 'bg-secondary text-foreground border-input' },
}

function ClassificationBadge({ classification }: { classification: Classification }) {
  const meta = CLASSIFICATION_META[classification]
  return (
    <Badge variant="outline" className={cn('h-auto px-2 py-0.5 text-xs', meta.tone)}>
      {meta.label}
    </Badge>
  )
}

function SidePanel({ title, side }: { title: string; side: ComparisonSide }) {
  return (
    <div className="rounded-sm border bg-card p-3">
      <p className="text-sm font-semibold text-foreground">{title}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        {side.outcome ? <OutcomeBadge outcome={side.outcome} /> : null}
        <Badge variant="secondary" className="text-xs">
          expectation {side.verdict.toLowerCase()}
        </Badge>
        {side.operator ? (
          <span className="text-sm">
            proposes <Mono className="font-semibold">{side.operator}</Mono>
          </span>
        ) : null}
      </div>
      {side.outcome ? (
        <p className="mt-1 text-xs text-muted-foreground">{OUTCOME_META[side.outcome].hint}</p>
      ) : null}
      {side.issue_codes.length > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          issues: <Mono>{side.issue_codes.join(', ')}</Mono>
        </p>
      ) : null}
      {side.failures.length > 0 ? (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-danger-foreground">
          {side.failures.map((failure) => (
            <li key={failure}>{failure}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

type SortKey = 'scenario' | 'category' | 'classification' | 'baseline' | 'candidate'

function SortHead({
  sort,
  activeKey,
  ascending,
  onSort,
  children,
}: {
  sort: SortKey
  activeKey: SortKey
  ascending: boolean
  onSort: (key: SortKey) => void
  children: React.ReactNode
}) {
  return (
    <TableHead>
      <button
        type="button"
        onClick={() => onSort(sort)}
        className="inline-flex items-center gap-1 text-xs hover:text-foreground focus-visible:outline-2"
      >
        {children}
        {activeKey === sort ? <span aria-hidden>{ascending ? '↑' : '↓'}</span> : null}
      </button>
    </TableHead>
  )
}

export function ComparisonPage() {
  const { user } = useAuth()
  const suitesQuery = useQuery({ queryKey: ['suites'], queryFn: api.suites })
  const configsQuery = useQuery({ queryKey: ['configurations'], queryFn: api.configurations })
  const historyQuery = useQuery({ queryKey: ['comparisons'], queryFn: api.comparisons })
  const capsQuery = useQuery({
    queryKey: ['capabilities', user?.id ?? 'public'],
    queryFn: api.capabilities,
  })

  const suite = suitesQuery.data?.items[0]
  const configurations = configsQuery.data?.items ?? []
  const executionLocalOnly =
    !capsQuery.data?.imports_enabled ||
    capsQuery.data.execution_limits.comparison_execution === 'local_only'
  const [baselineId, setBaselineId] = useState<string>('CFG-BASELINE-V1')
  const [candidateId, setCandidateId] = useState<string>('CFG-IMPROVED-V1')
  const [report, setReport] = useState<ComparisonReport | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('scenario')
  const [sortAsc, setSortAsc] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)

  const runMutation = useMutation({
    mutationFn: () =>
      api.runComparison({
        suite_id: suite!.id,
        baseline_config_id: baselineId,
        candidate_config_id: candidateId,
        idempotency_key: `ui-cmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      }),
    onSuccess: (data) => {
      setReport(data)
      historyQuery.refetch()
    },
  })

  const items = useMemo(() => {
    const list = report?.items ?? []
    const key = (item: ComparisonItem): string => {
      switch (sortKey) {
        case 'category':
          return `${item.category}-${item.scenario_id}`
        case 'classification':
          return `${item.classification}-${item.scenario_id}`
        case 'baseline':
          return `${item.baseline.verdict}-${item.scenario_id}`
        case 'candidate':
          return `${item.candidate.verdict}-${item.scenario_id}`
        default:
          return item.scenario_id
      }
    }
    const sorted = [...list].sort((a, b) => key(a).localeCompare(key(b)))
    return sortAsc ? sorted : sorted.reverse()
  }, [report, sortKey, sortAsc])

  function headerClick(next: SortKey) {
    if (next === sortKey) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(next)
      setSortAsc(true)
    }
  }

  if (suitesQuery.isPending || configsQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (suitesQuery.isError || configsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Comparisons are unavailable</AlertTitle>
        <AlertDescription>{(suitesQuery.error ?? configsQuery.error)?.message}</AlertDescription>
      </Alert>
    )
  }

  const totals = report?.totals

  return (
    <div className="space-y-6">
      <div className="border-b-2 border-foreground pb-5">
        <h1 className="text-3xl font-bold font-stretch-semi-condensed sm:text-4xl">
          Comparison report
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          Execute the pinned suite ({suite?.case_count ?? 0} cases) under two configurations and
          inspect which behavior changed. Pass/fail is judgment; behavior changes are reported
          separately.
        </p>
      </div>

      <div className="grid items-end gap-4 rounded-sm border bg-card p-5 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto]">
        <label className="text-xs">
          <span className="mb-1 block font-medium text-muted-foreground">
            Baseline configuration
          </span>
          <select
            value={baselineId}
            onChange={(event) => setBaselineId(event.target.value)}
            className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-2"
          >
            {configurations.map((config) => (
              <option key={config.id} value={config.id}>
                {config.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="mb-1 block font-medium text-muted-foreground">
            Candidate configuration
          </span>
          <select
            value={candidateId}
            onChange={(event) => setCandidateId(event.target.value)}
            className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-2"
          >
            {configurations.map((config) => (
              <option key={config.id} value={config.id}>
                {config.name}
              </option>
            ))}
          </select>
        </label>
        {executionLocalOnly ? (
          <p className="text-xs text-muted-foreground">
            Sign in as an owner in the local deployment to execute this archived suite. Saved
            reports remain readable.
          </p>
        ) : (
          <Button
            disabled={!suite || baselineId === candidateId || runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            {runMutation.isPending ? 'Executing suite…' : 'Run comparison'}
          </Button>
        )}
        {runMutation.isError ? (
          <span className="text-xs text-danger-foreground">{runMutation.error.message}</span>
        ) : null}
      </div>

      {report ? (
        <>
          {report.status === 'INTERRUPTED' ? (
            <Alert variant="destructive">
              <AlertTitle>Suite execution was interrupted</AlertTitle>
              <AlertDescription>
                {report.totals.completed} of {report.totals.total} cases completed. An incomplete
                suite can never receive an overall passing verdict.
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="grid grid-cols-2 gap-y-5 rounded-sm border bg-card px-5 py-5 sm:grid-cols-4">
            {(
              [
                ['unchanged_pass', 'Unchanged pass'],
                ['fixed', 'Fixed'],
                ['regression', 'Regression'],
                ['unchanged_fail', 'Unchanged fail'],
              ] as const
            ).map(([key, label]) => (
              <div key={key} role="group" aria-label={label} className="px-3">
                <p className="text-lg font-semibold tabular-nums">{totals?.[key] ?? 0}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
              </div>
            ))}
          </div>

          <p className="text-xs text-muted-foreground">
            Baseline <Mono>{report.baseline_config_id}</Mono> vs candidate{' '}
            <Mono>{report.candidate_config_id}</Mono> · Suite {report.suite_id}@
            {report.suite_revision} · executed {formatInstant(report.created_at)} · persisted report
            · manifest <Mono>{report.manifest_digest?.slice(0, 19)}…</Mono>
          </p>

          <div className="overflow-x-auto rounded-sm border bg-card">
            <Table className="min-w-[860px]">
              <TableHeader>
                <TableRow>
                  <SortHead
                    sort="scenario"
                    activeKey={sortKey}
                    ascending={sortAsc}
                    onSort={headerClick}
                  >
                    Scenario
                  </SortHead>
                  <SortHead
                    sort="category"
                    activeKey={sortKey}
                    ascending={sortAsc}
                    onSort={headerClick}
                  >
                    Category
                  </SortHead>
                  <SortHead
                    sort="classification"
                    activeKey={sortKey}
                    ascending={sortAsc}
                    onSort={headerClick}
                  >
                    Classification
                  </SortHead>
                  <SortHead
                    sort="baseline"
                    activeKey={sortKey}
                    ascending={sortAsc}
                    onSort={headerClick}
                  >
                    Baseline
                  </SortHead>
                  <SortHead
                    sort="candidate"
                    activeKey={sortKey}
                    ascending={sortAsc}
                    onSort={headerClick}
                  >
                    Candidate
                  </SortHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <Fragment key={`${item.scenario_id}:${item.title}:${item.category}`}>
                    <TableRow
                      onClick={() =>
                        setExpanded(expanded === item.scenario_id ? null : item.scenario_id)
                      }
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          setExpanded(expanded === item.scenario_id ? null : item.scenario_id)
                        }
                      }}
                      tabIndex={0}
                      aria-label={`Toggle detail for ${item.scenario_id}`}
                      className={cn(
                        'cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-[-2px]',
                        expanded === item.scenario_id && 'bg-secondary',
                        item.classification === 'REGRESSION' && 'bg-danger',
                      )}
                      aria-expanded={expanded === item.scenario_id}
                    >
                      <TableCell>
                        <span className="font-medium">{item.title}</span>
                        <Mono className="ml-1 text-muted-foreground">{item.scenario_id}</Mono>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-xs">
                          {item.category}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <ClassificationBadge classification={item.classification} />
                          {item.behavior_changed ? (
                            <Badge
                              variant="outline"
                              className="border-info-border bg-info text-xs text-info-foreground"
                            >
                              behavior changed
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {item.baseline.outcome ? (
                            <OutcomeBadge outcome={item.baseline.outcome} />
                          ) : null}
                          <Badge variant="secondary" className="text-xs">
                            {item.baseline.verdict.toLowerCase()}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {item.candidate.outcome ? (
                            <OutcomeBadge outcome={item.candidate.outcome} />
                          ) : null}
                          <Badge variant="secondary" className="text-xs">
                            {item.candidate.verdict.toLowerCase()}
                          </Badge>
                        </div>
                      </TableCell>
                    </TableRow>
                    {expanded === item.scenario_id ? (
                      <TableRow>
                        <TableCell colSpan={5} className="bg-secondary">
                          <p className="mb-2 text-xs text-muted-foreground">
                            Catches: {item.defect_statement}
                          </p>
                          <div className="grid gap-2 sm:grid-cols-2">
                            <SidePanel
                              title={`Baseline · ${report.baseline_config_id}`}
                              side={item.baseline}
                            />
                            <SidePanel
                              title={`Candidate · ${report.candidate_config_id}`}
                              side={item.candidate}
                            />
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      ) : (
        <div className="rounded-sm border border-dashed bg-card p-10 text-center">
          <p className="text-sm font-medium">No comparison executed yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            Choose a baseline and a candidate configuration and press{' '}
            <span className="font-medium">Run comparison</span>. The suite executes sequentially
            with a bounded budget; the persisted report appears here with per-case transitions.
          </p>
        </div>
      )}

      {historyQuery.isError ? (
        <p className="text-xs text-danger-foreground">
          Comparison history could not be loaded: {historyQuery.error.message}
        </p>
      ) : null}

      {historyQuery.data && historyQuery.data.items.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-lg font-bold">Recent comparisons</h2>
          <ul className="divide-y divide-border rounded-sm border bg-card text-sm">
            {historyQuery.data.items.slice(0, 6).map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <Mono className="text-muted-foreground">
                  {entry.baseline_config_id.replace('CFG-', '')} →{' '}
                  {entry.candidate_config_id.replace('CFG-', '')}
                </Mono>
                <Badge variant="secondary" className="text-xs">
                  pass {entry.totals.unchanged_pass}
                </Badge>
                {entry.totals.fixed > 0 ? (
                  <Badge
                    variant="secondary"
                    className="border border-success-border bg-success text-xs text-success-foreground"
                  >
                    fixed {entry.totals.fixed}
                  </Badge>
                ) : null}
                {entry.totals.regression > 0 ? (
                  <Badge
                    variant="secondary"
                    className="border border-danger-border bg-danger text-xs text-danger-foreground"
                  >
                    regression {entry.totals.regression}
                  </Badge>
                ) : null}
                <span className="ml-auto text-xs text-muted-foreground">
                  {formatInstant(entry.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}
