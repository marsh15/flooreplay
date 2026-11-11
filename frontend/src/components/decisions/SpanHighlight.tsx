import type { ReviewField } from '@/lib/decisions-types'

/** Evidence offsets in note signals count Unicode code points, not UTF-16 units. */
export function SpanHighlight({ text, fields }: { text: string; fields: ReviewField[] }) {
  const points = Array.from(text)
  const spans = fields
    .flatMap((field) => (field.span ? [{ ...field.span, field: field.name }] : []))
    .filter(
      (span) =>
        Number.isInteger(span.start) &&
        Number.isInteger(span.end) &&
        span.start >= 0 &&
        span.end <= points.length &&
        span.start < span.end &&
        points.slice(span.start, span.end).join('') === span.text,
    )
    .sort((left, right) => left.start - right.start || left.end - right.end)
  const parts: React.ReactNode[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start < cursor) continue
    if (span.start > cursor) parts.push(points.slice(cursor, span.start).join(''))
    parts.push(
      <mark
        key={`${span.field}:${span.start}:${span.end}`}
        data-highlight="true"
        className="rounded-sm bg-limit px-0.5 text-limit-foreground"
        title={`Evidence for ${span.field}`}
      >
        {points.slice(span.start, span.end).join('')}
      </mark>,
    )
    cursor = span.end
  }
  if (cursor < points.length) parts.push(points.slice(cursor).join(''))
  return <p className="whitespace-pre-wrap leading-7">{parts}</p>
}
