import { Alert } from '@/components/ui/alert'
import { EvidenceList, StatusTag } from '@/components/board'
import type { GateResult, GateState } from '@/lib/decisions-types'

const LABEL: Record<GateState, string> = {
  READY: 'Evidence ready',
  STALE: 'Evidence stale',
  INCOMPLETE: 'Evidence incomplete',
  CONFLICTING: 'Conflicting evidence',
}

function tone(state: GateState) {
  if (state === 'READY') return 'success' as const
  if (state === 'CONFLICTING') return 'danger' as const
  return 'limit' as const
}

export function GateBanner({
  gate,
  onOpenFact,
}: {
  gate: GateResult
  onOpenFact: (id: string) => void
}) {
  return (
    <Alert
      variant={
        gate.state === 'CONFLICTING' ? 'destructive' : gate.state === 'READY' ? 'success' : 'limit'
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusTag tone={tone(gate.state)}>{LABEL[gate.state]}</StatusTag>
          <span className="font-mono text-xs">{gate.state}</span>
        </div>
        {gate.findings.length ? (
          <ul className="space-y-3" aria-label="Gate findings">
            {gate.findings.map((finding, index) => (
              <li
                key={`${finding.code}:${finding.entity_key}:${index}`}
                className="border-t border-border/70 pt-3"
              >
                <p className="font-semibold">{finding.code.replaceAll('_', ' ')}</p>
                <p className="mt-1">
                  <StatusTag tone={tone(finding.state)}>{LABEL[finding.state]}</StatusTag>
                </p>
                <p className="mt-1">{finding.detail}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Entity: <span className="font-mono">{finding.entity_key}</span>
                </p>
                {finding.rule_id && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Rule: <span className="font-mono">{finding.rule_id}</span>
                  </p>
                )}
                <div className="mt-2">
                  <EvidenceList ids={finding.fact_ids} onOpen={onOpenFact} />
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p>No gate findings. Required evidence is usable at this cutoff.</p>
        )}
      </div>
    </Alert>
  )
}
