import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { PageHeader, Section, StatusTag } from '@/components/board'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/components/Auth'
import { listOrders } from '@/lib/decisions'
import { formatInstant } from '@/lib/status'
import type { GateState, Outcome } from '@/lib/decisions-types'

const OUTCOME_LABEL: Record<Outcome, string> = {
  ACCEPT: 'Accept',
  ACCEPT_WITH_CONDITIONS: 'Accept with conditions',
  DECLINE: 'Decline',
  NEEDS_REVIEW: 'Needs review',
}

function statusTone(state: GateState | Outcome) {
  if (state === 'READY' || state === 'ACCEPT') return 'success' as const
  if (state === 'CONFLICTING' || state === 'DECLINE') return 'danger' as const
  if (state === 'STALE' || state === 'INCOMPLETE' || state === 'NEEDS_REVIEW')
    return 'limit' as const
  return 'info' as const
}

export function DecisionsHome() {
  const { user, epoch } = useAuth()
  const orders = useQuery({
    queryKey: ['decision-orders', user?.id ?? 'public', epoch],
    queryFn: listOrders,
  })
  return (
    <div className="space-y-8">
      <PageHeader title="Order decisions">
        <p className="mt-2 max-w-3xl text-base text-muted-foreground">
          Review a proposed decision against the fabric, trims, capacity and approval evidence
          available at a specific cutoff.
        </p>
      </PageHeader>
      <Alert variant="info">
        <strong>Synthetic manufacturing data.</strong> Public demo orders use synthetic data from a
        fictional knit-garment exporter.
      </Alert>
      <Section
        title="Urgent orders"
        detail="The latest settled replay is shown for each order. Open an order to inspect its evidence and arithmetic."
      >
        {orders.isPending ? (
          <p role="status" aria-busy="true">
            Loading orders…
          </p>
        ) : orders.isError ? (
          <Alert variant="limit">
            <div className="space-y-2">
              <p>Orders could not be loaded. Try again when the decisions service is available.</p>
              <Button variant="outline" onClick={() => void orders.refetch()}>
                Retry orders
              </Button>
            </div>
          </Alert>
        ) : orders.data.orders.length === 0 ? (
          <div role="status" className="rounded-sm border border-border bg-card p-5">
            <h3 className="font-semibold">No orders yet</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Import an order request and its evidence to start a replay.
            </p>
            <Button className="mt-4" asChild>
              <Link to="/imports">Import evidence</Link>
            </Button>
          </div>
        ) : (
          <div
            className="overflow-x-auto rounded-sm border border-border bg-card"
            tabIndex={0}
            aria-label="Urgent orders table"
          >
            <table className="w-full min-w-[44rem] text-left text-sm">
              <thead className="bg-muted/70 text-xs">
                <tr>
                  <th scope="col" className="p-3">
                    Order
                  </th>
                  <th scope="col" className="p-3">
                    Buyer
                  </th>
                  <th scope="col" className="p-3">
                    Style
                  </th>
                  <th scope="col" className="p-3">
                    Ship date
                  </th>
                  <th scope="col" className="p-3">
                    Quantity
                  </th>
                  <th scope="col" className="p-3">
                    Latest outcome
                  </th>
                  <th scope="col" className="p-3">
                    Gate
                  </th>
                </tr>
              </thead>
              <tbody>
                {orders.data.orders.map((order) => (
                  <tr
                    key={order.order_id}
                    className="border-t border-border align-top hover:bg-muted/30"
                  >
                    <th scope="row" className="p-3">
                      <Link
                        className="font-mono font-semibold text-primary underline underline-offset-2 focus-visible:outline-2"
                        to={`/orders/${encodeURIComponent(order.order_id)}`}
                      >
                        {order.order_id}
                      </Link>
                    </th>
                    <td className="p-3">{order.buyer}</td>
                    <td className="p-3">{order.style_id}</td>
                    <td className="p-3 tabular-nums">{order.ship_date}</td>
                    <td className="p-3 tabular-nums">{order.total_qty} pcs</td>
                    <td className="p-3">
                      {order.latest ? (
                        <>
                          <StatusTag tone={statusTone(order.latest.outcome)}>
                            {OUTCOME_LABEL[order.latest.outcome]}
                          </StatusTag>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {formatInstant(order.latest.cutoff)}
                          </p>
                        </>
                      ) : (
                        <span className="text-muted-foreground">No settled replay</span>
                      )}
                    </td>
                    <td className="p-3">
                      {order.latest ? (
                        <StatusTag tone={statusTone(order.latest.gate_state)}>
                          {order.latest.gate_state}
                        </StatusTag>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <p className="text-xs text-muted-foreground">
        <Link className="underline underline-offset-2" to="/investigations">
          Shortfall investigations (v1)
        </Link>
      </p>
    </div>
  )
}
