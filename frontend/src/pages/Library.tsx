/**
 * Scenario library: find a scenario and understand the behavior it tests.
 * Latest results are always shown with their configuration; there is no
 * global "passing" badge without configuration context.
 */

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '@/lib/api'
import { formatInstant } from '@/lib/status'
import { ExpectationBadge, Mono, OutcomeBadge } from '@/components/status'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/board'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

function ConfigLabel({ id }: { id: string }) {
  if (id === 'CFG-BASELINE-V1') return 'baseline'
  if (id === 'CFG-IMPROVED-V1') return 'improved'
  if (id === 'CFG-DEFECT-SKILLFRESH') return 'defect'
  return id.replace('CFG-', '').toLowerCase() // unknown ids keep their own name
}

export function LibraryPage() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['scenarios'],
    queryFn: api.scenarios,
  })

  if (isPending) {
    return (
      <div className="space-y-6">
        <PageHeader title="Scenario library" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Scenario library" />
        <Alert variant="destructive">
          <AlertTitle>The scenario library could not be loaded</AlertTitle>
          <AlertDescription className="flex items-center gap-3">
            <span>{error.message}</span>
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const latestByScenario = new Map<string, typeof data.latest_attempts>()
  for (const attempt of data.latest_attempts) {
    const key = `${attempt.scenario_id}@${attempt.scenario_revision}`
    const list = latestByScenario.get(key) ?? []
    list.push(attempt)
    latestByScenario.set(key, list)
  }

  return (
    <div className="space-y-6">
      <div className="border-b-2 border-foreground pb-5">
        <h1 className="text-3xl font-bold font-stretch-semi-condensed sm:text-4xl">
          Scenario library
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          Pinned operational episodes. Each revision freezes its evidence; corrections create new
          revisions and never rewrite history.
        </p>
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        <Link className="underline underline-offset-4" to="/coverage/workbench">
          Replay workbench
        </Link>
        <Link className="underline underline-offset-4" to="/coverage/notes">
          Floor notes
        </Link>
        <Link className="underline underline-offset-4" to="/coverage/imports">
          Imports
        </Link>
        <Link className="underline underline-offset-4" to="/coverage/comparison">
          Comparison
        </Link>
      </div>

      {data.items.length === 0 ? (
        <div className="rounded-sm border border-dashed bg-card p-10 text-center">
          <p className="text-sm font-medium">No scenarios are seeded yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Run <Mono>make seed</Mono> to load the synthetic release fixtures, then reload.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-sm border bg-card">
          <Table className="min-w-[1000px] table-fixed" aria-label="Coverage scenarios">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[26%]">Scenario</TableHead>
                <TableHead className="w-[32%]">Behavior it tests</TableHead>
                <TableHead className="w-[18%]">Decision time</TableHead>
                <TableHead className="w-[24%]">Latest result by configuration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((item) => {
                const key = `${item.scenario_id}@${item.revision}`
                const attempts = latestByScenario.get(key) ?? []
                return (
                  <TableRow key={key}>
                    <TableCell>
                      <Link
                        to={`/coverage/workbench?scenario=${encodeURIComponent(item.scenario_id)}&revision=${item.revision}`}
                        className="font-medium underline-offset-4 hover:underline focus-visible:outline-2"
                      >
                        {item.title}
                      </Link>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <Mono className="text-muted-foreground">
                          {item.scenario_id}@{item.revision}
                        </Mono>
                        {Array.from(new Set(item.tags)).map((tag) => (
                          <Badge key={tag} variant="secondary" className="px-1.5 text-xs">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm leading-6 text-muted-foreground">
                      {item.defect_statement}
                    </TableCell>
                    <TableCell className="text-sm leading-6 text-muted-foreground">
                      {formatInstant(item.decision_at)}
                    </TableCell>
                    <TableCell>
                      {attempts.length === 0 ? (
                        <span className="text-xs text-muted-foreground">
                          Not run in this database yet
                        </span>
                      ) : (
                        <ul className="space-y-1.5">
                          {attempts.map((attempt) => (
                            <li
                              key={attempt.configuration_id}
                              className="flex flex-wrap items-center gap-2"
                            >
                              <Mono className="w-14 shrink-0 text-muted-foreground">
                                <ConfigLabel id={attempt.configuration_id} />
                              </Mono>
                              {attempt.domain_outcome ? (
                                <OutcomeBadge outcome={attempt.domain_outcome} />
                              ) : null}
                              <ExpectationBadge verdict={attempt.expectation_verdict} />
                            </li>
                          ))}
                        </ul>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
