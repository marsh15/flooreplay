import type { IncidentMetric, IncidentRevision } from '@/lib/incidents'
import { formatClock } from '@/lib/status'
import { cn } from '@/lib/utils'

interface Interval {
  start: string
  end: string
  plan: number | null
  recorded: number | null
  openId: string | null
  counted: boolean
  reason: string | null
}

const num = (value: unknown) => (typeof value === 'number' ? value : null)
const str = (value: unknown) => (typeof value === 'string' ? value : null)

/** Build one row per planned interval from the revision, marking what the report counted. */
function intervals(incident: IncidentRevision, metric: IncidentMetric): Interval[] {
  const counted = new Map((metric.inputs ?? []).map((input) => [input.start, input]))
  const outputs = new Map<string, IncidentRevision['output_buckets'][number]>()
  for (const bucket of incident.output_buckets) {
    const start = str(bucket.start)
    if (start) outputs.set(start, bucket)
  }
  const planned = incident.plan_buckets
    .map((bucket) => ({ bucket, start: str(bucket.start), end: str(bucket.end) }))
    .filter((item): item is { bucket: typeof item.bucket; start: string; end: string } =>
      Boolean(item.start && item.end),
    )
    .sort((a, b) => a.start.localeCompare(b.start))
  if (planned.length === 0) {
    return (metric.inputs ?? []).map((input) => ({
      start: input.start,
      end: input.end,
      plan: input.plan.quantity,
      recorded: input.output.quantity,
      openId: input.output.id,
      counted: true,
      reason: null,
    }))
  }
  const cutoff = new Date(incident.cutoff).getTime()
  return planned.map(({ bucket, start, end }) => {
    const input = counted.get(start)
    if (input) {
      return {
        start,
        end,
        plan: input.plan.quantity,
        recorded: input.output.quantity,
        openId: input.output.id,
        counted: true,
        reason: null,
      }
    }
    // Records that arrived after the cutoff must not be shown as part of this report.
    const reason =
      new Date(end).getTime() > cutoff
        ? 'The interval ends after the evidence cutoff.'
        : outputs.has(start)
          ? 'The interval was not comparable in this report.'
          : 'No output record was available at the cutoff.'
    return {
      start,
      end,
      plan: num(bucket.quantity),
      recorded: null,
      openId: bucket.id,
      counted: false,
      reason,
    }
  })
}

/**
 * Planned against recorded good output for each 15-minute interval, drawn from the
 * incident's own records. Intervals that could not be compared stay visibly uncounted;
 * missing output is never plotted as zero.
 */
export function BucketStrip({
  incident,
  metric,
  onOpen,
}: {
  incident: IncidentRevision
  metric: IncidentMetric
  onOpen: (id: string) => void
}) {
  const rows = intervals(incident, metric)
  if (rows.length === 0) return null
  const unit = metric.unit.replaceAll('_', ' ')
  const scale = Math.max(1, ...rows.flatMap((row) => [row.plan ?? 0, row.recorded ?? 0]))
  const uncounted = rows.filter((row) => !row.counted)
  return (
    <div className="rounded-sm border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-base font-bold font-stretch-semi-condensed">
          Plan and recorded output by 15-minute interval
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Each column opens its source record. Intervals that cannot be compared are marked not
          counted, never shown as zero.
        </p>
      </div>
      <div className="overflow-x-auto px-4 pt-4 pb-3">
        <ol className="flex min-w-[40rem] items-stretch gap-1.5">
          {rows.map((row) => {
            const planPct = row.plan == null ? null : (row.plan / scale) * 100
            const recordedPct = row.recorded == null ? null : (row.recorded / scale) * 100
            const label = row.counted
              ? `${formatClock(row.start)} to ${formatClock(row.end)}: recorded ${row.recorded} of ${row.plan} planned ${unit}`
              : `${formatClock(row.start)} to ${formatClock(row.end)}: not counted. ${row.reason}`
            return (
              <li key={row.start} className="min-w-0 flex-1">
                <button
                  type="button"
                  disabled={!row.openId}
                  aria-label={`${label}${row.openId ? `. Open source ${row.openId}` : ''}`}
                  onClick={() => row.openId && onOpen(row.openId)}
                  className="group flex w-full flex-col rounded-sm text-center focus-visible:outline-2"
                >
                  <span
                    className={cn(
                      'relative block h-40 w-full overflow-hidden rounded-sm border',
                      row.counted
                        ? 'border-transparent bg-secondary group-hover:bg-accent'
                        : 'border-dashed border-input bg-card',
                    )}
                  >
                    {row.counted &&
                      planPct != null &&
                      recordedPct != null &&
                      planPct > recordedPct && (
                        <span
                          aria-hidden="true"
                          className="absolute inset-x-0 border-y border-limit-border bg-limit"
                          style={{ bottom: `${recordedPct}%`, height: `${planPct - recordedPct}%` }}
                        />
                      )}
                    {row.counted && recordedPct != null && (
                      <span
                        aria-hidden="true"
                        className="absolute inset-x-1.5 bottom-0 bg-primary"
                        style={{ height: `${recordedPct}%` }}
                      />
                    )}
                    {planPct != null && (
                      <span
                        aria-hidden="true"
                        className="absolute inset-x-0 h-0.5 translate-y-0.5 bg-foreground"
                        style={{ bottom: `${planPct}%` }}
                      />
                    )}
                  </span>
                  <span className="mt-1.5 block text-xs font-semibold text-foreground tabular-nums">
                    {formatClock(row.start)}
                  </span>
                  <span className="block text-sm font-bold text-foreground tabular-nums">
                    {row.counted ? `${row.recorded} / ${row.plan}` : 'Not counted'}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1 border-t border-border px-4 py-3 text-xs text-muted-foreground">
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="size-3 bg-primary" />
          Bar: recorded good output
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="h-0.5 w-4 bg-foreground" />
          Line: baseline plan
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="size-3 border border-limit-border bg-limit" />
          Amber: shortfall within the interval
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden="true" className="size-3 border border-dashed border-input" />
          Dashed: not counted
        </li>
        <li>Figures read recorded / planned {unit}.</li>
      </ul>
      {uncounted.length > 0 && (
        <ul className="space-y-1 border-t border-border px-4 py-3 text-sm text-foreground">
          {uncounted.map((row) => (
            <li key={row.start}>
              <span className="font-semibold tabular-nums">
                {formatClock(row.start)} to {formatClock(row.end)}
              </span>{' '}
              not counted. {row.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
