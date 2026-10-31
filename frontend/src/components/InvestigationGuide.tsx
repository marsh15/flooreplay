import type { AnalysisReport } from '@/lib/incidents'
import { StatusTag, type Tone } from '@/components/board'

type Link = { label: string; href: string }
type Step = {
  title: string
  href?: string
  extra?: Link[]
  status: string
  tone: Tone
  next: string
}

const words = (value: string) => value.replaceAll('_', ' ').toLowerCase()
const count = (value: number, noun: string) => `${value} ${noun}${value === 1 ? '' : 's'}`

/**
 * Five-step guide to the workbench. Each step states its current status from the
 * pinned report and links to the section that does the work. It only reads props,
 * so it adds no requests and no dashboard of its own.
 */
export function InvestigationGuide({
  report,
  viewedRevision,
  latestRevision,
  earlierRevision,
  compareAvailable,
  exportAvailable,
}: {
  report: AnalysisReport
  viewedRevision: number
  latestRevision: number
  earlierRevision: number | undefined
  compareAvailable: boolean
  exportAvailable: boolean
}) {
  const saved = report.execution_kind === 'saved_deterministic'
  const { metrics } = report
  const gaps = metrics.missing_buckets.length + metrics.unfinished_buckets.length
  const steps: Step[] = [
    {
      title: '1. Measure the difference',
      href: '#observed-situation',
      status:
        metrics.shortfall == null
          ? `Shortfall unavailable · coverage ${words(metrics.status)}`
          : `Shortfall ${metrics.shortfall} ${words(metrics.unit)} · coverage ${words(metrics.status)}`,
      tone: metrics.shortfall ? 'limit' : 'neutral',
      next: 'Check the calculation inputs. Missing data is not counted as zero.',
    },
    {
      title: '2. Check sources and missing evidence',
      href: '#source-health',
      extra: [{ label: 'Evidence timeline', href: '#evidence-timeline' }],
      status: `${count(metrics.missing_buckets.length, 'missing bucket')} · ${count(metrics.unfinished_buckets.length, 'unfinished bucket')}`,
      tone: gaps ? 'limit' : 'neutral',
      next: 'A missing record is missing data, not lost production. Check source health before relying on the timeline.',
    },
    {
      title: '3. Check findings',
      href: '#explanations-and-open-questions',
      extra: [
        { label: 'Review proposals', href: '#recovery-options' },
        { label: 'Assigned checks', href: '#assigned-checks' },
      ],
      status: `${count(report.hypotheses.length, 'explanation')} · ${count(report.proposals.length, 'proposal')} in revision ${report.revision}`,
      tone: 'neutral',
      next: 'Read the supporting and contradicting records before choosing a cause. Assigning a check needs sign-in. Recording a review needs an invited reviewer.',
    },
    {
      title: '4. Compare revisions',
      href: compareAvailable ? '#compare-revisions' : undefined,
      status: compareAvailable
        ? `Compare with revision ${earlierRevision}`
        : saved
          ? 'Needs the live API'
          : 'No earlier revision',
      tone: 'neutral',
      next: 'Shows which source records and explanations changed between revisions.',
    },
    {
      title: '5. Export the report',
      href: '#shift-update',
      status: exportAvailable ? 'Portable export ready' : 'PDF available · JSON needs sign-in',
      tone: 'neutral',
      next: 'Print the supervisor report to save a PDF. The portable export is a JSON file of this revision.',
    },
  ]

  return (
    <aside
      className="break-words rounded-sm border border-border bg-card p-4 print:hidden"
      aria-label="Investigation guide"
    >
      <h2 className="text-base font-bold">Follow the investigation</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {saved
          ? `Saved report for revision ${viewedRevision} (${report.id}). Assignments and outcomes need the live API.`
          : viewedRevision === latestRevision
            ? `Pinned report ${report.id} for revision ${viewedRevision}, the latest. Assigned checks and the shift handover show the latest incident state, separate from this report.`
            : `You are reading revision ${viewedRevision}; the latest is revision ${latestRevision}. Assigned checks and the shift handover show the latest incident state.`}
      </p>
      <ol className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {steps.map((step) => (
          <li
            key={step.title}
            className="flex flex-col items-start gap-2 border-t border-border pt-3"
          >
            {step.href ? (
              <a
                className="inline-flex min-h-11 items-center rounded-sm font-semibold text-primary underline focus-visible:outline-2"
                href={step.href}
              >
                {step.title}
              </a>
            ) : (
              <p className="inline-flex min-h-11 items-center font-semibold">{step.title}</p>
            )}
            <StatusTag tone={step.tone}>{step.status}</StatusTag>
            <p className="text-sm text-muted-foreground">{step.next}</p>
            {step.extra?.map((link) => (
              <a
                key={link.href}
                className="inline-flex min-h-11 items-center rounded-sm text-sm font-semibold text-primary underline focus-visible:outline-2"
                href={link.href}
              >
                {link.label}
              </a>
            ))}
          </li>
        ))}
      </ol>
      <p className="mt-3 text-sm text-muted-foreground">
        “Knowledge cutoff” means the time by which evidence had reached the system. A late-arriving
        record may describe an earlier event, but appears only in a later evidence revision.
        Recording a proposal review, a check outcome and the incident resolution are separate
        decisions.
      </p>
    </aside>
  )
}
