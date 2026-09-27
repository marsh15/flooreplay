/**
 * Typed API client for the FloorReplay backend.
 *
 * Types are hand-written against the /api/v1 contracts in this milestone;
 * they will be generated from the OpenAPI schema once the comparison and
 * review surfaces stabilize, so this file is the single seam to replace.
 */

export type DomainOutcome =
  | 'NEEDS_CONTEXT'
  | 'CONFLICTING_CONTEXT'
  | 'NO_FEASIBLE_CANDIDATE'
  | 'REJECTED_BY_CONSTRAINT'
  | 'READY_FOR_REVIEW'

export type ExecutionLifecycle = 'RUNNING' | 'COMPLETED' | 'ERRORED' | 'INTERRUPTED'

export type Verdict = 'PASS' | 'FAIL' | 'NOT_EVALUATED'

export interface EvidenceRef {
  snapshot_id: string
  source_ref?: string
  field?: string
  detail?: string
}

export interface Issue {
  code: string
  severity: 'BLOCKING' | 'MATERIAL' | 'INFO'
  subject?: string
  message: string
  evidence: EvidenceRef[]
}

export interface ConstraintResult {
  code: 'C01' | 'C02' | 'C03' | 'C04' | 'C05' | 'C06' | 'C07' | 'C08' | 'C09' | 'C10' | 'C11' | 'C12'
  verdict: Verdict
  reason_code: string
  message: string
  evidence: EvidenceRef[]
}

export interface ConstraintNames {
  [code: string]: string
}

export const CONSTRAINT_NAMES: ConstraintNames = {
  C01: 'Operator exists and is active',
  C02: 'Present and not unavailable',
  C03: 'Interval fits shift and slot',
  C04: 'Skill meets requirement',
  C05: 'Skill evidence is fresh',
  C06: 'Machine exists, compatible, usable',
  C07: 'No overlapping assignment',
  C08: 'Operation belongs to style',
  C09: 'References pinned plan and slot',
  C10: 'Machine has no reservation',
  C11: 'References context digest',
  C12: 'Not the unavailable subject',
}

export interface Proposal {
  action_type: string
  operator_id: string
  target_slot_id: string
  machine_id: string
  operation_id: string
  style_id: string
  plan_revision: string
  starts_at: string
  ends_at: string
  context_digest: string
  ranking_factors: [string, string][]
}

export interface CandidateExclusion {
  operator_id: string
  issue_codes: string[]
}

export interface Abstention {
  reason_code: string
  candidate_exclusions: CandidateExclusion[]
}

export interface ReplayResult {
  outcome: DomainOutcome
  gate_issues: Issue[]
  proposal: Proposal | null
  abstention: Abstention | null
  constraints: ConstraintResult[]
  context_digest: string
  ranked_candidates: string[]
}

export interface ScenarioSummary {
  scenario_id: string
  revision: number
  title: string
  tags: string[]
  defect_statement: string
  decision_at: string
}

export interface LatestAttempt {
  scenario_id: string
  scenario_revision: number
  configuration_id: string
  domain_outcome: DomainOutcome | null
  expectation_verdict: 'PASS' | 'FAIL' | null
  created_at: string
}

export interface ScenarioListResponse {
  items: ScenarioSummary[]
  latest_attempts: LatestAttempt[]
}

export interface UnavailabilityEvent {
  kind: 'OPERATOR_UNAVAILABLE'
  subject_operator_id: string
  observed_at: string
  summary: string
  source_ref: string
}

export interface CoverageTarget {
  line_id: string
  slot_id: string
  machine_id: string
  starts_at: string
  ends_at: string
}

export interface ScenarioDetail extends ScenarioSummary {
  event: UnavailabilityEvent
  target: CoverageTarget
  catalog_revision_id: string
  pinned_snapshot_ids: string[]
}

export interface Configuration {
  id: string
  name: string
  policy_kind: string
  settings: Record<string, number>
  known_limitation: string
}

