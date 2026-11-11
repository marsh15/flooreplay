import { StatusTag } from '@/components/board'
import { formatInstant } from '@/lib/status'
import type { GateState } from '@/lib/decisions-types'

function ageAtCutoff(observed: string, cutoff: string) {
  const milliseconds = new Date(cutoff).getTime() - new Date(observed).getTime()
  if (!Number.isFinite(milliseconds)) return null
  if (milliseconds < 0) return 'effective after this cutoff'
  const minutes = Math.floor(milliseconds / 60_000)
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const remainder = minutes % 60
  if (days) return `${days}d ${hours}h before cutoff`
  if (hours) return `${hours}h ${remainder}m before cutoff`
  return `${remainder}m before cutoff`
}

export function FreshnessBadge({
  factId,
  source,
  validFrom,
  cutoff,
  gateState,
}: {
  factId: string
  source: string
  validFrom: string
  cutoff: string
  gateState: GateState
}) {
  const age = ageAtCutoff(validFrom, cutoff)
  const tone = gateState === 'READY' ? 'success' : gateState === 'CONFLICTING' ? 'danger' : 'limit'
  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-xs">
      <StatusTag tone={tone}>Gate: {gateState}</StatusTag>
      <span>
        <span className="font-mono">{factId}</span> · {source} · observed {formatInstant(validFrom)}
        {age ? ` · ${age}` : ''}
      </span>
    </span>
  )
}
