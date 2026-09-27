/**
 * Imports (local owner): select a documented source profile, inspect the
 * normalized preview with row-level issues, publish the exact preview as
 * an immutable snapshot, then fork a scenario onto it. The public demo
 * ships these curated examples only; the backend mounts no import routes
 * in public mode.
 */

import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { api, type ImportPreview, type ImportRequestBody } from '@/lib/api'
import { CURATED_EXAMPLES, type CuratedExample } from '@/lib/examples'
import { formatInstant, shortDigest } from '@/lib/status'
import { Mono } from '@/components/status'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

const PROFILES = [
  {
    id: 'attendance-v1',
    name: 'Attendance export',
    contract: 'Required columns: operator_id, status, observed_at. Status codes: P, A, PRESENT, ABSENT, U, UNKNOWN, 1, 0, blank (blank means UNKNOWN, never absent).',
  },
  {
    id: 'skills-v1',
    name: 'Skill matrix export',
    contract: 'Required columns: operator_id, operation_id, level (1-4), assessed_at. Naive timestamps are interpreted as Asia/Kolkata.',
  },
]

function IssueList({ issues }: { issues: { code: string; severity: string; message: string }[] }) {
  if (issues.length === 0) return null
  return (
    <ul className="mt-1 space-y-0.5">
      {issues.map((issue, index) => (
        <li
          key={index}
          className={cn(
            'flex items-start gap-1.5 text-xs',
            issue.severity === 'BLOCKING' ? 'text-red-700' : 'text-amber-700',
          )}
        >
          <Badge
            variant="secondary"
            className={cn(
              'h-auto px-1 py-0 text-[10px]',
              issue.severity === 'BLOCKING' && 'border border-red-600/30 bg-red-600/10 text-red-800',
              issue.severity === 'WARNING' && 'border border-amber-600/30 bg-amber-500/15 text-amber-900',
            )}
          >
            {issue.code}
          </Badge>
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  )
}

export function ImportsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const fileInput = useRef<HTMLInputElement>(null)

  const [profileId, setProfileId] = useState('attendance-v1')
  const [csvText, setCsvText] = useState('')
  const [declaredAt, setDeclaredAt] = useState('2026-09-22T07:55:00+05:30')
  const [coverageComplete, setCoverageComplete] = useState(true)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [published, setPublished] = useState<{ snapshot_id: string; content_digest: string } | null>(null)
  const [forkError, setForkError] = useState<string | null>(null)

  const scenariosQuery = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios })

  const requestBody = useMemo<ImportRequestBody>(
    () => ({
      profile_id: profileId,
      csv_text: csvText,
      declared_evidence_at: declaredAt,
      coverage_complete: coverageComplete,
    }),
    [profileId, csvText, declaredAt, coverageComplete],
  )

  const previewMutation = useMutation({
    mutationFn: () => api.importPreview(requestBody),
    onSuccess: (data) => {
      setPreview(data)
      setPublished(null)
      setForkError(null)
    },
  })

  const publishMutation = useMutation({
    mutationFn: () =>
      api.importPublish({ ...requestBody, preview_digest: preview!.preview_digest }),
    onSuccess: (data) => {
      setPublished(data)
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
    },
  })

  function loadExample(example: CuratedExample) {
    setProfileId(example.profile_id)
    setCsvText(example.csv)
    setDeclaredAt(example.declared_evidence_at)
    setCoverageComplete(example.coverage_complete)
    setPreview(null)
    setPublished(null)
    setForkError(null)
  }

  function onFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    if (file.size > 1024 * 1024) {
      setForkError('File exceeds the 1 MiB limit.')
      return
    }
    file.text().then(setCsvText)
  }

  const forkMutation = useMutation({
    mutationFn: (input: { scenarioId: string; revision: number }) =>
      api.forkScenario(input.scenarioId, input.revision, published!.snapshot_id),
    onSuccess: (fork) => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      navigate(`/workbench?scenario=${fork.scenario_id}&revision=${fork.revision}`)
    },
    onError: (error: Error) => setForkError(error.message),
  })

  const structuralError =
    previewMutation.isError && previewMutation.error instanceof Error
      ? previewMutation.error.message
      : null

  const publishedKind = preview?.snapshot_kind
  // Hero scenarios pin both an attendance and a skills snapshot, so any
  // published import kind has something to replace.
  const forkableRevisions = publishedKind ? (scenariosQuery.data?.items ?? []) : []

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Imports</h1>
        <p className="mt-0.5 text-sm text-zinc-500">
          Upload a source export, inspect exactly what the system understood, and publish it as
          an immutable snapshot. Publication is all-or-nothing: a malformed row can never quietly
          disappear.
        </p>
      </div>

      {/* Step 1: profile */}
      <section className="space-y-2">
        <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
          Source profile
        </h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {PROFILES.map((profile) => (
            <button
              key={profile.id}
              type="button"
              aria-pressed={profileId === profile.id}
              onClick={() => setProfileId(profile.id)}
              className={cn(
                'rounded-lg border p-3 text-left text-sm transition-colors focus-visible:outline-2',
                profileId === profile.id
                  ? 'border-zinc-900 bg-zinc-900 text-white'
                  : 'border-zinc-200 bg-white hover:border-zinc-400',
              )}
            >
              <span className="font-medium">{profile.name}</span>
              <span
                className={cn(
                  'mt-1 block text-xs leading-snug',
                  profileId === profile.id ? 'text-zinc-300' : 'text-zinc-500',
                )}
              >
                {profile.contract}
              </span>
            </button>
          ))}
        </div>
      </section>

      {/* Step 2: metadata + CSV */}
      <section className="space-y-2">
        <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
          Upload and source metadata
        </h2>
        <div className="space-y-3 rounded-lg border bg-white p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs">
              <span className="mb-1 block font-medium text-zinc-600">
                Declared evidence time (when the source says this was true)
              </span>
              <input
                value={declaredAt}
                onChange={(event) => setDeclaredAt(event.target.value)}
                className="w-full rounded-md border border-zinc-300 px-2 py-1.5 font-mono text-xs focus-visible:outline-2"
                placeholder="2026-09-22T07:55:00+05:30"
              />
              <span className="mt-1 block text-zinc-400">
                Never taken from the upload clock; must carry a UTC offset.
              </span>
            </label>
            <label className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={coverageComplete}
                onChange={(event) => setCoverageComplete(event.target.checked)}
                className="mt-0.5"
              />
              <span>
                <span className="block font-medium text-zinc-600">
                  Source asserts complete coverage
                </span>
                <span className="mt-1 block text-zinc-400">
                  The application cannot prove an external export's completeness; this is the
                  importer's assertion and it is recorded on the snapshot.
                </span>
              </span>
            </label>
          </div>

          <label className="block text-xs">
            <span className="mb-1 block font-medium text-zinc-600">CSV text (UTF-8, comma, max 1 MiB / 5,000 rows)</span>
            <textarea
              value={csvText}
              onChange={(event) => setCsvText(event.target.value)}
              rows={8}
              spellCheck={false}
              className="w-full rounded-md border border-zinc-300 p-2 font-mono text-xs focus-visible:outline-2"
              placeholder="operator_id,status,observed_at&#10;O219,P,2026-09-22 07:55"
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              onChange={onFileSelected}
              className="hidden"
            />
            <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
              Choose CSV file
            </Button>
            <Separator orientation="vertical" className="h-5" />
            <span className="text-xs text-zinc-400">Curated examples:</span>
            {CURATED_EXAMPLES.map((example) => (
              <Button key={example.id} variant="secondary" size="sm" onClick={() => loadExample(example)}>
                {example.label}
              </Button>
            ))}
          </div>
        </div>
      </section>

      {/* Step 3: preview */}
      <section className="space-y-2">
        <div className="flex items-center gap-3">
          <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
            Normalized preview
          </h2>
          <Button
            size="sm"
            disabled={!csvText.trim() || previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
          >
            {previewMutation.isPending ? 'Checking…' : 'Preview'}
          </Button>
        </div>

        {previewMutation.isPending ? <Skeleton className="h-24 w-full" /> : null}

        {structuralError ? (
          <Alert variant="destructive">
            <AlertTitle>The file cannot be previewed</AlertTitle>
            <AlertDescription>{structuralError}</AlertDescription>
          </Alert>
        ) : null}

        {preview ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="secondary">{preview.counts.rows} rows</Badge>
              <Badge
                variant="secondary"
                className={cn(
                  preview.counts.blocking > 0 && 'border border-red-600/30 bg-red-600/10 text-red-800',
                )}
              >
                {preview.counts.blocking} blocking
              </Badge>
              <Badge
                variant="secondary"
                className={cn(
                  preview.counts.warning > 0 && 'border border-amber-600/30 bg-amber-500/15 text-amber-900',
                )}
              >
                {preview.counts.warning} warnings
              </Badge>
              {preview.ignored_columns.length > 0 ? (
                <span className="text-zinc-400">
                  Ignored extra columns: {preview.ignored_columns.join(', ')}
                </span>
              ) : null}
              <span className="ml-auto text-zinc-400">
                Evidence time {formatInstant(preview.declared_evidence_at)} ·{' '}
                <Mono>{shortDigest(preview.preview_digest)}</Mono>
              </span>
            </div>

            {preview.file_issues.length > 0 ? (
              <div className="rounded-lg border border-amber-600/30 bg-amber-500/10 p-2.5">
                <p className="text-xs font-semibold text-amber-900">File-level findings</p>
                <IssueList issues={preview.file_issues} />
              </div>
            ) : null}

            <div className="overflow-x-auto rounded-lg border bg-white">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">Row</TableHead>
                    <TableHead>Original cells</TableHead>
                    <TableHead>Normalized</TableHead>
                    <TableHead className="w-[34%]">Diagnostics</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.rows.map((row) => (
                    <TableRow
                      key={row.row}
                      className={
                        row.issues.some((issue) => issue.severity === 'BLOCKING')
                          ? 'bg-red-600/5'
                          : undefined
                      }
                    >
                      <TableCell>
                        <Mono className="text-zinc-400">{row.row}</Mono>
                      </TableCell>
                      <TableCell className="font-mono text-[11px] text-zinc-500">
                        {Object.entries(row.raw)
                          .filter(([, value]) => value !== '')
                          .map(([key, value]) => (
                            <span key={key} className="mr-2 inline-block">
                              {key}=<span className="text-zinc-700">{value}</span>
                            </span>
                          ))}
                      </TableCell>
                      <TableCell className="font-mono text-[11px]">
                        {Object.entries(row.normalized).map(([key, value]) => (
                          <span key={key} className="mr-2 inline-block">
                            {key}=<span className="font-semibold">{value}</span>
                          </span>
                        ))}
                        {row.normalizations.length > 0 ? (
                          <span className="mt-0.5 block text-[10px] text-blue-700">
                            {row.normalizations.join('; ')}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <IssueList issues={row.issues} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="flex items-center gap-3">
              <Button
                disabled={preview.counts.blocking > 0 || publishMutation.isPending}
                onClick={() => publishMutation.mutate()}
              >
                {publishMutation.isPending
                  ? 'Publishing…'
                  : preview.counts.blocking > 0
                    ? 'Blocked: fix the issues above'
                    : 'Publish immutable snapshot'}
              </Button>
              {publishMutation.isError ? (
                <span className="text-xs text-red-700">{publishMutation.error.message}</span>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      {/* Step 4: publish + fork */}
      {published ? (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">
            Published
          </h2>
          <div className="rounded-lg border border-emerald-600/30 bg-emerald-600/5 p-3">
            <p className="text-sm">
              Snapshot <Mono className="font-semibold">{published.snapshot_id}</Mono> is published
              and immutable.
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              Content digest <Mono>{published.content_digest}</Mono>. Corrections never edit this
              snapshot; they create a new one.
            </p>
            <Separator className="my-3" />
            <p className="text-xs font-medium text-zinc-600">
              Fork a scenario onto this evidence (a new revision; history stays untouched)
            </p>
            {scenariosQuery.isPending ? (
              <Skeleton className="mt-2 h-8 w-64" />
            ) : (
              <div className="mt-2 flex flex-wrap gap-2">
                {forkableRevisions.map((scenario) => (
                  <Button
                    key={`${scenario.scenario_id}@${scenario.revision}`}
                    variant="outline"
                    size="sm"
                    disabled={forkMutation.isPending}
                    onClick={() =>
                      forkMutation.mutate({
                        scenarioId: scenario.scenario_id,
                        revision: scenario.revision,
                      })
                    }
                  >
                    Fork {scenario.scenario_id}@{scenario.revision}
                  </Button>
                ))}
              </div>
            )}
            {forkError ? (
              <p className="mt-2 text-xs text-red-700">{forkError}</p>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  )
}
