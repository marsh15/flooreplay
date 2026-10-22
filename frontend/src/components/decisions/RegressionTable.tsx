import { StatusTag } from '@/components/board'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { RegressionRun } from '@/lib/decisions-types'

export function RegressionTable({ run }: { run: RegressionRun }) {
  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Case</TableHead>
            <TableHead>Baseline verdict</TableHead>
            <TableHead>Candidate verdict</TableHead>
            <TableHead>Classification</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {run.cases.map((item) => (
            <TableRow key={item.case_id}>
              <TableCell>
                <span className="block font-medium">{item.title}</span>
                <span className="font-mono text-xs text-muted-foreground">{item.case_id}</span>
              </TableCell>
              <TableCell>{item.baseline}</TableCell>
              <TableCell>{item.candidate ?? 'Not evaluated'}</TableCell>
              <TableCell>
                <StatusTag
                  tone={
                    item.classification === 'REGRESSION'
                      ? 'danger'
                      : item.classification === 'FIXED'
                        ? 'success'
                        : 'neutral'
                  }
                >
                  {item.classification.replaceAll('_', ' ')}
                </StatusTag>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="mt-3 font-mono text-xs text-muted-foreground">
        {run.complete ? 'Complete stored run' : 'Run is incomplete'} · suite {run.suite_digest} ·
        engine {run.engine_version}
      </p>
    </div>
  )
}
