import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import { Limits, PageHeader, Section, StatusTag } from '@/components/board'
import { SpanHighlight } from '@/components/decisions/SpanHighlight'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { listReviewItems, resolveReviewItem } from '@/lib/decisions'
import type { ReviewAction, ReviewItem } from '@/lib/decisions-types'
import { useAuth } from '@/components/Auth'
import { formatInstant } from '@/lib/status'

type FieldDraft = { value: string; evidence: string }

function ReviewCard({
  item,
  onResolve,
  pending,
}: {
  item: ReviewItem
  onResolve: (
    id: string,
    action: ReviewAction,
    reason: string,
    corrected?: Record<string, FieldDraft>,
  ) => void
  pending: boolean
}) {
  const [reason, setReason] = useState('')
  const [drafts, setDrafts] = useState<Record<string, FieldDraft>>(() =>
    Object.fromEntries(
      (item.fields ?? []).map((field) => [
        field.name,
        {
          value:
            typeof field.value === 'string'
              ? field.value
              : field.value == null
                ? ''
                : JSON.stringify(field.value),
          evidence: field.evidence ?? '',
        },
      ]),
    ),
  )
  const hasReason = reason.trim().length > 0
  const changedDrafts = Object.fromEntries(
    (item.fields ?? []).flatMap((field) => {
      const draft = drafts[field.name]
      const originalValue =
        typeof field.value === 'string'
          ? field.value
          : field.value == null
            ? ''
            : JSON.stringify(field.value)
      const originalEvidence = field.evidence ?? ''
      return draft && (draft.value !== originalValue || draft.evidence !== originalEvidence)
        ? [[field.name, draft] as const]
        : []
    }),
  )

  return (
    <article className="space-y-4 rounded-sm border border-border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold">{item.note_id ?? item.order_id ?? item.id}</h3>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {item.kind} · {item.id} · {formatInstant(item.created_at)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Assigned to: {item.assignee ?? 'Unassigned'}
          </p>
          {item.order_id ? (
            <Link
              className="mt-2 inline-flex underline underline-offset-2"
              to={`/orders/${encodeURIComponent(item.order_id)}`}
            >
              Open order {item.order_id}
            </Link>
          ) : null}
        </div>
        <StatusTag tone="limit">Needs review</StatusTag>
      </header>
      {item.note_text ? (
        <div className="rounded-sm border border-border bg-background px-3 py-2 text-sm">
          <SpanHighlight text={item.note_text} fields={item.fields ?? []} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No source note is attached to this item.</p>
      )}
      {item.fields?.length ? (
        <div className="space-y-4">
          {item.fields.map((field) => {
            const draft = drafts[field.name] ?? { value: '', evidence: '' }
            return (
              <section
                key={field.name}
                className="grid gap-3 border-t border-border pt-3 sm:grid-cols-2"
              >
                <div className="sm:col-span-2">
                  <h4 className="text-sm font-semibold">{field.name.replaceAll('_', ' ')}</h4>
                  <p className="mt-1 text-xs text-muted-foreground">Field status: {field.status}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Failed checks:{' '}
                    {field.failed_checks.length ? field.failed_checks.join(', ') : 'None recorded'}
                  </p>
                </div>
                <label className="space-y-1 text-sm font-medium">
                  Value for {field.name} in {item.id}
                  <Input
                    value={draft.value}
                    onChange={(event) => {
                      const value = event.currentTarget.value
                      setDrafts((current) => ({ ...current, [field.name]: { ...draft, value } }))
                    }}
                  />
                </label>
                <label className="space-y-1 text-sm font-medium">
                  Evidence for {field.name} in {item.id}
                  <Input
                    value={draft.evidence}
                    onChange={(event) => {
                      const evidence = event.currentTarget.value
                      setDrafts((current) => ({ ...current, [field.name]: { ...draft, evidence } }))
                    }}
                  />
                </label>
              </section>
            )
          })}
        </div>
      ) : null}
      <label
        className="block max-w-2xl space-y-1 text-sm font-medium"
        htmlFor={`reason-${item.id}`}
      >
        Reason for {item.id}
        <Input
          id={`reason-${item.id}`}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={!hasReason || pending}
          onClick={() => onResolve(item.id, 'confirm', reason)}
        >
          Confirm {item.id}
        </Button>
        <Button
          variant="secondary"
          disabled={!hasReason || pending || Object.keys(changedDrafts).length === 0}
          onClick={() => onResolve(item.id, 'correct', reason, changedDrafts)}
        >
          Correct {item.id}
        </Button>
        <Button
          variant="destructive"
          disabled={!hasReason || pending}
          onClick={() => onResolve(item.id, 'reject', reason)}
        >
          Reject {item.id}
        </Button>
      </div>
    </article>
  )
}

export function ReviewQueue() {
  const { epoch } = useAuth()
  const client = useQueryClient()
  const [notice, setNotice] = useState('')
  const items = useQuery({
    queryKey: ['decisions', 'review-items', epoch],
    queryFn: listReviewItems,
  })
  const resolveMutation = useMutation({
    mutationFn: ({
      id,
      action,
      reason,
      corrected,
    }: {
      id: string
      action: ReviewAction
      reason: string
      corrected?: Record<string, FieldDraft>
    }) =>
      resolveReviewItem(id, {
        action,
        reason: reason.trim(),
        ...(action === 'correct' && corrected
          ? {
              corrected: Object.fromEntries(
                Object.entries(corrected).map(([name, field]) => [
                  name,
                  {
                    value: field.value.trim() ? field.value : null,
                    evidence: field.evidence.trim() ? field.evidence : null,
                  },
                ]),
              ),
            }
          : {}),
      }),
    onSuccess: async () => {
      setNotice('Review action recorded.')
      await client.invalidateQueries({ queryKey: ['decisions', 'review-items'] })
    },
    onError: () => setNotice('The review action could not be recorded. Try again.'),
  })

  return (
    <div className="space-y-8">
      <PageHeader title="Review queue">
        <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
          Check extracted evidence against the original note. Confirm, correct, or reject each item
          with a reason.
        </p>
      </PageHeader>
      <Section
        title="Items needing review"
        detail="Evidence spans point to exact source text, including Tamil and Tanglish notes."
      >
        {items.isPending ? <p role="status">Loading review items…</p> : null}
        {items.isError ? (
          <Limits tone="danger">Review items are unavailable. Try again later.</Limits>
        ) : null}
        {items.data?.items.length === 0 ? (
          <div role="status" className="rounded-sm border border-border bg-card p-5">
            <h3 className="font-semibold">No items need review</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              New extraction and decision items will appear here.
            </p>
          </div>
        ) : null}
        {items.data?.items.length ? (
          <div className="space-y-4">
            {items.data.items.map((item) => (
              <ReviewCard
                key={item.id}
                item={item}
                pending={resolveMutation.isPending}
                onResolve={(id, action, reason, corrected) => {
                  setNotice('')
                  resolveMutation.mutate({ id, action, reason, corrected })
                }}
              />
            ))}
          </div>
        ) : null}
        {notice ? (
          <p role="status" className="mt-3 text-sm">
            {notice}
          </p>
        ) : null}
      </Section>
    </div>
  )
}
