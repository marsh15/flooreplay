import type { components } from '@/lib/generated-api'
import { session } from '@/lib/session'
import { API_BASE, ApiError } from '@/lib/api'
import savedLibrary from '@/data/incident-library.json'
import savedRevision from '@/data/hero-revision.json'
import savedReport from '@/data/hero-report.json'
import savedEvaluation from '@/data/evaluation-report.json'

export interface IncidentSummary {
  library_group?: 'curated_demo' | 'engineering_fixture' | 'operational'
  id: string
  revision: number
  title: string
  line: string
  window_start: string
  window_end: string
  cutoff: string
  shortfall: number | null
  status: string
  evidence_completeness?: string
  last_reviewed_revision?: number | null
}

export interface IncidentSearchResult {
  id: string
  revision: number
  title: string
  line: string
  score: number
  match_reason: string
  differences: string[]
  cutoff: string
  execution_kind: string
  excerpts?: HistoricalExcerpt[]
}

export interface IncidentRevision {
  id: string
  revision: number
  title: string
  cutoff: string
  scope: { factory: string; line_id: string; order_id: string; style_id: string; stage: string; unit: string }
  window: { start: string; end: string }
  available_revisions: number[]
  events: { id: string; source_id: string; [key: string]: unknown }[]
  plan_buckets: { id: string; source_id?: string; [key: string]: unknown }[]
  output_buckets: { id: string; source_id?: string; [key: string]: unknown }[]
}

export interface IncidentMetric {
  status: string
  planned: number | null
  observed: number | null
  variance: number | null
  shortfall: number | null
  unit: string
  formula?: string
  inputs?: { start: string; end: string; plan: { id: string; quantity: number }; output: { id: string; quantity: number } }[]
  matched_buckets: string[]
  missing_buckets: string[]
  unfinished_buckets: string[]
  observation_watermark?: string
  descriptors?: AiMetric[]
  baseline_target?: number | null
  blocked_minutes?: number | null
  block_segments?: unknown[]
  target_pressure?: {
    remaining_target: number | null
    remaining_working_minutes: number
    remaining_elapsed_minutes?: number
    as_of?: string
    required_units_per_hour: number | null
    baseline_units_per_hour: number | null
    target_met: boolean | null
    assumptions: string[]
  } | null
}

export interface TimelineEvent {
  id: string
  type: string
  lane: string
  summary: string
  occurred_at?: string
  start?: string
  end?: string
  available_at?: string
  source_id?: string
  evidence_ids?: string[]
  assertion?: boolean
}

export interface Hypothesis {
  category: string
  status: string
  mechanism: string
  supporting_evidence: string[]
  contradicting_evidence: string[]
  next_check: string
}

export interface RecoveryProposal {
  id: string
  type: string
  owner_role: string
  supporting_evidence: string[]
  preconditions: string[]
  missing_information: string[]
  purpose: string
  state: string
}

export interface Precedent {
  id?: string
  incident_id?: string
  title?: string
  score?: number
  match_reasons?: string[]
  match_reason?: string
  differences?: string[]
}

export interface AnalysisReport {
  id: string
  incident_id: string
  revision: number
  cutoff: string
  metrics: IncidentMetric
  timeline: TimelineEvent[]
  hypotheses: Hypothesis[]
  proposals: RecoveryProposal[]
  precedents?: Precedent[]
  summary: string
  capabilities?: Record<string, { status: string; reasons: string[] }>
  execution_kind?: string
  created_at?: string
  reviews?: { id: string; proposal_id: string; state: string; actor: string; rationale: string; created_at: string }[]
  stale?: boolean
}

export interface EvidenceDetail {
  id?: string
  source_id?: string
  type?: string
  source_system?: string
  occurred_at?: string
  available_at?: string
  imported_at?: string
  summary?: string
  source_ref?: string
  payload?: Record<string, unknown>
  [key: string]: unknown
}

