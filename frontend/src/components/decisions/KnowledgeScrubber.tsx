import { Button } from '@/components/ui/button'
import { formatInstant } from '@/lib/status'

export function KnowledgeScrubber({
  times,
  value,
  onChange,
}: {
  times: string[]
  value: number
  onChange: (index: number) => void
}) {
  const bounded = Math.max(0, Math.min(value, Math.max(0, times.length - 1)))
  const time = times[bounded]
  if (!time) return <p role="status">No knowledge times are available for this order.</p>
  return (
    <div className="space-y-3 rounded-sm border border-border bg-card p-4">
      <label htmlFor="knowledge-time-scrubber" className="block text-sm font-semibold">
        Knowledge-time cutoff
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={bounded === 0}
          aria-label="Earlier knowledge time"
          onClick={() => onChange(bounded - 1)}
        >
          Earlier
        </Button>
        <input
          id="knowledge-time-scrubber"
          type="range"
          min={0}
          max={times.length - 1}
          step={1}
          value={bounded}
          aria-label="Knowledge-time cutoff"
          aria-valuetext={formatInstant(time)}
          onChange={(event) => onChange(Number(event.target.value))}
          className="min-w-40 flex-1 accent-primary focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary"
        />
        <Button
          type="button"
          variant="outline"
          disabled={bounded >= times.length - 1}
          aria-label="Later knowledge time"
          onClick={() => onChange(bounded + 1)}
        >
          Later
        </Button>
      </div>
      <p aria-live="polite" className="font-mono text-sm">
        {formatInstant(time)}
      </p>
      <p className="text-xs text-muted-foreground">
        Use the arrow keys to move one event at a time. Home and End move to the earliest or latest
        knowledge time.
      </p>
    </div>
  )
}
