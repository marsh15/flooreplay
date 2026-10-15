import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/components/Auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Limits, PageHeader } from '@/components/board'
import { getOperations } from '@/lib/operations'

export function OperationsPage() {
  const { user } = useAuth()
  const [query, setQuery] = useState('')
  const report = useQuery({
    queryKey: ['operations', user?.id, query],
    queryFn: () => getOperations(query),
    enabled: user?.role === 'owner',
    retry: false,
  })
  return (
    <div className="space-y-6">
      <PageHeader title="Operational evidence">
        <p className="mt-2 max-w-2xl text-base leading-7 text-muted-foreground">
          Find your request receipts, provider operations and retained reservations. Source text and
          questions are excluded.
        </p>
      </PageHeader>
      {user?.role !== 'owner' ? (
        <Limits tone="neutral">Sign in as an owner to inspect your operations.</Limits>
      ) : (
        <>
          <label className="block text-sm font-semibold">
            Search request, incident or operation ID
            <Input
              className="mt-1"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <Button variant="outline" onClick={() => void report.refetch()}>
            Refresh evidence
          </Button>
          {report.isPending && <p role="status">Loading operational evidence…</p>}
          {report.error && <p role="alert">{report.error.message}</p>}
          {report.data && (
            <>
              <section className="space-y-4">
                <h2 className="border-t-2 border-foreground pt-3 text-xl font-bold font-stretch-semi-condensed">
                  Alerts requiring action
                </h2>
                {report.data.alerts.length ? (
                  report.data.alerts.map((alert, index) => (
                    <article
                      key={index}
                      className="rounded-sm border border-limit-border bg-limit p-4 text-limit-foreground"
                    >
                      <h3 className="text-base font-bold">
                        {alert.severity} · {alert.code}
                      </h3>
                      <p className="break-all font-mono text-xs">
                        {alert.operation_id ?? alert.request_id}
                      </p>
                      <p className="mt-2 text-sm">{alert.remediation}</p>
                      <a className="mt-2 inline-block text-xs underline" href="#operations-runbook">
                        Open response runbook
                      </a>
                    </article>
                  ))
                ) : (
                  <p>No alerts in this owner scope and receipt window.</p>
                )}
              </section>
              <section className="space-y-4">
                <h2 className="border-t-2 border-foreground pt-3 text-xl font-bold font-stretch-semi-condensed">
                  Durable AI operations
                </h2>
                <p className="text-sm">{report.data.recovery_policy}</p>
                {report.data.operations.map((operation) => (
                  <article key={operation.id} className="rounded-sm border bg-card p-4">
                    <h3 className="text-base font-bold">
                      {operation.task} · {operation.status}
                    </h3>
                    <p className="break-all text-xs">
                      Operation: {operation.id}
                      <br />
                      Request: {operation.request_id ?? 'Not recorded'}
                      <br />
                      Incident: {operation.incident_id ?? 'Not recorded'} · Analysis:{' '}
                      {operation.analysis_id}
                      <br />
                      Latency:{' '}
                      {operation.elapsed_seconds == null
                        ? 'Not terminal or not recorded'
                        : `${operation.elapsed_seconds}s`}
                    </p>
                    <details>
                      <summary className="mt-2 text-xs">Provider receipt identifiers</summary>
                      <pre className="overflow-x-auto text-xs">
                        {JSON.stringify(operation.provider_receipts, null, 2)}
                      </pre>
                    </details>
                  </article>
                ))}
              </section>
              <section className="space-y-4">
                <h2 className="border-t-2 border-foreground pt-3 text-xl font-bold font-stretch-semi-condensed">
                  Request receipts and import health
                </h2>
                <div className="overflow-x-auto rounded-sm border bg-card">
                  <table className="w-full text-left text-xs">
                    <caption className="sr-only">Actor-scoped request receipts</caption>
                    <thead>
                      <tr>
                        <th className="p-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Request ID
                        </th>
                        <th className="p-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Route
                        </th>
                        <th className="p-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Status
                        </th>
                        <th className="p-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Latency
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.data.events.map((event) => (
                        <tr key={event.request_id} className="border-t">
                          <td className="p-2 font-mono">{event.request_id}</td>
                          <td className="p-2">
                            {event.method} {event.route}
                          </td>
                          <td className="p-2">
                            {event.status_code} {event.failure_category}
                          </td>
                          <td className="p-2">{event.elapsed_seconds}s</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              <section className="space-y-4">
                <h2 className="border-t-2 border-foreground pt-3 text-xl font-bold font-stretch-semi-condensed">
                  Your allowance reservations
                </h2>
                {report.data.allowance_entries.map((entry) => (
                  <p className="break-all text-xs" key={entry.id}>
                    {entry.id} · {entry.operation} · {entry.status} · reserved ₹
                    {entry.reserved_inr.toFixed(2)} · charged ₹{entry.charged_inr.toFixed(2)}
                  </p>
                ))}
                <p className="mt-2 text-xs">
                  The shared ceiling is enforced when reserving paid calls; this view contains your
                  entries only.
                </p>
              </section>
              <section id="operations-runbook" className="space-y-4 rounded-sm border bg-card p-4">
                <h2 className="text-xl font-bold font-stretch-semi-condensed">Response runbook</h2>
                <p className="mt-2 text-sm">
                  For a failed request, search its ID in host logs and check readiness and the
                  deployed commit. For uncertain provider work, compare receipt IDs against provider
                  billing; retain the reservation until reconciliation. Use the deterministic
                  investigation while resolving failures. Escalate unresolved failures to the
                  application owner.
                </p>
              </section>
              <ul className="list-disc pl-5 text-xs">
                {report.data.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  )
}