export type AiTask = 'question' | 'investigation' | 'summary' | 'recovery' | 'note'
export interface AiMetric { id: string; value: number | null; unit: string; formula?: string; input_refs?: string[] }
export interface HistoricalExcerpt { id: string; text?: string; excerpt?: string; incident_id?: string; source_id?: string }
export interface AiClaim { text: string; evidence_ids: string[]; metric_ids: string[]; historical_refs: string[]; source_fields: string[]; rendered_metrics?: AiMetric[] }
export interface AiRun {
  id: string; status: string; analysis_id: string; task: AiTask; request_key: string;
  result: { status?: string; reason?: string; errors?: string[]; output?: { claims?: AiClaim[]; selected_claims?: AiClaim[]; limitations?: string[]; abstention_reasons?: string[]; hypotheses?: { explanation: AiClaim; counterevidence_ids: string[]; limitations: string[]; next_checks: string[] }[]; assertions?: { assertion: AiClaim; source_id: string; source_span: string; mentioned_entities: string[]; uncertainty: string }[]; proposals?: { catalog_action_id: string; prerequisites: string[]; evidence_ids: string[]; owner_role: string }[]; unresolved_issues?: string[] }; validation?: { errors?: string[] } } | null;
  claim_reviews?: AiClaimReview[];
  packet?: { metrics?: AiMetric[]; historical_evidence?: HistoricalExcerpt[] };
  configuration?: { generation_model?: string; task?: AiTask };
}

export interface ReleaseEvaluationReport {
  release: string; status: string; split_counts: { historical: number; development: number; locked: number }; authored_templates: number; arithmetic_and_structure_cases_checked: number; leakage_audit: string; problems: string[]; limitations: string[]; provider: string; provider_status: string; human_support_precision: number | null
}

export interface CurrentProviderEvaluation { provider?: string; status: string; attempted?: number; completed?: number; failed?: number; running?: number; unverified_completed?: number; reviewed?: number; review_policy?: string; supported_claims?: number; reviewed_claims?: number; limitations?: string[] }

export interface IncidentEvaluationReport {
  current_provider?: CurrentProviderEvaluation
  id: string
  dataset_revision: string | number
  label_revision: string | number
  configuration: string | Record<string, unknown>
  case_count: number
  metrics: Record<string, unknown>
  failures: Record<string, unknown>[]
  cases: Record<string, unknown>[]
  retrieval_cases?: Record<string, unknown>[]
  baseline_comparison?: {
    label_revision: string
    baseline: { configuration: string; hit_at_5: { passed: number; total: number }; recall_at_5: { passed: number; total: number } }
    candidate: { configuration: string; hit_at_5: { passed: number; total: number }; recall_at_5: { passed: number; total: number } }
    failed_baseline_queries: string[]
    failed_candidate_queries: string[]
  }
  limitations: string[]
  execution_kind?: string
  runtime?: string | Record<string, unknown>
  hardware?: string | Record<string, unknown>
  model?: string | Record<string, unknown>
  created_at?: string
}

export type IncidentImportBody = Omit<components['schemas']['IncidentImportRequest'], 'profile'> & { profile: 'production-v1' | 'operations-v1' | 'notes-v1' }
export interface IncidentCsvInspection {
  headers: string[]
  sample_rows: Record<string, string>[]
  row_count: number
  fields: { name: string; required: boolean; description: string }[]
}
export type IncidentCsvInspectRequest = Omit<components['schemas']['IncidentCsvInspectRequest'], 'profile'> & { profile: IncidentImportBody['profile'] }
export type AiClaimReviewRequest = components['schemas']['AIClaimReviewRequest']
export interface AiClaimReview { id: string; run_id: string; claim_path: string; supported: boolean; actor: string; rationale?: string; output_digest?: string; created_at?: string }
export type AiRunRequest = Omit<components['schemas']['IncidentDraftRequest'], 'task' | 'retrieval_mode'> & { task: AiTask; retrieval_mode: 'evidence_only' | 'hybrid' }
export type HybridRequest = components['schemas']['HybridRequest']
export type IncidentReviewRequest = components['schemas']['IncidentReviewRequest']

