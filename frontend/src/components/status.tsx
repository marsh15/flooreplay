/**
 * Status components. A badge never communicates by color alone: every one
 * carries its text label, and tones are restrained tints over the light
 * neutral surface.
 */

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { OUTCOME_META, VERDICT_META } from '@/lib/status'
import type { DomainOutcome, ExecutionLifecycle, Verdict } from '@/lib/api'

const TONES = {
  ready: 'bg-success text-success-foreground border-success-border',
  rejected: 'bg-danger text-danger-foreground border-danger-border font-semibold',
  blocked: 'bg-limit text-limit-foreground border-limit-border',
  abstain: 'bg-info text-info-foreground border-info-border',
  neutral: 'bg-secondary text-secondary-foreground border-border',
} as const

export function OutcomeBadge({
  outcome,
  className,
}: {
  outcome: DomainOutcome
  className?: string
}) {
  const meta = OUTCOME_META[outcome]
  return (
    <Badge
      variant="outline"
      className={cn('h-auto px-2 py-0.5 text-xs font-medium', TONES[meta.tone], className)}
    >
      {meta.label}
    </Badge>
  )
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const tone =
    verdict === 'PASS' ? TONES.ready : verdict === 'FAIL' ? TONES.rejected : TONES.neutral
  return (
    <Badge variant="outline" className={cn('h-auto px-2 py-0.5 text-xs font-medium', tone)}>
      {VERDICT_META[verdict].label}
    </Badge>
  )
}

export function ExpectationBadge({ verdict }: { verdict: 'PASS' | 'FAIL' | null }) {
  if (verdict === null) {
    return <span className="text-xs text-muted-foreground">No expectation pinned</span>
  }
  const tone = verdict === 'PASS' ? TONES.ready : TONES.rejected
  const label = verdict === 'PASS' ? 'Expectation pass' : 'Expectation fail'
  return (
    <Badge variant="outline" className={cn('h-auto px-2 py-0.5 text-xs font-medium', tone)}>
      {label}
    </Badge>
  )
}

export function LifecycleBadge({ lifecycle }: { lifecycle: ExecutionLifecycle }) {
  const label =
    lifecycle === 'COMPLETED'
      ? 'Completed'
      : lifecycle === 'RUNNING'
        ? 'Running'
        : lifecycle === 'ERRORED'
          ? 'Errored'
          : 'Interrupted'
  const tone = lifecycle === 'COMPLETED' ? TONES.neutral : TONES.blocked
  return (
    <Badge variant="outline" className={cn('h-auto px-2 py-0.5 text-xs font-medium', tone)}>
      {label}
    </Badge>
  )
}

export function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn('font-mono text-xs', className)}>{children}</span>
}
