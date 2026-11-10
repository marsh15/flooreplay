import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { ConstraintCard } from '@/components/decisions/ConstraintCard'
import { FactDrawer } from '@/components/decisions/FactDrawer'
import { FreshnessBadge } from '@/components/decisions/FreshnessBadge'
import { GateBanner } from '@/components/decisions/GateBanner'
import { RecordDecisionForm } from '@/components/decisions/RecordDecisionForm'
import { PageHeader, Section, StatusTag } from '@/components/board'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { DEMO_WORKSPACE, useDecisionWorkspace } from '@/lib/decision-workspace'
import { getOrderDecision, recordDecision } from '@/lib/decisions'
import { formatInstant } from '@/lib/status'
import type { Condition, Outcome } from '@/lib/decisions-types'

function isUtcIso(value: string | null): value is string {
  return Boolean(
    value &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value) &&
    Number.isFinite(Date.parse(value)),
  )
}

function conditionText(condition: Condition) {
  if (condition.type === 'overtime')
    return `Schedule ${condition.hours_per_line_per_day} overtime hours per line per day across ${condition.lines} lines for ${condition.days} days.`
  if (condition.type === 'split_shipment')
    return `Ship ${condition.covered_qty} pcs of ${condition.colour} first; ship the remaining ${condition.remainder_qty} pcs by ${condition.remainder_ship_date}.`
  return 'A condition is recorded for this recommendation.'
}

