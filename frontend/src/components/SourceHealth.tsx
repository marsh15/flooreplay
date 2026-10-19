import { EvidenceLink, StatusTag, type Tone } from '@/components/board'
import type { FeedStatus, SourceHealth } from '@/lib/incidents'
import { formatClock, formatInstant } from '@/lib/status'

const FEED: Record<FeedStatus, { label: string; tone: Tone }> = {
  REPORTED: { label: 'Reported', tone: 'neutral' },
  AWAITING: { label: 'Awaiting record', tone: 'info' },
  GAP: { label: 'Skipped by feed', tone: 'limit' },
  CONFLICTING: { label: 'Conflicting records', tone: 'danger' },
  NOT_DUE: { label: 'Not yet due', tone: 'neutral' },
}

function feedDetail(entry: SourceHealth['production_feed']['intervals'][number]) {
  if (entry.status === 'AWAITING')
    return `Due ${entry.minutes_since_due} min before the cutoff${entry.overdue ? '; later than the usual delay' : ''}`
  if (entry.status === 'GAP')
    return 'A later interval was reported, so this record is missing rather than delayed'
  return null
}

export function SourceHealthPanel({
  health,
  onOpen,
}: {
  health: SourceHealth
  onOpen: (id: string) => void
}) {
  const feed = health.production_feed
  const due = feed.intervals.filter((entry) => entry.status !== 'NOT_DUE')
  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-sm leading-6">{health.summary}</p>
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">Latest output record</dt>
          <dd className="tabular-nums">
            {feed.latest_available_at
              ? `${formatInstant(feed.latest_available_at)} · ${feed.minutes_since_latest_record} min before cutoff`
              : 'None at this cutoff'}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Usual delay after interval end</dt>
          <dd className="tabular-nums">
            {feed.typical_delay_minutes === null
              ? 'Unknown'
              : `${feed.typical_delay_minutes} min (median)`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Expected cadence</dt>
          <dd className="tabular-nums">Every {feed.expected_interval_minutes} min</dd>
        </div>
      </dl>
      {due.length > 0 && (
        <div className="overflow-x-auto rounded-sm border border-border bg-card">
          <table className="w-full min-w-[560px] text-left text-sm">
            <caption className="sr-only">Output feed status for each due planned interval</caption>
            <thead className="border-b bg-secondary text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-2">
                  Interval
                </th>
                <th scope="col" className="px-4 py-2 text-right">
                  Plan
                </th>
                <th scope="col" className="px-4 py-2 text-right">
                  Reported
                </th>
                <th scope="col" className="px-4 py-2">
                  Feed
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {due.map((entry) => (
                <tr key={entry.plan_id}>
                  <td className="whitespace-nowrap px-4 py-2 tabular-nums">
                    {formatClock(entry.start)}–{formatClock(entry.end)}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{entry.planned}</td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {entry.reported ?? <span className="text-muted-foreground">No record</span>}
                  </td>
                  <td className="px-4 py-2">
                    <StatusTag tone={FEED[entry.status].tone}>{FEED[entry.status].label}</StatusTag>
                    {entry.output_id && (
                      <span className="ml-2">
                        <EvidenceLink id={entry.output_id} onOpen={onOpen} />
                      </span>
                    )}
                    {entry.output_ids?.map((id) => (
                      <span key={id} className="ml-2">
                        <EvidenceLink id={id} onOpen={onOpen} />
                      </span>
                    ))}
                    {feedDetail(entry) && (
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {feedDetail(entry)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {health.operations_feed.late_record_ids.length > 0 && (
        <p className="text-sm">
          Became available more than {health.operations_feed.late_threshold_minutes} minutes after
          they happened:{' '}
          {health.operations_feed.late_record_ids.map((id) => (
            <span key={id} className="mr-1">
              <EvidenceLink id={id} onOpen={onOpen} />
            </span>
          ))}
        </p>
      )}
      {health.conflicts.correction_conflicts.length > 0 && (
        <p className="text-sm text-danger-foreground">
          {health.conflicts.correction_conflicts.length} record
          {health.conflicts.correction_conflicts.length === 1 ? ' has' : 's have'} more than one
          correction.
        </p>
      )}
      {health.imports.length > 0 && (
        <details>
          <summary className="cursor-pointer py-1 text-sm font-medium">
            Published imports ({health.imports.length})
          </summary>
          <ul className="mt-2 space-y-1 text-sm">
            {health.imports.map((item) => (
              <li key={`${item.revision}-${item.filename}`} className="tabular-nums">
                Revision {item.revision} · {item.source_system} · {item.filename}
                {item.rows !== null ? ` · ${item.rows} rows` : ''} ·{' '}
                {formatInstant(item.published_at)}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-muted-foreground">{health.rejections.reason}</p>
    </div>
  )
}