export interface IncidentImportPreview {
  status: 'READY' | 'BLOCKED'
  profile: string
  source_system: string
  timezone: string
  filename: string
  raw_digest: string
  preview_digest: string
  row_count: number
  issues: { row: number; field: string; code: string; severity: string; message: string }[]
  plan_buckets: unknown[]
  output_buckets: unknown[]
  events: unknown[]
}

export type NewIncidentBody = Omit<components['schemas']['IncidentCreateRequest'], 'scope' | 'window'> & {
  scope: { factory: string; line_id: string; order_id: string; style_id: string; stage: 'sewing'; unit: 'good_units' }
  window: { start: string; end: string }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...session.headers(), ...init?.headers },
  })
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`
    let code = 'REQUEST_FAILED'
    try {
      const body = await response.json()
      message = body.message ?? body.detail ?? message
      code = body.code ?? code
    } catch { /* non-JSON response */ }
    throw new ApiError(code, String(message), response.status)
  }
  return response.json() as Promise<T>
}

function unavailable(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status >= 500
}

const savedId = savedReport.id
const savedHero = { ...savedReport, execution_kind: 'saved_deterministic' } as AnalysisReport
const savedIncident = savedRevision as IncidentRevision

const pathId = (id: string) => encodeURIComponent(id)

export const incidentApi = {
  list: async (): Promise<{ items: IncidentSummary[]; execution_kind?: string }> => {
    try { return await request<{ items: IncidentSummary[] }>('/incidents') }
    catch (error) { if (!unavailable(error)) throw error; return { items: savedLibrary.items.map((item) => ({ ...item, library_group: item.library_group === 'curated_demo' || item.library_group === 'engineering_fixture' || item.library_group === 'operational' ? item.library_group : undefined })), execution_kind: 'saved_deterministic' } }
  },
  revision: async (id: string, revision: number): Promise<IncidentRevision> => {
    try { return await request<IncidentRevision>(`/incidents/${pathId(id)}/revisions/${revision}`) }
    catch (error) { if (id !== savedIncident.id || revision !== savedIncident.revision || !(unavailable(error) || error instanceof ApiError && error.status === 404)) throw error; return savedIncident }
  },
  analyze: async (id: string, revision: number): Promise<AnalysisReport> => {
    try { return await request<AnalysisReport>(`/incidents/${pathId(id)}/analyses`, {
      method: 'POST', body: JSON.stringify({ revision, idempotency_key: crypto.randomUUID() } satisfies components['schemas']['IncidentAnalysisRequest']),
    }) }
    catch (error) { if (id !== savedHero.incident_id || revision !== savedHero.revision || !(unavailable(error) || error instanceof ApiError && error.status === 404)) throw error; return savedHero }
  },
  analysis: async (id: string): Promise<AnalysisReport> => {
    try { return await request<AnalysisReport>(`/analyses/${pathId(id)}`) }
    catch (error) { if (id !== savedId || !(unavailable(error) || error instanceof ApiError && error.status === 404)) throw error; return savedHero }
  },
  evidence: async (analysisId: string, evidenceId: string): Promise<EvidenceDetail> => {
    try { return await request<EvidenceDetail>(`/analyses/${pathId(analysisId)}/evidence/${pathId(evidenceId)}`) }
    catch (error) {
      if (analysisId !== savedId || !(unavailable(error) || error instanceof ApiError && error.status === 404)) throw error
      const record = [...savedIncident.events, ...savedIncident.plan_buckets, ...savedIncident.output_buckets].find((item) => item.id === evidenceId)
      if (!record) throw error
      return { id: evidenceId, source_id: record.source_id ?? `synthetic-fixture:${savedIncident.id}@${savedIncident.revision}/${evidenceId}`, record, incident_id: savedIncident.id, revision: savedIncident.revision }
    }
  },
  search: (query: string) => request<{ items: IncidentSearchResult[]; execution_kind: string }>(`/incidents/search?q=${encodeURIComponent(query)}`),
  submitProposal: (analysisId: string, proposalId: string) =>
    request<{ id: string; state: string }>(`/analyses/${pathId(analysisId)}/proposals/${pathId(proposalId)}/submit`, {
      method: 'POST', body: JSON.stringify({ idempotency_key: crypto.randomUUID(), rationale: 'Submitted for review against the cited evidence.', decision: 'PENDING_REVIEW' } satisfies IncidentReviewRequest),
    }),
  reviewProposal: (analysisId: string, proposalId: string, decision: 'APPROVED' | 'REJECTED', rationale: string) =>
    request<{ id: string; state: string }>(`/analyses/${pathId(analysisId)}/proposals/${pathId(proposalId)}/review`, {
      method: 'POST', body: JSON.stringify({ decision, rationale, idempotency_key: crypto.randomUUID() } satisfies IncidentReviewRequest),
    }),
  exportReport: async (analysisId: string) => {
    const response = await fetch(`${API_BASE}/analyses/${pathId(analysisId)}/export`, { headers: session.headers() })
    if (!response.ok) throw new ApiError('EXPORT_FAILED', 'Report export unavailable. Sign in as a reviewer.', response.status)
    return response.blob()
  },
  createAiRun: (analysisId: string, body: AiRunRequest) => request<AiRun>(`/analyses/${pathId(analysisId)}/ai-runs`, { method: 'POST', body: JSON.stringify(body) }),
  aiRunByRequest: (key: string) => request<AiRun>(`/ai-runs/by-request/${pathId(key)}`),
  reviewAiClaim: (runId: string, body: AiClaimReviewRequest) => request<AiClaimReview>(`/ai-runs/${pathId(runId)}/claim-review`, { method: 'POST', body: JSON.stringify(body) }),
  aiRun: (id: string) => request<AiRun>(`/ai-runs/${pathId(id)}`),
  usage: () => request<{ total_ceiling_inr: number; committed_inr: number; available_inr: number; active_operations: number; purpose_available_inr: Record<string, number>; entries: { id: string; status: string; charged_inr: number; reserved_inr: number; purpose: string; operation: string }[] }>('/usage'),
  corpora: () => request<{ items: { id: string; indexed?: boolean }[] }>('/corpora'),
  hybridSearch: (body: HybridRequest) => request<{ results: IncidentSearchResult[]; manifest: { corpus_id: string; corpus_digest: string; cutoff: string } }>('/incidents/search/hybrid', { method: 'POST', body: JSON.stringify(body) }),
  releaseEvaluation: () => request<ReleaseEvaluationReport>('/evaluation-reports/incident-release-v1'),
  evaluationReport: async (id: string): Promise<IncidentEvaluationReport> => {
    try { return await request<IncidentEvaluationReport>(`/evaluation-reports/${pathId(id)}`) }
    catch (error) {
      if (id !== savedEvaluation.id || !unavailable(error)) throw error
      return savedEvaluation as IncidentEvaluationReport
    }
  },
  inspectCsv: (body: IncidentCsvInspectRequest) => request<IncidentCsvInspection>('/incidents/imports/inspect', { method: 'POST', body: JSON.stringify(body) }),
  previewImport: (body: IncidentImportBody) => request<IncidentImportPreview>('/incidents/imports/preview', { method: 'POST', body: JSON.stringify(body) }),
  publishImport: (body: IncidentImportBody, previewDigest: string, idempotencyKey: string) => request<IncidentRevision>('/incidents/imports/publish', { method: 'POST', body: JSON.stringify({ ...body, preview_digest: previewDigest, idempotency_key: idempotencyKey } satisfies components['schemas']['IncidentPublishRequest']) }),
  createIncident: (body: NewIncidentBody) => request<IncidentRevision>('/incidents', { method: 'POST', body: JSON.stringify(body) }),
}
