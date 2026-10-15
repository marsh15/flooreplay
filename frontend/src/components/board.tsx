/**
 * Production-board primitives shared across screens: ruled sections, evidence
 * ID chips, status tags, limit callouts, ledger figures and form controls.
 * Every status carries its own text; color only supplements it.
 */

import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function sectionId(title: string) {
  return title.toLowerCase().replaceAll(/[^a-z0-9]+/g, '-')
}

export function PageHeader({
  title,
  children,
  actions,
  className,
}: {
  title: ReactNode
  children?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <header className={cn('border-b-2 border-foreground pb-5', className)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="max-w-3xl text-3xl leading-tight font-bold font-stretch-semi-condensed sm:text-4xl">
            {title}
          </h1>
          {children}
        </div>
        {actions}
      </div>
    </header>
  )
}

export function Section({
  title,
  detail,
  children,
  className,
}: {
  title: string
  detail?: string
  children: ReactNode
  className?: string
}) {
  return (
    <section id={sectionId(title)} className={cn('scroll-mt-16 space-y-5', className)}>
      <div className="border-t-2 border-foreground pt-3">
        <h2 className="text-xl font-bold font-stretch-semi-condensed">{title}</h2>
        {detail && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{detail}</p>}
      </div>
      {children}
    </section>
  )
}

export function EvidenceLink({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(id)}
      className="evidence-link inline-flex items-center rounded-sm border border-input bg-card px-1.5 py-0.5 font-mono text-xs text-foreground underline-offset-2 hover:underline focus-visible:outline-2"
    >
      {id}
    </button>
  )
}

export function EvidenceList({ ids, onOpen }: { ids: string[]; onOpen: (id: string) => void }) {
  return ids.length ? (
    <span className="flex flex-wrap gap-1">
      {ids.map((id) => (
        <EvidenceLink key={id} id={id} onOpen={onOpen} />
      ))}
    </span>
  ) : (
    <span className="text-xs text-muted-foreground">None recorded</span>
  )
}

export type Tone = 'neutral' | 'limit' | 'danger' | 'success' | 'info'

const TAG_TONES: Record<Tone, string> = {
  neutral: 'border-border bg-secondary text-secondary-foreground',
  limit: 'border-limit-border bg-limit text-limit-foreground',
  danger: 'border-danger-border bg-danger text-danger-foreground',
  success: 'border-success-border bg-success text-success-foreground',
  info: 'border-info-border bg-info text-info-foreground',
}

export function StatusTag({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-sm border px-2 py-0.5 text-xs font-semibold',
        TAG_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Evidence limits and cautions, shown inline and never collapsed. */
export function Limits({
  tone = 'limit',
  children,
  className,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('rounded-sm border px-3 py-2 text-sm', TAG_TONES[tone], className)}>
      {children}
    </div>
  )
}

/** One cell of a ruled ledger row: a label, a figure and its unit or status text. */
export function BoardStat({
  label,
  value,
  note,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: Tone
}) {
  const limit = tone === 'limit'
  return (
    <div className={cn('px-5 py-4', limit && 'bg-limit')}>
      <dt
        className={cn(
          'text-sm font-medium',
          limit ? 'text-limit-foreground' : 'text-muted-foreground',
        )}
      >
        {label}
      </dt>
      <dd className="mt-2 flex flex-wrap items-baseline gap-x-2">
        <span
          className={cn(
            'text-5xl leading-none font-bold font-stretch-semi-condensed tabular-nums',
            limit && 'text-limit-foreground',
          )}
        >
          {value}
        </span>
        {note && (
          <span
            className={cn('text-sm', limit ? 'text-limit-foreground' : 'text-muted-foreground')}
          >
            {note}
          </span>
        )}
      </dd>
    </div>
  )
}

export function NativeSelect({ className, ...props }: ComponentProps<'select'>) {
  return (
    <select
      className={cn(
        'h-10 rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-2',
        className,
      )}
      {...props}
    />
  )
}

export function FieldLabel({ className, ...props }: ComponentProps<'label'>) {
  return (
    <label
      className={cn('mb-1 block text-sm font-medium text-muted-foreground', className)}
      {...props}
    />
  )
}
