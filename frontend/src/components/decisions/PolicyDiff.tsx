import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { PolicyChange } from '@/lib/decisions-types'

function show(value: unknown) {
  if (value === null) return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

export function PolicyDiff({ changes }: { changes: PolicyChange[] }) {
  if (!changes.length) return <p className="text-sm text-muted-foreground">No parameter changes.</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Parameter</TableHead>
          <TableHead>Current</TableHead>
          <TableHead>Candidate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {changes.map((change) => (
          <TableRow key={change.path}>
            <TableCell className="font-mono text-xs">{change.path}</TableCell>
            <TableCell>{show(change.before)}</TableCell>
            <TableCell>{show(change.after)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
