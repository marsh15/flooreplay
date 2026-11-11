import { useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatInstant } from '@/lib/status'
import type { FactView } from '@/lib/decisions-types'

function chainFor(selectedId: string, facts: FactView[]) {
  const byId = new Map(facts.map((fact) => [fact.id, fact]))
  const selected = byId.get(selectedId)
  if (!selected) return []
  const connected = new Set([selected.id])
  let changed = true
  while (changed) {
    changed = false
    for (const fact of facts) {
      if (
        (fact.supersedes_id && connected.has(fact.supersedes_id)) ||
        (fact.supersedes_id && connected.has(fact.id))
      ) {
        if (!connected.has(fact.id)) {
          connected.add(fact.id)
          changed = true
        }
        if (fact.supersedes_id && !connected.has(fact.supersedes_id)) {
          connected.add(fact.supersedes_id)
          changed = true
        }
      }
    }
  }
  return [...connected]
    .map((id) => byId.get(id))
    .filter((fact): fact is FactView => Boolean(fact))
    .sort(
      (left, right) =>
        left.known_at.localeCompare(right.known_at) || left.id.localeCompare(right.id),
    )
}

export function FactDrawer({
  factId,
  facts,
  onClose,
}: {
  factId: string | null
  facts: FactView[]
  onClose: () => void
}) {
  const fact = facts.find((item) => item.id === factId)
  const chain = useMemo(() => (factId ? chainFor(factId, facts) : []), [factId, facts])
  useEffect(() => {
    if (factId) document.querySelector<HTMLElement>('[data-slot="dialog-title"]')?.focus()
  }, [factId])
  return (
    <Dialog
      open={factId !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className="max-h-[85dvh] overflow-y-auto rounded-sm sm:max-w-2xl"
        aria-describedby="fact-drawer-description"
      >
        <DialogHeader>
          <DialogTitle tabIndex={-1}>Fact details</DialogTitle>
          <DialogDescription id="fact-drawer-description">
            Source record and its valid-time and knowledge-time history.
          </DialogDescription>
        </DialogHeader>
        {fact ? (
          <div className="space-y-5">
            <dl className="grid min-w-0 gap-x-5 gap-y-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="font-semibold">Fact ID</dt>
                <dd className="break-all font-mono text-xs">{fact.id}</dd>
              </div>
              <div>
                <dt className="font-semibold">Kind</dt>
                <dd>{fact.kind}</dd>
              </div>
              <div>
                <dt className="font-semibold">Entity</dt>
                <dd className="break-all font-mono text-xs">{fact.entity_key}</dd>
              </div>
              <div>
                <dt className="font-semibold">Source</dt>
                <dd>{fact.source}</dd>
              </div>
              <div>
                <dt className="font-semibold">Valid from</dt>
                <dd>{formatInstant(fact.valid_from)}</dd>
              </div>
              <div>
                <dt className="font-semibold">Valid to</dt>
                <dd>{fact.valid_to ? formatInstant(fact.valid_to) : 'Open interval'}</dd>
              </div>
              <div>
                <dt className="font-semibold">Known at</dt>
                <dd>{formatInstant(fact.known_at)}</dd>
              </div>
              <div>
                <dt className="font-semibold">Source artifact</dt>
                <dd className="break-all font-mono text-xs">{fact.artifact_id ?? 'Not linked'}</dd>
              </div>
            </dl>
            <section aria-labelledby="fact-payload-heading" className="space-y-2">
              <h3
                id="fact-payload-heading"
                className="border-t-2 border-foreground pt-3 font-semibold"
              >
                Payload
              </h3>
              <pre className="overflow-x-auto rounded-sm border border-border bg-muted/40 p-3 font-mono text-xs leading-5">
                {JSON.stringify(fact.payload, null, 2)}
              </pre>
            </section>
            <section aria-labelledby="supersession-heading" className="space-y-2">
              <h3
                id="supersession-heading"
                className="border-t-2 border-foreground pt-3 font-semibold"
              >
                Supersession chain
              </h3>
              {chain.length > 0 ? (
                <ol className="space-y-2">
                  {chain.map((item) => (
                    <li
                      key={item.id}
                      className="flex flex-wrap items-center gap-2 border-b border-border pb-2 text-sm"
                    >
                      <span className="font-mono text-xs">{item.id}</span>
                      <span>{formatInstant(item.known_at)}</span>
                      {item.id === fact.id && <strong>(selected)</strong>}
                      {item.supersedes_id && (
                        <span>
                          Supersedes <span className="font-mono text-xs">{item.supersedes_id}</span>
                        </span>
                      )}
                      {chain.some((candidate) => candidate.supersedes_id === item.id) && (
                        <span>Superseded by a later fact in this chain</span>
                      )}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No linked supersession history is available.
                </p>
              )}
            </section>
          </div>
        ) : (
          <p role="status">This fact is unavailable in the current snapshot.</p>
        )}
        <div className="flex justify-end">
          <Button variant="outline" onClick={onClose}>
            Close fact details
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