export function OrderDecision() {
  const { orderId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const requestedCutoff = searchParams.get('cutoff')
  const policy = searchParams.get('policy') ?? undefined
  const cutoff = isUtcIso(requestedCutoff) ? requestedCutoff : undefined
  const invalidCutoff = requestedCutoff !== null && cutoff === undefined
  const { user, epoch } = useAuth()
  const workspace = useDecisionWorkspace()
  const queryClient = useQueryClient()
  const [factId, setFactId] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const decision = useQuery({
    queryKey: [
      'order-decision',
      user?.id ?? 'public',
      epoch,
      workspace,
      orderId,
      cutoff ?? 'latest',
      policy ?? 'adopted',
    ],
    queryFn: () => getOrderDecision(orderId, { cutoff, policy }),
    enabled: Boolean(orderId),
  })
  const record = useMutation({
    mutationFn: ({ finalOutcome, reason }: { finalOutcome: Outcome; reason: string }) => {
      if (!decision.data) throw new Error('The decision is not available yet.')
      return recordDecision(orderId, {
        cutoff: decision.data.cutoff,
        policy_digest: decision.data.policy.digest,
        final_outcome: finalOutcome,
        reason,
      })
    },
    onSuccess: async () => {
      setMessage('Final decision recorded with its reason.')
      await queryClient.invalidateQueries({
        queryKey: ['order-decision', user?.id ?? 'public', epoch, workspace, orderId],
      })
    },
  })
  if (decision.isPending)
    return (
      <p role="status" aria-busy="true">
        Loading order decision…
      </p>
    )
  if (decision.isError)
    return (
      <Alert variant="limit">
        <div className="space-y-2">
          <p>This order decision could not be loaded.</p>
          <Button variant="outline" onClick={() => void decision.refetch()}>
            Retry decision
          </Button>
          <Button asChild variant="link">
            <Link to="/">Back to orders</Link>
          </Button>
        </div>
      </Alert>
    )
  const view = decision.data
  const latestFactBySource = [
    ...new Map(
      [...view.facts]
        .sort((left, right) => left.known_at.localeCompare(right.known_at))
        .map((fact) => [fact.source, fact]),
    ).values(),
  ]
  const timelineParams = new URLSearchParams()
  if (cutoff) timelineParams.set('cutoff', cutoff)
  if (policy) timelineParams.set('policy', policy)
  const timelineQuery = timelineParams.size ? `?${timelineParams.toString()}` : ''
  return (
    <div className="space-y-8">
      <PageHeader
        title={
          <>
            Order <span className="font-mono">{view.order_id}</span>
          </>
        }
        actions={
          <Button asChild variant="outline">
            <Link to={`/orders/${encodeURIComponent(orderId)}/timeline${timelineQuery}`}>
              Knowledge timeline
            </Link>
          </Button>
        }
      >
        <p className="mt-2 max-w-3xl text-base text-muted-foreground">
          Decision evidence known by {formatInstant(view.cutoff)} (IST).
        </p>
      </PageHeader>
      {!view.settled && (
        <Alert variant="limit">This replay is unsettled and may change as more facts arrive.</Alert>
      )}
      {invalidCutoff && (
        <Alert variant="limit" role="status">
          The cutoff in this link is not a valid UTC time. Showing the latest available replay.
        </Alert>
      )}
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-y-2 border-foreground py-3 text-sm">
        <span>
          <strong>Ship date:</strong>{' '}
          {(view.facts.find((fact) => fact.kind === 'order_request')?.payload
            .ship_date as string) ?? 'Not recorded'}
        </span>
        <span>
          <strong>Policy:</strong> {view.policy.label}
        </span>
        <span className="font-mono text-xs">
          <strong>Decision digest:</strong> {view.decision_digest}
        </span>
      </div>
      <Section
        title="Evidence gate"
        detail="Every finding includes its rule and supporting fact IDs."
      >
        <GateBanner gate={view.gate} onOpenFact={setFactId} />
        {view.constraints.some((result) => result.pending_review_fact_ids.length > 0) && (
          <Alert variant="limit">
            <p>Some evidence affecting this decision needs a human review.</p>
            <Link className="ml-1 font-semibold underline underline-offset-2" to="/review">
              Open the review queue
            </Link>
          </Alert>
        )}
        <div className="flex flex-wrap gap-x-6 gap-y-2 border-l-2 border-border pl-3 text-sm">
          {latestFactBySource.map((fact) => (
            <FreshnessBadge
              key={fact.id}
              factId={fact.id}
              source={fact.source}
              validFrom={fact.valid_from}
              cutoff={view.cutoff}
              gateState={view.gate.state}
            />
          ))}
        </div>
      </Section>
      <Section
        title="Recommendation"
        detail="The deterministic engine result is advice; the merchandiser records the final call."
      >
        <div className="space-y-4 rounded-sm border border-border bg-card p-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusTag
              tone={
                view.recommendation.outcome === 'ACCEPT'
                  ? 'success'
                  : view.recommendation.outcome === 'DECLINE'
                    ? 'danger'
                    : 'limit'
              }
            >
              {view.recommendation.outcome.replaceAll('_', ' ')}
            </StatusTag>
            <span>Engine recommendation</span>
          </div>
          {view.recommendation.candidate_outcome && (
            <p className="text-sm">
              Outcome pending approval:{' '}
              <strong>{view.recommendation.candidate_outcome.replaceAll('_', ' ')}</strong>
            </p>
          )}
          {view.recommendation.reasons.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {view.recommendation.reasons.map((reason, index) => (
                <li key={`${index}:${reason}`}>{reason}</li>
              ))}
            </ul>
          )}
          {view.recommendation.conditions.length > 0 && (
            <div>
              <h3 className="mb-2 font-semibold">Conditions</h3>
              <ul className="list-disc space-y-2 pl-5 text-sm">
                {view.recommendation.conditions.map((condition, index) => (
                  <li key={`${condition.type}:${index}`}>{conditionText(condition)}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Section>
      <Section
        title="Constraint checks"
        detail="Arithmetic is shown in the order the engine evaluated it."
      >
        {view.constraints.length ? (
          <div className="grid min-w-0 gap-4 lg:grid-cols-2">
            {view.constraints.map((result, index) => (
              <ConstraintCard
                key={`${result.constraint}:${result.subject}:${index}`}
                result={result}
                onOpenFact={setFactId}
              />
            ))}
          </div>
        ) : (
          <p role="status">No constraints were evaluated.</p>
        )}
      </Section>
      <Section
        title="Record the final decision"
        detail="A final outcome and a written reason are stored with the replay cutoff."
      >
        {(!user || workspace === DEMO_WORKSPACE) && (
          <Alert variant="info">
            Recording a decision needs a signed-in account and a private workspace. The public demo
            is read only.
          </Alert>
        )}
        {record.isError && <Alert variant="destructive">{record.error.message}</Alert>}
        <div className="max-w-2xl rounded-sm border border-border bg-card p-4">
          <RecordDecisionForm
            key={`${view.decision_digest}:${view.cutoff}`}
            engineOutcome={view.recommendation.outcome}
            onSubmit={(finalOutcome, reason) => {
              setMessage('')
              record.mutate({ finalOutcome, reason })
            }}
            busy={record.isPending}
            success={message}
          />
        </div>
      </Section>
      {view.records.length > 0 && (
        <Section
          title="Recorded decisions"
          detail="Human decisions remain linked to the exact engine replay."
        >
          <ol className="space-y-3">
            {view.records.map((item) => (
              <li key={item.id} className="rounded-sm border border-border bg-card p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusTag tone={item.override ? 'limit' : 'success'}>
                    {item.override ? 'Human override' : 'Recorded outcome'}
                  </StatusTag>
                  <strong>{item.final_outcome.replaceAll('_', ' ')}</strong>
                  <span className="text-sm text-muted-foreground">
                    by {item.reviewer} · {formatInstant(item.recorded_at)}
                  </span>
                </div>
                <p className="mt-2 text-sm">{item.reason}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Engine recommendation: {item.engine_outcome.replaceAll('_', ' ')}
                </p>
              </li>
            ))}
          </ol>
        </Section>
      )}
      <FactDrawer factId={factId} facts={view.facts} onClose={() => setFactId(null)} />
    </div>
  )
}
