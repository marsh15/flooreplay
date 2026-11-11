import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { FactDrawer } from '@/components/decisions/FactDrawer'
import { KnowledgeScrubber } from '@/components/decisions/KnowledgeScrubber'
import { PageHeader, Section, StatusTag } from '@/components/board'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useDecisionWorkspace } from '@/lib/decision-workspace'
import { getOrderDecision, getOrderTimeline } from '@/lib/decisions'
import { formatInstant } from '@/lib/status'

function closestIndex(times: string[], instant: number) {
  let result = 0
  for (let index = 0; index < times.length; index += 1) {
    if (new Date(times[index]).getTime() <= instant) result = index
  }
  return result
}

function isUtcIso(value: string | null): value is string {
  return Boolean(
    value &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value) &&
    Number.isFinite(Date.parse(value)),
  )
}

export function Timeline() {
  const { orderId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedCutoff = searchParams.get('cutoff')
  const policy = searchParams.get('policy') ?? undefined
  const validCutoff = isUtcIso(requestedCutoff) ? requestedCutoff : undefined
  const invalidCutoff = requestedCutoff !== null && validCutoff === undefined
  const { user, epoch } = useAuth()
  const workspace = useDecisionWorkspace()
  const [factId, setFactId] = useState<string | null>(null)
  const timeline = useQuery({
    queryKey: ['order-timeline', user?.id ?? 'public', epoch, workspace, orderId],
    queryFn: () => getOrderTimeline(orderId),
    enabled: Boolean(orderId),
  })
  const times = useMemo(() => timeline.data?.knowledge_times ?? [], [timeline.data])
  const index = useMemo(
    () =>
      validCutoff
        ? closestIndex(times, new Date(validCutoff).getTime())
        : Math.max(0, times.length - 1),
    [times, validCutoff],
  )
  const selectedTime = times[index]
  const decision = useQuery({
    queryKey: [
      'timeline-decision',
      user?.id ?? 'public',
      epoch,
      workspace,
      orderId,
      validCutoff ?? selectedTime ?? 'latest',
      policy ?? 'adopted',
    ],
    queryFn: () => getOrderDecision(orderId, { cutoff: validCutoff ?? selectedTime, policy }),
    enabled: Boolean(orderId && timeline.data && (validCutoff || selectedTime)),
  })
  function changeCutoff(nextIndex: number) {
    const next = times[nextIndex]
    if (next) {
      const updated = new URLSearchParams(searchParams)
      updated.set('cutoff', next)
      setSearchParams(updated, { replace: true })
    }
  }
  const decisionParams = new URLSearchParams()
  if (validCutoff) decisionParams.set('cutoff', validCutoff)
  if (policy) decisionParams.set('policy', policy)
  const decisionQuery = decisionParams.size ? `?${decisionParams.toString()}` : ''

  if (timeline.isPending)
    return (
      <p role="status" aria-busy="true">
        Loading knowledge timeline…
      </p>
    )
  if (timeline.isError)
    return (
      <Alert variant="limit">
        <div className="space-y-2">
          <p>The order timeline could not be loaded.</p>
          <Button variant="outline" onClick={() => void timeline.refetch()}>
            Retry timeline
          </Button>
        </div>
      </Alert>
    )
  return (
    <div className="space-y-8">
      <PageHeader
        title={
          <>
            Timeline · <span className="font-mono">{orderId}</span>
          </>
        }
        actions={
          <Button asChild variant="outline">
            <Link to={`/orders/${encodeURIComponent(orderId)}${decisionQuery}`}>
              Back to decision
            </Link>
          </Button>
        }
      >
        <p className="mt-2 max-w-3xl text-base text-muted-foreground">
          Replay what the system could know at each historical cutoff. Times are shown in India
          Standard Time.
        </p>
      </PageHeader>
      {invalidCutoff && (
        <Alert variant="limit" role="status">
          The cutoff in this link is not a valid time. Showing the latest available knowledge time.
        </Alert>
      )}
      <Section
        title="Knowledge-time replay"
        detail="Move the cutoff to see which facts were known and how the decision changed."
      >
        {times.length ? (
          <KnowledgeScrubber times={times} value={index} onChange={changeCutoff} />
        ) : (
          <p role="status">No knowledge times are recorded for this order.</p>
        )}
        {decision.isPending && (
          <p role="status" aria-busy="true">
            Replaying the decision…
          </p>
        )}
        {decision.isError && (
          <Alert variant="limit">The decision could not be replayed at this cutoff.</Alert>
        )}
        {decision.data && (
          <div className="space-y-3 rounded-sm border border-border bg-card p-4">
            <div className="flex flex-wrap items-center gap-3">
              <StatusTag
                tone={
                  decision.data.gate.state === 'READY'
                    ? 'success'
                    : decision.data.gate.state === 'CONFLICTING'
                      ? 'danger'
                      : 'limit'
                }
              >
                Gate: {decision.data.gate.state}
              </StatusTag>
              <StatusTag tone="info">
                {decision.data.recommendation.outcome.replaceAll('_', ' ')}
              </StatusTag>
              <span className="text-sm">Cutoff {formatInstant(decision.data.cutoff)}</span>
            </div>
            <p className="font-mono text-xs break-all">
              Decision digest: {decision.data.decision_digest}
            </p>
          </div>
        )}
      </Section>
      <Section
        title="Knowledge events"
        detail="Events are ordered by when the system learned each fact."
      >
        {timeline.data.events.length ? (
          <ol className="space-y-0 border-l-2 border-foreground pl-4">
            {timeline.data.events.map((event, index) => (
              <li
                key={`${event.fact_id}:${index}`}
                className="relative border-b border-border py-4 last:border-b-0"
              >
                <span
                  aria-hidden="true"
                  className="absolute -left-[1.38rem] top-5 size-2.5 rounded-full border border-foreground bg-background"
                />
                <div className="flex flex-wrap items-center gap-2">
                  <time className="font-mono text-xs" dateTime={event.known_at}>
                    {formatInstant(event.known_at)}
                  </time>
                  <StatusTag>{event.kind}</StatusTag>
                </div>
                <p className="mt-1">{event.summary}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Entity: <span className="font-mono">{event.entity_key}</span> · Source:{' '}
                  {event.source}
                </p>
                <Button
                  variant="link"
                  className="h-auto px-0 py-1"
                  onClick={() => setFactId(event.fact_id)}
                >
                  Open fact {event.fact_id}
                </Button>
              </li>
            ))}
          </ol>
        ) : (
          <p role="status">No events are recorded.</p>
        )}
      </Section>
      <FactDrawer
        factId={factId}
        facts={decision.data?.facts ?? []}
        onClose={() => setFactId(null)}
      />
    </div>
  )
}
