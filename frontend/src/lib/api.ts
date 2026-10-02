import { session } from '@/lib/session'
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

// Dev uses the Vite proxy; a deployed static build points at the backend
// origin via VITE_API_BASE (e.g. https://flooreplay-api.onrender.com/api/v1).
// Exported so non-fetch consumers (e.g. the report download link) share it.
export const API_BASE: string = (import.meta.env.VITE_API_BASE || '/api/v1').replace(/\/$/, '')
const BASE: string = API_BASE

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...session.headers(), ...init?.headers },
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
    throw new ApiError(code, message, response.status, response.headers.get('X-Request-ID') ?? undefined)
  }
  return response.json() as Promise<T>
}

export class ApiError extends Error {
  code: string
  status: number

  requestId?: string

  constructor(code: string, message: string, status: number, requestId?: string) {
    super(requestId ? `${message} Request ${requestId}.` : message)
    this.requestId = requestId
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

export type Classification = 'UNCHANGED_PASS' | 'FIXED' | 'REGRESSION' | 'UNCHANGED_FAIL' | 'NOT_COMPARABLE'

export interface ComparisonSide {
  outcome: DomainOutcome | null
  verdict: 'PASS' | 'FAIL' | 'NOT_EVALUATED'
  operator: string | null
  issue_codes: string[]
  failures: string[]
}

export interface ComparisonItem {
  scenario_id: string
  title: string
  category: string
  defect_statement: string
  baseline: ComparisonSide
  candidate: ComparisonSide
  classification: Classification
  behavior_changed: boolean
}

export interface ComparisonReport {
  id: string
  suite_id: string
  suite_revision: number
  baseline_config_id: string
  candidate_config_id: string
  status: 'COMPLETED' | 'INTERRUPTED'
  totals: {
    fixed: number
    regression: number
    unchanged_pass: number
    unchanged_fail: number
    completed: number
    total: number
  }
  created_at: string
  manifest_digest?: string
  items?: ComparisonItem[]
  execution_kind?: 'live'
}

export interface SuiteSummary {
  id: string
  revision: number
  label: string
  case_count: number
  content_digest: string
}

export interface NoteDraft {
  event_category: string
  subject_mentions: string[]
  operation_mentions: string[]
  polarity: string
  uncertainty_phrase: string | null
  raw_temporal_expressions: string[]
  ambiguity_notes: string[]
}

export interface MentionResolutionView {
  raw: string
  resolved_id: string | null
  status: 'RESOLVED' | 'AMBIGUOUS' | 'UNKNOWN'
  candidates: string[]
}

export interface NoteParseResult {
  parser_call_id: string
  parser_kind: string
  live: boolean
  draft: NoteDraft
  resolution: { operators: MentionResolutionView[]; operations: MentionResolutionView[] }
}

export interface NoteConfirmResult {
  scenario_id: string
  revision: number
  event: { subject_operator_id: string; observed_at: string; summary: string; source_ref: string }
  corrections: Record<string, string>
  parser_call_id: string | null
  pinned_snapshot_ids: string[]
}

export interface ReviewCheckResult {
  id: string
  original_replay_id: string
  target_scenario_id: string
  target_scenario_revision: number
  outcome: 'STILL_SUPPORTED' | 'STALE_RECOMMENDATION' | 'BLOCKED_CONTEXT'
  changed_paths: string[]
  reason_codes: string[]
  issues: { code: string; message: string }[]
  target_context_digest: string | null
  created_at: string
  original_untouched: boolean
}

export const api = {
  capabilities: () =>
    request<{
      mode: string
      imports_enabled: boolean
      reviews_enabled?: boolean
      export_enabled?: boolean
      ai?: { generation_available: boolean; reason: string | null; provider: string; model: string; index_ready: boolean; evaluation_status: string }
      build_id: string
      live_parser_available: boolean
      execution_limits: {
        replays_per_hour_per_client: number | null
        comparison_execution: 'local_only' | 'open'
        saved_report_fallback: string
      }
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
  latestReplay: (scenarioId: string, revision: number, configurationId: string) =>
    request<ReplayAttempt>(
      `/replays/latest?scenario_id=${encodeURIComponent(scenarioId)}&scenario_revision=${revision}&configuration_id=${encodeURIComponent(configurationId)}`,
    ),
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
  suites: () => request<{ items: SuiteSummary[] }>('/suites'),
  comparisons: () => request<{ items: ComparisonReport[] }>('/comparisons'),
  comparison: (id: string) => request<ComparisonReport>(`/comparisons/${id}`),
  runComparison: (body: {
    suite_id: string
    baseline_config_id: string
    candidate_config_id: string
    idempotency_key: string
  }) =>
    request<ComparisonReport>('/comparisons', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  parseNote: (text: string) =>
    request<NoteParseResult>('/notes/parse', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  confirmNote: (body: {
    scenario_id: string
    scenario_revision: number
    subject_operator_id: string
    observed_at: string
    summary: string
    source_kind: 'note' | 'manual'
    parser_call_id?: string | null
    corrections?: Record<string, string>
  }) =>
    request<NoteConfirmResult>('/notes/confirm', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  reviewCheck: (body: {
    original_replay_id: string
    target_scenario_id: string
    target_scenario_revision: number
  }) =>
    request<ReviewCheckResult>('/review-checks', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}
