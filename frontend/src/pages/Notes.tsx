import { useAuth } from '@/components/Auth'
/**
 * Floor notes (local owner): enter a note, extract a draft, inspect
 * uncertainty and mention resolution, confirm a structured event, and fork
 * a scenario onto it. The model only drafts; a human confirms. Manual
 * structured entry is always available, including when parsing fails.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api, type NoteParseResult } from '@/lib/api'
import { Mono } from '@/components/status'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { cn } from '@/lib/utils'

const EXAMPLE_NOTE =
  'O117 called in sick at 07:52, cannot run sleeve attach on Line 4 today. Supervisor confirmed by phone.'

function StatusChip({ status }: { status: string }) {
  const tone =
    status === 'RESOLVED'
      ? 'border-emerald-600/30 bg-emerald-600/10 text-emerald-800'
      : status === 'AMBIGUOUS'
        ? 'border-amber-600/30 bg-amber-500/15 text-amber-900'
        : 'border-zinc-300 bg-zinc-100 text-zinc-600'
  return (
    <Badge variant="outline" className={cn('text-[10px]', tone)}>
      {status.toLowerCase()}
    </Badge>
  )
}

export function NotesPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const capabilities = useQuery({ queryKey: ['capabilities', user?.id ?? 'public'], queryFn: api.capabilities })
  const canAuthor = capabilities.data?.mode === 'local' && capabilities.data.imports_enabled
  const [noteText, setNoteText] = useState(EXAMPLE_NOTE)
  const [parse, setParse] = useState<NoteParseResult | null>(null)
  // The exact text the current draft was extracted from; a draft is only
  // attributable to the note it parsed, so confirming cites the parser call
  // only while the text is unchanged.
  const [parsedText, setParsedText] = useState('')
  const [confirmed, setConfirmed] = useState<{ scenario_id: string; revision: number } | null>(null)

  const scenariosQuery = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios })
  const scenarios = scenariosQuery.data?.items ?? []
  const [scenarioKey, setScenarioKey] = useState('')
  const selectedScenario =
    scenarios.find((s) => `${s.scenario_id}@${s.revision}` === scenarioKey) ?? scenarios[0]

  const [operatorId, setOperatorId] = useState('')
  const [observedAt, setObservedAt] = useState('2026-09-22T07:52:00+05:30')
  const [summary, setSummary] = useState('')
  const [sourceKind, setSourceKind] = useState<'note' | 'manual'>('note')

  const draftIsCurrent = parse !== null && parsedText === noteText

  const parseMutation = useMutation({
    mutationFn: () => api.parseNote(noteText),
    onSuccess: (data) => {
      setParse(data)
      setParsedText(noteText)
      setConfirmed(null)
      const resolved = data.resolution.operators.find((o) => o.status === 'RESOLVED')
      if (resolved?.resolved_id) setOperatorId(resolved.resolved_id)
      setSummary(noteText.slice(0, 200))
    },
  })

  const confirmMutation = useMutation({
    mutationFn: () =>
      api.confirmNote({
        scenario_id: selectedScenario.scenario_id,
        scenario_revision: selectedScenario.revision,
        subject_operator_id: operatorId,
        observed_at: observedAt,
        summary: summary || 'Confirmed unavailability event.',
        source_kind: sourceKind,
        parser_call_id:
          sourceKind === 'note' && draftIsCurrent ? parse?.parser_call_id ?? null : null,
        corrections:
          draftIsCurrent && parse && parse.draft.raw_temporal_expressions.length > 0
            ? { observed_at: `draft mentioned: ${parse.draft.raw_temporal_expressions.join(', ')}` }
            : undefined,
      }),
    onSuccess: (data) => {
      setConfirmed({ scenario_id: data.scenario_id, revision: data.revision })
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
    },
  })

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Floor notes</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">
          The parser produces a draft, never an event. Mentions resolve by exact id or curated
          alias; ambiguity stays ambiguous. A human confirms the structured event, which forks a
          new scenario revision. History is never rewritten.
        </p>
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-800">
          Note (English, max 2,000 characters)
        </h2>
        <textarea
          value={noteText}
          onChange={(event) => setNoteText(event.target.value)}
          rows={4}
          className="w-full rounded-md border border-zinc-300 bg-white p-2 font-mono text-xs focus-visible:outline-2"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={!canAuthor || !noteText.trim() || noteText.length > 2000 || parseMutation.isPending}
            onClick={() => parseMutation.mutate()}
          >
            {parseMutation.isPending ? 'Extracting draft…' : 'Extract draft'}
          </Button>
          {!canAuthor && <p className="text-xs text-zinc-600">Sign in as an owner in the local deployment to extract or confirm archived floor notes.</p>}
          <Button size="sm" variant="outline" onClick={() => { setParse(null); setSourceKind('manual') }}>
            Skip parsing: manual entry
          </Button>
          <span className="ml-auto text-xs text-zinc-600">
            {parse ? (
              <>
                draft by <Mono>{parse.parser_kind}</Mono>
                {parse.live ? ' (live model)' : ' (offline rule baseline; no API key configured)'}
              </>
            ) : null}
          </span>
        </div>
        {parseMutation.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Draft extraction failed</AlertTitle>
            <AlertDescription>
              {parseMutation.error.message}. Manual structured entry below remains available.
            </AlertDescription>
          </Alert>
        ) : null}
      </section>

      {parse ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-zinc-800">
            Draft and resolution
          </h2>
          {!draftIsCurrent ? (
            <p className="rounded-md border border-amber-600/30 bg-amber-500/10 p-2 text-xs text-amber-900">
              The note was edited after this draft was extracted, so the draft below is stale.
              Re-extract to refresh it; confirming now records the event without citing the
              parser.
            </p>
          ) : null}
          <div className="space-y-2 rounded-lg border bg-white p-3 text-sm">
            <p>
              Category <Mono className="font-semibold">{parse.draft.event_category}</Mono> ·
              polarity <Mono>{parse.draft.polarity}</Mono>
              {parse.draft.uncertainty_phrase ? (
                <>
                  {' '}
                  · uncertainty <Mono>{parse.draft.uncertainty_phrase}</Mono>
                </>
              ) : null}
            </p>
            <ul className="space-y-1">
              {parse.resolution.operators.map((entry) => (
                <li key={entry.raw} className="flex items-center gap-2 text-xs">
                  <Mono>{entry.raw}</Mono>
                  <StatusChip status={entry.status} />
                  {entry.resolved_id ? (
                    <Mono className="font-semibold">{entry.resolved_id}</Mono>
                  ) : null}
                  {entry.candidates.length > 1 ? (
                    <span className="text-amber-700">candidates: {entry.candidates.join(', ')}</span>
                  ) : null}
                </li>
              ))}
              {parse.resolution.operations.map((entry) => (
                <li key={entry.raw} className="flex items-center gap-2 text-xs">
                  <Mono>{entry.raw}</Mono>
                  <StatusChip status={entry.status} />
                  {entry.resolved_id ? (
                    <Mono className="font-semibold">{entry.resolved_id}</Mono>
                  ) : null}
                </li>
              ))}
            </ul>
            {parse.draft.raw_temporal_expressions.length > 0 ? (
              <p className="text-xs text-zinc-500">
                Raw time expressions ({parse.draft.raw_temporal_expressions.join(', ')}) must be
                resolved to an explicit instant below.
              </p>
            ) : null}
            {parse.draft.ambiguity_notes.length > 0 ? (
              <p className="text-xs text-amber-700">{parse.draft.ambiguity_notes.join(' ')}</p>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-800">
          Confirm structured event
        </h2>
        <div className="grid gap-3 rounded-lg border bg-white p-3 sm:grid-cols-2">
          {scenariosQuery.isError ? (
            <p className="text-xs text-red-700 sm:col-span-2">
              Scenarios could not be loaded: {scenariosQuery.error.message}
            </p>
          ) : null}
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-zinc-600">Fork onto scenario revision</span>
            <select
              value={selectedScenario ? `${selectedScenario.scenario_id}@${selectedScenario.revision}` : ''}
              onChange={(event) => setScenarioKey(event.target.value)}
              className="w-full rounded-md border border-zinc-300 px-2 py-1.5 text-sm focus-visible:outline-2"
            >
              {scenarios.map((scenario) => (
                <option key={`${scenario.scenario_id}@${scenario.revision}`} value={`${scenario.scenario_id}@${scenario.revision}`}>
                  {scenario.scenario_id}@{scenario.revision} · {scenario.title.slice(0, 44)}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-zinc-600">Unavailable operator</span>
            <input
              value={operatorId}
              onChange={(event) => setOperatorId(event.target.value.toUpperCase())}
              placeholder="O117"
              className="w-full rounded-md border border-zinc-300 px-2 py-1.5 font-mono text-sm focus-visible:outline-2"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-zinc-600">
              Observed at (explicit UTC offset required)
            </span>
            <input
              value={observedAt}
              onChange={(event) => setObservedAt(event.target.value)}
              className="w-full rounded-md border border-zinc-300 px-2 py-1.5 font-mono text-xs focus-visible:outline-2"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block font-medium text-zinc-600">Summary</span>
            <input
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              placeholder="Confirmed from floor note"
              className="w-full rounded-md border border-zinc-300 px-2 py-1.5 text-sm focus-visible:outline-2"
            />
          </label>
        </div>
        <div className="flex items-center gap-3">
          <Button
            disabled={!canAuthor || !selectedScenario || !operatorId || confirmMutation.isPending}
            onClick={() => confirmMutation.mutate()}
          >
            {confirmMutation.isPending ? 'Confirming…' : 'Confirm event and fork revision'}
          </Button>
          <label className="flex items-center gap-1.5 text-xs text-zinc-500">
            <input
              type="radio"
              checked={sourceKind === 'note'}
              onChange={() => setSourceKind('note')}
            />
            from parsed note
          </label>
          <label className="flex items-center gap-1.5 text-xs text-zinc-500">
            <input
              type="radio"
              checked={sourceKind === 'manual'}
              onChange={() => setSourceKind('manual')}
            />
            manual entry
          </label>
          {confirmMutation.isError ? (
            <span className="text-xs text-red-700">{confirmMutation.error.message}</span>
          ) : null}
        </div>
      </section>

      {confirmed ? (
        <section className="space-y-2">
          <div className="rounded-lg border border-emerald-600/30 bg-emerald-600/5 p-3">
            <p className="text-sm">
              Confirmed. New revision <Mono className="font-semibold">{confirmed.scenario_id}@{confirmed.revision}</Mono>{' '}
              carries the event; the original revision is untouched.
            </p>
            <Separator className="my-2" />
            <Link
              to={`/coverage/workbench?scenario=${confirmed.scenario_id}&revision=${confirmed.revision}`}
              className="text-sm underline underline-offset-4 hover:no-underline focus-visible:outline-2"
            >
              Open it in the replay workbench
            </Link>
          </div>
        </section>
      ) : null}
    </div>
  )
}
