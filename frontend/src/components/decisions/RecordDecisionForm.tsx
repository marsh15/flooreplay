import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StatusTag } from '@/components/board'
import type { Outcome } from '@/lib/decisions-types'

const OUTCOMES: Outcome[] = ['ACCEPT', 'ACCEPT_WITH_CONDITIONS', 'DECLINE', 'NEEDS_REVIEW']

export function RecordDecisionForm({
  engineOutcome,
  onSubmit,
  busy = false,
  success = '',
}: {
  engineOutcome: Outcome
  onSubmit: (finalOutcome: Outcome, reason: string) => void
  busy?: boolean
  success?: string
}) {
  const [outcome, setOutcome] = useState<Outcome>(engineOutcome)
  const [reason, setReason] = useState('')
  const trimmed = reason.trim()
  const override = outcome !== engineOutcome
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (trimmed) onSubmit(outcome, trimmed)
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label htmlFor="final-outcome" className="mb-1 block text-sm font-semibold">
          Final decision
        </label>
        <select
          id="final-outcome"
          value={outcome}
          onChange={(event) => setOutcome(event.target.value as Outcome)}
          className="h-10 w-full rounded-sm border border-input bg-card px-2 text-sm focus-visible:outline-2 focus-visible:outline-primary"
        >
          {OUTCOMES.map((option) => (
            <option key={option} value={option}>
              {option.replaceAll('_', ' ')}
            </option>
          ))}
        </select>
      </div>
      {override && (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <StatusTag tone="limit">Human override</StatusTag>
          <span>Engine recommended {engineOutcome.replaceAll('_', ' ')}.</span>
        </p>
      )}
      <div>
        <label htmlFor="decision-reason" className="mb-1 block text-sm font-semibold">
          Reason for this decision
        </label>
        <Input
          id="decision-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          required
          aria-describedby="decision-reason-help"
        />
        <p id="decision-reason-help" className="mt-1 text-xs text-muted-foreground">
          Record the evidence or business reason behind the final call.
        </p>
      </div>
      {success && (
        <p role="status" className="text-sm">
          {success}
        </p>
      )}
      <Button type="submit" disabled={busy || trimmed.length === 0}>
        {busy ? 'Recording…' : 'Record final decision'}
      </Button>
    </form>
  )
}
