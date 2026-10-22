import { EvidenceList, StatusTag } from '@/components/board'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ConstraintResult } from '@/lib/decisions-types'

const STATUS_LABEL = { PASS: 'Pass', FAIL: 'Fail', NOT_EVALUATED: 'Not evaluated' } as const

export function ConstraintCard({
  result,
  onOpenFact,
}: {
  result: ConstraintResult
  onOpenFact: (id: string) => void
}) {
  const tone = result.status === 'PASS' ? 'success' : result.status === 'FAIL' ? 'danger' : 'limit'
  return (
    <Card className="min-w-0 rounded-sm border-border shadow-none">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <CardTitle className="font-stretch-semi-condensed">{result.constraint}</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">{result.subject}</p>
        </div>
        <StatusTag tone={tone}>{STATUS_LABEL[result.status]}</StatusTag>
      </CardHeader>
      <CardContent className="space-y-4 p-4 pt-0">
        {result.steps.length ? (
          <div
            className="overflow-x-auto rounded-sm border border-border"
            tabIndex={0}
            aria-label={`${result.constraint} arithmetic steps`}
          >
            <table className="w-full min-w-[32rem] text-left text-sm">
              <thead className="bg-muted/60 text-xs">
                <tr>
                  <th scope="col" className="p-2">
                    Step
                  </th>
                  <th scope="col" className="p-2">
                    Calculation
                  </th>
                  <th scope="col" className="p-2">
                    Value
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.steps.map((step, index) => (
                  <tr key={`${step.label}-${index}`} className="border-t border-border align-top">
                    <th scope="row" className="p-2 font-medium">
                      {step.label}
                    </th>
                    <td className="max-w-[34rem] p-2 font-mono text-xs whitespace-normal break-words">
                      {step.expression}
                    </td>
                    <td className="p-2 font-mono tabular-nums">{step.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No arithmetic was evaluated.</p>
        )}
        <p className="text-sm leading-6">{result.detail}</p>
        {result.consumed_by.length > 0 && (
          <p className="text-sm">
            <span className="font-semibold">Consumed by:</span> {result.consumed_by.join(', ')}
          </p>
        )}
        {result.pending_review_fact_ids.length > 0 && (
          <div>
            <p className="mb-1 text-sm font-semibold">Pending review evidence</p>
            <EvidenceList ids={result.pending_review_fact_ids} onOpen={onOpenFact} />
          </div>
        )}
        <div>
          <p className="mb-1 text-sm font-semibold">Evidence</p>
          <EvidenceList ids={result.fact_ids} onOpen={onOpenFact} />
        </div>
      </CardContent>
    </Card>
  )
}
