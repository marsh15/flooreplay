/**
 * Evidence drawer: opens the pinned snapshot and highlights the exact
 * source row an issue or constraint points at. Raw text is rendered as
 * text; nothing from an import is ever interpreted.
 */

import { useQuery } from '@tanstack/react-query'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { api, type EvidenceRef } from '@/lib/api'
import { formatInstant } from '@/lib/status'
import { Mono } from '@/components/status'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const ROW_KEYS: Record<string, string> = {
  ATTENDANCE: 'attendance',
  ASSIGNMENTS: 'assignments',
  SKILLS: 'skills',
  MACHINE_STATE: 'machine_state',
}

const COLUMNS: Record<string, string[]> = {
  ATTENDANCE: ['operator_id', 'status', 'observed_at', 'source_ref'],
  ASSIGNMENTS: ['operator_id', 'slot_id', 'machine_id', 'starts_at', 'ends_at', 'source_ref'],
  SKILLS: ['operator_id', 'operation_id', 'level', 'assessed_at', 'source_ref'],
  MACHINE_STATE: ['machine_id', 'usable', 'observed_at', 'detail', 'source_ref'],
}

export function EvidenceDrawer({
  evidence,
  open,
  onOpenChange,
}: {
  evidence: EvidenceRef | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['snapshot', evidence?.snapshot_id],
    queryFn: () => api.snapshot(evidence!.snapshot_id),
    enabled: open && evidence !== null && evidence.snapshot_id !== 'event',
  })

  const isEvent = evidence?.snapshot_id === 'event'
  const rowsKey = data ? ROW_KEYS[data.kind] : undefined
  const rows = data && rowsKey ? ((data.payload[rowsKey] as Record<string, unknown>[]) ?? []) : []
  const columns = data ? (COLUMNS[data.kind] ?? []) : []

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="font-mono text-sm">
            {evidence ? evidence.snapshot_id : ''}
          </SheetTitle>
          <SheetDescription>
            {isEvent
              ? 'Confirmed episode event. This is the reviewed, human-confirmed record, not a raw model draft.'
              : data
                ? `${data.kind.toLowerCase().replace('_', ' ')} snapshot · ${data.source_system}`
                : 'Pinned source snapshot'}
          </SheetDescription>
        </SheetHeader>

        {isPending && !isEvent ? (
          <div className="space-y-2 px-4">
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-5/6" />
          </div>
        ) : isError ? (
          <p className="px-4 text-sm text-red-700">
            Snapshot could not be loaded: {error.message}
          </p>
        ) : isEvent ? (
          <div className="px-4 text-sm">
            <p className="text-muted-foreground">
              This evidence reference points at the confirmed unavailability event pinned to the
              scenario revision, not a snapshot row.
            </p>
          </div>
        ) : data ? (
          <div className="space-y-4 px-4 pb-8">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
              <dt className="text-muted-foreground">Scope</dt>
              <dd>{data.scope}</dd>
              <dt className="text-muted-foreground">Evidence time</dt>
              <dd>{formatInstant(data.declared_evidence_at)}</dd>
              <dt className="text-muted-foreground">Coverage</dt>
              <dd>{data.coverage_complete ? 'Complete (source asserts no missing rows)' : 'Incomplete'}</dd>
              <dt className="text-muted-foreground">Digest</dt>
              <dd>
                <Mono className="break-all">{data.content_digest}</Mono>
              </dd>
            </dl>

            {rows.length > 0 ? (
              <div className="rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {columns.map((column) => (
                        <TableHead key={column} className="text-xs">
                          {column}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row, index) => {
                      const highlighted =
                        evidence?.source_ref != null && row.source_ref === evidence.source_ref
                      return (
                        <TableRow
                          key={index}
                          className={highlighted ? 'bg-amber-500/15' : undefined}
                        >
                          {columns.map((column) => (
                            <TableCell key={column} className="px-2 py-1.5 text-xs">
                              {column === 'source_ref' ? (
                                <Mono>{String(row[column] ?? '')}</Mono>
                              ) : (
                                String(row[column] ?? '')
                              )}
                            </TableCell>
                          ))}
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <pre className="overflow-x-auto rounded-lg border bg-zinc-50 p-3 font-mono text-xs">
                {JSON.stringify(data.payload.plan ?? data.payload, null, 2)}
              </pre>
            )}
            {rows.length > 0 && evidence?.source_ref == null && evidence?.field ? (
              <p className="text-xs text-muted-foreground">
                Referenced field: <Mono>{evidence.field}</Mono>
              </p>
            ) : null}
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