export interface SnapshotDetail {
  id: string
  kind: 'ATTENDANCE' | 'ASSIGNMENTS' | 'PLAN' | 'SKILLS' | 'MACHINE_STATE'
  source_system: string
  scope: string
  declared_evidence_at: string
  coverage_complete: boolean
  content_digest: string
  payload: Record<string, unknown>
}

export interface ReplayAttempt {
  id: string
  idempotency_key: string
  scenario_id: string
  scenario_revision: number
  configuration_id: string
  lifecycle: ExecutionLifecycle
  domain_outcome: DomainOutcome | null
  result: ReplayResult | { execution_error: { code: string; message: string } } | null
  expectation_verdict: 'PASS' | 'FAIL' | null
  expectation_failures: string[] | null
  context_digest: string | null
  manifest_digest: string | null
  created_at: string
  completed_at: string | null
  execution_kind: 'live'
}

const BASE = import.meta.env.DEV ? '/api/v1' : '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let code = 'REQUEST_FAILED'
    let message = `Request failed with status ${response.status}`
    try {
      const body = await response.json()
      code = body.code ?? code
      message = body.message ?? message
    } catch {
      // non-JSON error body; keep defaults
    }
    throw new ApiError(code, message, response.status)
  }
  return response.json() as Promise<T>
}

export class ApiError extends Error {
  code: string
  status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

export interface ImportRowIssue {
  code: string
  severity: 'BLOCKING' | 'WARNING'
  column: string
  raw_value: string
  message: string
}

export interface ImportPreviewRow {
  row: number
  raw: Record<string, string>
  normalized: Record<string, string>
  normalizations: string[]
  issues: ImportRowIssue[]
}

export interface ImportPreview {
  profile_id: string
  snapshot_kind: string
  headers: string[]
  ignored_columns: string[]
  declared_evidence_at: string
  coverage_complete: boolean
  scope: string
  preview_digest: string
  raw_digest: string
  counts: { rows: number; blocking: number; warning: number }
  rows: ImportPreviewRow[]
  file_issues: ImportRowIssue[]
}

export interface ImportPublishResult {
  snapshot_id: string
  already_published: boolean
  content_digest: string
}

export interface ImportRequestBody {
  profile_id: string
  csv_text: string
  declared_evidence_at: string
  coverage_complete: boolean
  scope?: string
}

export interface ForkResult {
  scenario_id: string
  revision: number
  title: string
  tags: string[]
  pinned_snapshot_ids: string[]
}

export const api = {
  capabilities: () =>
    request<{
      mode: string
      imports_enabled: boolean
      build_id: string
      live_parser_available: boolean
      configurations: { id: string; name: string; known_limitation: string }[]
    }>('/capabilities'),
  scenarios: () => request<ScenarioListResponse>('/scenarios'),
  scenario: (id: string, revision: number) =>
    request<ScenarioDetail>(`/scenarios/${id}/revisions/${revision}`),
  configurations: () => request<{ items: Configuration[] }>('/configurations'),
  snapshot: (id: string) => request<SnapshotDetail>(`/snapshots/${id}`),
  runReplay: (body: {
    scenario_id: string
    scenario_revision: number
    configuration_id: string
    idempotency_key: string
  }) =>
    request<ReplayAttempt>('/replays', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  replay: (id: string) => request<ReplayAttempt>(`/replays/${id}`),
  importPreview: (body: ImportRequestBody) =>
    request<ImportPreview>('/imports/preview', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  importPublish: (body: ImportRequestBody & { preview_digest: string }) =>
    request<ImportPublishResult>('/imports/publish', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  forkScenario: (scenarioId: string, revision: number, snapshotId: string) =>
    request<ForkResult>(`/scenarios/${scenarioId}/revisions/${revision}/fork`, {
      method: 'POST',
      body: JSON.stringify({ snapshot_id: snapshotId }),
    }),
}
