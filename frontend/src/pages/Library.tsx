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
      <div className="space-y-3">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>The scenario library could not be loaded</AlertTitle>
        <AlertDescription className="flex items-center gap-3">
          <span>{error.message}</span>
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            Retry
          </Button>
        </AlertDescription>
      </Alert>
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
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Scenario library</h1>
        <p className="mt-0.5 text-sm text-zinc-500">
          Pinned operational episodes. Each revision freezes its evidence; corrections create new
          revisions and never rewrite history.
        </p>
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-zinc-600">
        <Link className="underline underline-offset-4" to="/coverage/workbench">Replay workbench</Link>
        <Link className="underline underline-offset-4" to="/coverage/notes">Floor notes</Link>
        <Link className="underline underline-offset-4" to="/coverage/imports">Imports</Link>
        <Link className="underline underline-offset-4" to="/coverage/comparison">Comparison</Link>
      </div>

      {data.items.length === 0 ? (
        <div className="rounded-lg border border-dashed bg-white p-10 text-center">
          <p className="text-sm font-medium">No scenarios are seeded yet</p>
          <p className="mt-1 text-sm text-zinc-500">
            Run <Mono>make seed</Mono> to load the synthetic release fixtures, then reload.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[26%]">Scenario</TableHead>
                <TableHead>Behavior it tests</TableHead>
                <TableHead className="w-44">Decision time</TableHead>
                <TableHead className="w-[38%]">Latest result by configuration</TableHead>
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
                        <Mono className="text-zinc-400">
                          {item.scenario_id}@{item.revision}
                        </Mono>
                        {item.tags.map((tag) => (
                          <Badge key={tag} variant="secondary" className="px-1.5 text-[10px]">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-md text-sm text-zinc-600">
                      {item.defect_statement}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-zinc-600">
                      {formatInstant(item.decision_at)}
                    </TableCell>
                    <TableCell>
                      {attempts.length === 0 ? (
                        <span className="text-xs text-zinc-400">Not run in this database yet</span>
                      ) : (
                        <ul className="space-y-1.5">
                          {attempts.map((attempt) => (
                            <li key={attempt.configuration_id} className="flex items-center gap-2">
                              <Mono className="w-14 shrink-0 text-zinc-500">
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
